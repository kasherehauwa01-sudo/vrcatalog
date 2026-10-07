"""Validated, transactional hierarchy synchronization shared by worker and admin API."""
from datetime import datetime, timedelta
from html.parser import HTMLParser
import logging
import re
import threading
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from sqlalchemy import Column, Integer, MetaData, String, Table, func, select, text, update
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.catalog import CatalogCategory, CatalogSectionMapping, CatalogSyncState, Product
from app.services.logging import add_log

SOURCE_URL = "https://volgorost.ru/catalog/ves-katalog/"
LOCK_KEY = 82461931
_local_lock = threading.Lock()
logger = logging.getLogger(__name__)


def normalize_section(value):
    return " ".join((value or "").split()).lower().replace("ё", "е")


class CatalogParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = {}

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        attrs = dict(attrs)
        url = urlsplit(attrs.get("href") or "")
        if url.scheme not in {"", "http", "https"} or url.netloc not in {"", "volgorost.ru", "www.volgorost.ru"} or url.query or url.fragment:
            return
        # Only directory links, never product .html URLs or deeper paths.
        match = re.fullmatch(r"/catalog/([a-z0-9_-]+)/(?:([a-z0-9_-]+)/)?", url.path)
        if not match or any(part in {"ves-katalog", "compare", "search", "filter", "favorites", "cart"} for part in match.groups()):
            return
        name = " ".join((attrs.get("title") or "").split())
        if not name or len(name) > 255:
            return
        previous = self.links.get(url.path)
        if previous and previous != name:
            raise ValueError(f"Противоречивые названия: {url.path}")
        self.links[url.path] = name


def parse_catalog(html):
    parser = CatalogParser()
    parser.feed(html)
    categories = []
    sections = []
    for path, name in parser.links.items():
        parts = path.strip("/").split("/")
        if len(parts) == 2:
            categories.append({"name": name, "source_path": path, "sort_order": len(categories)})
        else:
            parent = f"/catalog/{parts[1]}/"
            if parent not in parser.links:
                raise ValueError(f"Подкатегория без родителя: {path}")
            sections.append({"name": name, "source_path": path, "parent": parent, "sort_order": len(sections)})
    return categories, sections


def validate_catalog(categories, sections, previous_categories=0, previous_sections=0):
    # Floors are safety thresholds, not expected catalog sizes. Relative checks
    # also reject a partial HTML response after a successful synchronization.
    if len(categories) < 10 or len(sections) < 100:
        raise ValueError("Подозрительно малый или пустой каталог (минимум 10 категорий и 100 разделов)")
    if len(categories) < previous_categories * .75 or len(sections) < previous_sections * .75:
        raise ValueError("Каталог сократился более чем на 25%; сохранена последняя успешная структура")
    parents = {s["parent"] for s in sections}
    if any(c["source_path"] not in parents for c in categories):
        raise ValueError("Обнаружена категория без подкатегорий")


def fetch_catalog():
    request = Request(SOURCE_URL, headers={"User-Agent": "VR-Catalog/1.0 catalog-sync"})
    with urlopen(request, timeout=20) as response:
        if urlsplit(response.url).hostname not in {"volgorost.ru", "www.volgorost.ru"}:
            raise ValueError("Неожиданный адрес каталога")
        raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("Ответ каталога слишком большой")
        return raw.decode(response.headers.get_content_charset() or "utf-8")


def lock_import(db):
    """Serialize XML writes against sync, including multi-process deployments."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK_KEY})


def category_lookup(db):
    rows = db.query(CatalogSectionMapping.normalized_name, CatalogCategory.id, CatalogCategory.name).join(
        CatalogCategory, CatalogCategory.id == CatalogSectionMapping.category_id
    ).filter(CatalogSectionMapping.active.is_(True), CatalogCategory.active.is_(True)).all()
    result, ambiguous = {}, set()
    for key, category_id, name in rows:
        if key in result and result[key][0] != category_id:
            ambiguous.add(key)
        result[key] = (category_id, name)
    return {key: value for key, value in result.items() if key not in ambiguous}


def refresh_products(db):
    """One product UPDATE, lookup work proportional to distinct sections only."""
    lookup = category_lookup(db)
    sections = db.scalars(select(Product.section).where(Product.section.isnot(None)).distinct()).all()
    staging = Table("catalog_category_refresh", MetaData(),
        Column("section", String(255), primary_key=True),
        Column("category_id", Integer), Column("category1", String(255)), prefixes=["TEMPORARY"])
    staging.create(db.connection())
    try:
        values = []
        for section in sections:
            category_id, name = lookup.get(normalize_section(section), (None, None))
            values.append({"section": section, "category_id": category_id, "category1": name})
        if values:
            db.execute(staging.insert(), values)
        category_id = select(staging.c.category_id).where(staging.c.section == Product.section).scalar_subquery()
        category1 = select(staging.c.category1).where(staging.c.section == Product.section).scalar_subquery()
        db.execute(update(Product).where(
            Product.category_id.is_distinct_from(category_id) | Product.category1.is_distinct_from(category1)
        ).values(category_id=category_id, category1=category1, updated_at=Product.updated_at),
            execution_options={"synchronize_session": False})
    finally:
        staging.drop(db.connection())


def apply_catalog(db, categories, sections):
    existing = {c.source_path: c for c in db.query(CatalogCategory).all()}
    mappings = {s.source_path: s for s in db.query(CatalogSectionMapping).all()}
    for item in existing.values():
        item.active = False
    for item in mappings.values():
        item.active = False
    for row in categories:
        item = existing.get(row["source_path"])
        if item is None:
            item = CatalogCategory(**row)
            db.add(item)
            existing[row["source_path"]] = item
        item.name, item.sort_order, item.active = row["name"], row["sort_order"], True
    db.flush()
    for row in sections:
        item = mappings.get(row["source_path"])
        if item is None:
            item = CatalogSectionMapping(source_path=row["source_path"])
            db.add(item)
        item.name = row["name"]
        item.normalized_name = normalize_section(row["name"])
        item.category_id = existing[row["parent"]].id
        item.sort_order, item.active = row["sort_order"], True
    db.flush()
    refresh_products(db)


def sync_categories(*, scheduled=False):
    if not _local_lock.acquire(blocking=False):
        return {"status": "busy"}
    try:
        # Pin a connection: session-level advisory lock survives status commits.
        with engine.connect() as connection:
            postgres = connection.dialect.name == "postgresql"
            locked = False
            try:
                if postgres:
                    locked = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY})
                    connection.commit()
                    if not locked:
                        return {"status": "busy"}
                with Session(bind=connection) as db:
                    state = db.get(CatalogSyncState, 1)
                    if state is None:
                        state = CatalogSyncState(id=1)
                        db.add(state)
                    now = datetime.utcnow()
                    if scheduled and state.last_attempt_at and now - state.last_attempt_at < timedelta(days=1):
                        return {"status": "not_due"}
                    state.last_attempt_at, state.status = now, "running"
                    db.commit()
                    try:
                        categories, sections = parse_catalog(fetch_catalog())
                        validate_catalog(categories, sections, state.category_count, state.section_count)
                        apply_catalog(db, categories, sections)
                        state.status, state.last_error = "success", None
                        state.last_success_at = datetime.utcnow()
                        state.category_count, state.section_count = len(categories), len(sections)
                        add_log(db, "catalog_sync_success", f"Категорий: {len(categories)}; разделов: {len(sections)}")
                        db.commit()
                    except Exception as exc:
                        db.rollback()
                        logger.exception("Catalog synchronization failed")
                        state = db.get(CatalogSyncState, 1)
                        state.status, state.last_error = "failed", str(exc)[:2000]
                        add_log(db, "catalog_sync_error", state.last_error, "error")
                        db.commit()
                    return sync_status(db)
            finally:
                if locked:
                    connection.rollback()
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
                    connection.commit()
    finally:
        _local_lock.release()


def run_category_sync_if_due():
    try:
        sync_categories(scheduled=True)
    except Exception:
        logger.exception("Unable to run catalog synchronization")


def unmatched_sections(db):
    return [{"name": name, "product_count": count} for name, count in db.query(
        Product.section, func.count(Product.id)
    ).filter(Product.category_id.is_(None), Product.section.isnot(None), func.trim(Product.section) != "").group_by(
        Product.section).order_by(Product.section).all()]


def sync_status(db):
    state = db.get(CatalogSyncState, 1)
    fields = ("status", "last_attempt_at", "last_success_at", "category_count", "section_count", "last_error")
    return {**({key: getattr(state, key) for key in fields} if state else {"status": "pending"}),
            "unmatched_sections": unmatched_sections(db)}


def category_tree(db):
    categories = db.query(CatalogCategory).filter_by(active=True).order_by(CatalogCategory.sort_order, CatalogCategory.id).all()
    nodes = {c.id: {"id": c.id, "name": c.name, "subcategories": []} for c in categories}
    # Use real XML spellings for exact legacy section filtering; include empty
    # source sections too, but never hide real products without a mapping.
    lookup = category_lookup(db)
    rows = db.query(Product.section, Product.category_id, func.count(Product.id)).filter(
        Product.section.isnot(None), func.trim(Product.section) != ""
    ).group_by(Product.section, Product.category_id).order_by(Product.section).all()
    unknown, represented = [], set()
    for name, category_id, count in rows:
        item = {"name": name, "product_count": count}
        if category_id in nodes:
            nodes[category_id]["subcategories"].append(item)
            represented.add((category_id, normalize_section(name)))
        else:
            unknown.append(item)
    for row in db.query(CatalogSectionMapping).filter_by(active=True).order_by(CatalogSectionMapping.sort_order, CatalogSectionMapping.id):
        key = (row.category_id, row.normalized_name)
        if key not in represented and row.category_id in nodes and lookup.get(row.normalized_name, (None,))[0] == row.category_id:
            nodes[row.category_id]["subcategories"].append({"name": row.name, "product_count": 0})
            represented.add(key)
    result = list(nodes.values())
    if unknown:
        result.append({"id": None, "name": "Без категории", "subcategories": unknown})
    return result
