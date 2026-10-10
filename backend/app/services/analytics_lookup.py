"""Read-only, bounded analytics projection; independent of the full batch-info API."""
import logging
import time

from sqlalchemy import String, and_, cast, func, literal, or_, select, union_all
from sqlalchemy.orm import Session

from app.models.catalog import Product, ProductProperty
from app.schemas.analytics_lookup import (
    AnalyticsLookupItemIn,
    AnalyticsLookupItemOut,
    AnalyticsLookupResponse,
    AnalyticsProductOut,
)

logger = logging.getLogger(__name__)

# These are batch-info's fallback aliases, not all XML importer aliases.
PROPERTY_ALIASES = {
    "manufacturer": ("производитель", "manufacturer"),
    "brand": ("бренд", "brand"),
    "legacy_category": ("категория", "category"),
    "material": ("материал", "material"),
}
# Match Python str.strip() for property names/values, including XML whitespace.
PROPERTY_WHITESPACE = "\t\n\v\f\r\x1c\x1d\x1e\x1f \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"


def _clean(value):
    return (value or "").strip() or None


def _matching_query(items):
    ids = {item.product_id for item in items if item.product_id is not None}
    codes = {item.code.casefold() for item in items if item.product_id is None and item.code}
    articles = {item.article.casefold() for item in items if item.product_id is None and item.article}
    queries = []
    if ids:
        queries.append(select(
            literal("product_id").label("kind"), cast(Product.id, String).label("key"),
            Product.id.label("first_id"), Product.id.label("last_id"),
        ).where(Product.id.in_(ids)))
    for kind, column, values in (("code", Product.code, codes), ("article", Product.article, articles)):
        if values:
            normalized = func.lower(func.trim(column))
            # At most one aggregate row per requested key, even for many duplicates.
            # min != max means ambiguous; neither ID is silently selected.
            queries.append(select(
                literal(kind).label("kind"), normalized.label("key"),
                func.min(Product.id).label("first_id"), func.max(Product.id).label("last_id"),
            ).where(normalized.in_(values)).group_by(normalized))
    return union_all(*queries) if len(queries) > 1 else queries[0]


def _resolve(item, matches):
    if item.product_id is not None:
        kinds = (("product_id", str(item.product_id)),)
    else:
        kinds = tuple((kind, value.casefold()) for kind, value in (
            ("code", item.code), ("article", item.article),
        ) if value)
    for kind, key in kinds:
        match = matches.get((kind, key))
        if match is not None:
            if match.first_id != match.last_id:
                return "ambiguous", None, None
            return "matched", kind, match.first_id
    return "not_found", None, None


def _load_properties(db, products, metrics):
    missing = {
        field: {product_id for product_id, product in products.items() if product[field] is None}
        for field in PROPERTY_ALIASES
    }
    name = func.lower(func.trim(ProductProperty.name, PROPERTY_WHITESPACE))
    value = func.trim(ProductProperty.value, PROPERTY_WHITESPACE)
    conditions = [
        and_(name == "horeca", func.lower(value) == "horeca"),
    ]
    for field, ids in missing.items():
        if ids:
            conditions.append(and_(ProductProperty.product_id.in_(ids), name.in_(PROPERTY_ALIASES[field])))
    query = (
        select(ProductProperty.product_id, ProductProperty.name, ProductProperty.value)
        .where(ProductProperty.product_id.in_(products), value != "", or_(*conditions))
        # Keep batch-info's tie order for differently cased equivalent values.
        .order_by(ProductProperty.product_id, ProductProperty.name, ProductProperty.value, ProductProperty.id)
        .execution_options(yield_per=250)
    )
    # Retain only the best fallback per field, not all properties of the page.
    best = {}
    started = time.perf_counter()
    result = db.execute(query)
    metrics["properties_sql_ms"] += (time.perf_counter() - started) * 1000
    try:
        while True:
            started = time.perf_counter()
            rows = result.fetchmany(250)
            metrics["properties_sql_ms"] += (time.perf_counter() - started) * 1000
            if not rows:
                break
            metrics["properties_rows"] += len(rows)
            for product_id, raw_name, raw_value in rows:
                property_name = raw_name.strip()
                property_value = raw_value.strip()
                key = (property_name.casefold(), property_value.casefold())
                product = products[product_id]
                if key == ("horeca", "horeca"):
                    product["horeca"] = True
                for field, aliases in PROPERTY_ALIASES.items():
                    if product_id not in missing[field] or key[0] not in aliases:
                        continue
                    previous = best.get((product_id, field))
                    if previous is None or key < previous:
                        best[product_id, field] = key
                        product[field] = property_value
    finally:
        result.close()


def analytics_product_lookup(db: Session, items: list[AnalyticsLookupItemIn]) -> AnalyticsLookupResponse:
    started = time.perf_counter()
    metrics = dict(
        requested=len(items), matched=0, not_found=0, ambiguous=0,
        products_sql_ms=0.0, properties_sql_ms=0.0, properties_rows=0, status="error",
    )
    try:
        query = _matching_query(items)
        sql_started = time.perf_counter()
        matches = {(row.kind, row.key): row for row in db.execute(query)}
        metrics["products_sql_ms"] += (time.perf_counter() - sql_started) * 1000
        resolved = [_resolve(item, matches) for item in items]
        product_ids = {product_id for _, _, product_id in resolved if product_id is not None}
        products = {}
        if product_ids:
            query = select(
                Product.id, Product.code, Product.article, Product.manufacturer, Product.brand,
                Product.category_id, Product.category1, Product.section, Product.material, Product.updated_at,
            ).where(Product.id.in_(product_ids))
            sql_started = time.perf_counter()
            rows = db.execute(query).all()
            metrics["products_sql_ms"] += (time.perf_counter() - sql_started) * 1000
            for row in rows:
                products[row.id] = dict(
                    product_id=row.id, code=row.code, article=row.article,
                    manufacturer=_clean(row.manufacturer), brand=_clean(row.brand),
                    category_id=row.category_id, category=_clean(row.category1),
                    subcategory=_clean(row.section), legacy_category=_clean(row.section),
                    material=_clean(row.material), horeca=False, updated_at=row.updated_at,
                )
            if products:
                _load_properties(db, products, metrics)
        validated = {product_id: AnalyticsProductOut(**product) for product_id, product in products.items()}
        result = []
        for index, (status, matched_by, product_id) in enumerate(resolved):
            # A concurrent deletion between SELECTs is a missing row, never a partial product.
            if status == "matched" and product_id not in validated:
                status, matched_by = "not_found", None
            result.append(AnalyticsLookupItemOut(
                request_index=index, status=status, matched_by=matched_by,
                product=validated.get(product_id),
            ))
            metrics[status] += 1
        response = AnalyticsLookupResponse(items=result)
        metrics["status"] = "ok"
        return response
    finally:
        metrics["total_ms"] = (time.perf_counter() - started) * 1000
        logger.info(
            "analytics_lookup_perf requested=%(requested)d matched=%(matched)d "
            "not_found=%(not_found)d ambiguous=%(ambiguous)d total_ms=%(total_ms).3f "
            "products_sql_ms=%(products_sql_ms).3f properties_sql_ms=%(properties_sql_ms).3f "
            "properties_rows=%(properties_rows)d status=%(status)s",
            metrics,
        )
