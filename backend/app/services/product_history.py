from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import or_, text
from sqlalchemy.orm import Session, selectinload

from app.db.session import SessionLocal
from app.models.catalog import HistorySetting, HistorySnapshot, HistorySnapshotItem, HistorySnapshotItemPrice, Product, ProductTypeSetting
from app.services.catalog import product_type_name
from app.services.logging import add_log


SNAPSHOT_TYPE = "monthly_promotion"
PROMOTION_NAME = "Акция месяца"
SOURCE_PROPERTY = "Вид товара"
# Импортер хранит исходные имена 1С; короткие варианты поддерживают ранее
# сохранённые/вручную созданные записи той же цены.
BASE_PRICE_TYPES = ("ЦенаПредыдущаяРозничная", "Предыдущая розничная")
PROMO_PRICE_TYPES = ("ЦенаРозничная", "Розничная")
MOSCOW_OFFSET_HOURS = 3
logger = logging.getLogger(__name__)
_history_lock = threading.Lock()


def first_day(value: date) -> date:
    return value.replace(day=1)


def add_month(value: date, offset: int) -> date:
    month_index = value.year * 12 + value.month - 1 + offset
    return date(month_index // 12, month_index % 12 + 1, 1)


def get_history_setting(db: Session) -> HistorySetting:
    setting = db.query(HistorySetting).filter_by(snapshot_type=SNAPSHOT_TYPE).first()
    if setting is None:
        setting = HistorySetting(snapshot_type=SNAPSHOT_TYPE, save_for_next_month=True)
        db.add(setting)
        db.flush()
    return setting


def scheduled_period(today: date, save_for_next_month: bool) -> date:
    """Возвращает период последнего уже наступившего запуска 28 числа."""
    due_month = first_day(today) if today.day >= 28 else add_month(first_day(today), -1)
    return add_month(due_month, 1 if save_for_next_month else 0)


def manual_period(today: date, save_for_next_month: bool) -> date:
    return add_month(first_day(today), 1 if save_for_next_month else 0)


def promotion_type_codes(db: Session) -> tuple[list[str], dict[str, str]]:
    configured = dict(db.query(ProductTypeSetting.code, ProductTypeSetting.name).all())
    values = [code for code, in db.query(Product.product_type).filter(Product.product_type.isnot(None)).distinct()]
    codes = [
        code for code in values
        if (product_type_name(code, configured) or "").strip().casefold() == PROMOTION_NAME.casefold()
    ]
    return codes, configured


def promotion_products(db: Session) -> list[Product]:
    codes, _ = promotion_type_codes(db)
    if not codes:
        return []
    return (
        db.query(Product)
        .options(selectinload(Product.prices))
        .filter(Product.product_type.in_(codes))
        .order_by(Product.id)
        .all()
    )


def _price(product: Product, accepted_types: tuple[str, ...]) -> Decimal | None:
    price = next((item for item in product.prices if item.price_type in accepted_types), None)
    return Decimal(str(price.price_value)).quantize(Decimal("0.01")) if price else None


def _decimal_price(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def snapshot_preview(db: Session, period: date) -> dict:
    products = promotion_products(db)
    existing = db.query(HistorySnapshot.id).filter_by(snapshot_type=SNAPSHOT_TYPE, period=period).first()
    return {
        "period": period,
        "snapshot_type": SNAPSHOT_TYPE,
        "snapshot_name": PROMOTION_NAME,
        "item_count": len(products),
        "exists": existing is not None,
    }


def create_snapshot(
    db: Session,
    period: date,
    creation_source: str,
    *,
    replace_existing: bool = False,
) -> tuple[HistorySnapshot, bool]:
    """Создаёт снимок; явное ручное сохранение может атомарно обновить период."""
    if db.bind and db.bind.dialect.name == "postgresql":
        # Межпроцессная блокировка дополняет UNIQUE constraint при нескольких контейнерах.
        db.execute(text("SELECT pg_advisory_xact_lock(9282026)"))
    existing = db.query(HistorySnapshot).filter_by(snapshot_type=SNAPSHOT_TYPE, period=period).first()
    if existing and not replace_existing:
        add_log(db, "history_snapshot_skipped", f"Снимок {PROMOTION_NAME} за {period:%Y-%m} уже существует. Создание пропущено.")
        return existing, False

    products = promotion_products(db)
    if existing:
        snapshot = existing
        # ORM-cascade удаляет прежние строки и все связанные исторические цены.
        # Новые строки создаются в той же транзакции, поэтому частичного обновления нет.
        snapshot.items.clear()
        snapshot.creation_source = creation_source
        snapshot.item_count = len(products)
        snapshot.status = "success"
        snapshot.created_at = datetime.utcnow()
    else:
        snapshot = HistorySnapshot(
            snapshot_type=SNAPSHOT_TYPE,
            period=period,
            source_property=SOURCE_PROPERTY,
            source_value=PROMOTION_NAME,
            creation_source=creation_source,
            item_count=len(products),
            status="success",
        )
        db.add(snapshot)
    db.flush()
    missing_base = 0
    missing_promo = 0
    for product in products:
        base_price = _price(product, BASE_PRICE_TYPES)
        promo_price = _price(product, PROMO_PRICE_TYPES)
        missing_base += int(base_price is None)
        missing_promo += int(promo_price is None)
        item = HistorySnapshotItem(
            snapshot_id=snapshot.id,
            product_id=product.id,
            code=product.code,
            article=product.article,
            name=product.name,
            base_price=base_price,
            promo_price=promo_price,
            product_type_code=product.product_type,
            product_type_name=PROMOTION_NAME,
        )
        db.add(item)
        db.flush()
        db.add_all([
            HistorySnapshotItemPrice(
                snapshot_item_id=item.id,
                price_type=price.price_type,
                price_value=_decimal_price(price.price_value),
            )
            for price in product.prices
        ])
    db.flush()
    action = "обновление" if existing else "создание"
    message = (
        f"Формирование истории «{PROMOTION_NAME}»; действие={action}; период={period:%Y-%m}; "
        f"найдено={len(products)}; сохранено={len(products)}; "
        f"без базовой цены={missing_base}; без акционной цены={missing_promo}; "
        f"snapshot_id={snapshot.id}; статус=успешно"
    )
    add_log(db, "history_snapshot_created", message)
    logger.info(message)
    return snapshot, existing is None


def run_history_snapshot_if_due(now: datetime | None = None) -> None:
    """Ежедневная catch-up проверка в существующем фоновом worker."""
    if not _history_lock.acquire(blocking=False):
        return
    db = SessionLocal()
    try:
        moscow_now = now or datetime.utcnow() + timedelta(hours=MOSCOW_OFFSET_HOURS)
        setting = get_history_setting(db)
        period = scheduled_period(moscow_now.date(), setting.save_for_next_month)
        create_snapshot(db, period, "automatic")
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Не удалось сформировать историю «%s»", PROMOTION_NAME)
    finally:
        db.close()
        _history_lock.release()


def list_snapshots(db: Session) -> list[HistorySnapshot]:
    return db.query(HistorySnapshot).filter_by(snapshot_type=SNAPSHOT_TYPE).order_by(HistorySnapshot.period.desc()).all()


def snapshot_by_period(db: Session, period: date, search: str = "") -> tuple[HistorySnapshot | None, list[HistorySnapshotItem]]:
    snapshot = db.query(HistorySnapshot).filter_by(snapshot_type=SNAPSHOT_TYPE, period=period).first()
    if snapshot is None:
        return None, []
    query = db.query(HistorySnapshotItem).options(selectinload(HistorySnapshotItem.prices)).filter_by(snapshot_id=snapshot.id)
    normalized_search = search.strip()
    if normalized_search:
        pattern = f"%{normalized_search}%"
        query = query.filter(or_(
            HistorySnapshotItem.code.ilike(pattern),
            HistorySnapshotItem.article.ilike(pattern),
            HistorySnapshotItem.name.ilike(pattern),
        ))
    return snapshot, query.order_by(HistorySnapshotItem.code, HistorySnapshotItem.id).all()
