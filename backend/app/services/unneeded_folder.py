"""Daily, read-only catalog scan and durable email digest baseline."""
import json
import logging
import threading
from datetime import datetime
from html import escape
from io import BytesIO
from time import perf_counter
from zoneinfo import ZoneInfo

import xlwt
from sqlalchemy import delete, func, select, text

from app.db.session import SessionLocal
from app.models.catalog import NotificationEmailHistory, NotificationScenarioSetting, Product, ProductProperty, Stock, UnneededFolderSnapshot, WarehouseSetting
from app.services.catalog_folders import FOLDER_PATH_PROPERTIES, folder_path
from app.services.monthly_promotion import get_mail_setting, recipients, send_email

CODE = "unneeded_folder"
NAME = "Добавление товара в папку НЕНУЖНОЕ"
WAREHOUSE_NAME = "Авиаторов Зал+Склад"
logger = logging.getLogger(__name__)
_lock = threading.Lock()


def get_setting(db):
    setting = db.query(NotificationScenarioSetting).filter_by(code=CODE).with_for_update().populate_existing().first()
    if setting is None:
        setting = NotificationScenarioSetting(code=CODE, enabled=False, send_time="22:30", recipients_json="[]")
        db.add(setting)
        db.flush()
    return setting


def current_products(db):
    # Stream narrow rows, not Product entities or all property collections.
    rows = db.execute(select(Product.code, Product.name, Product.manager, ProductProperty.value)
                      .join(ProductProperty, ProductProperty.product_id == Product.id)
                      .where(ProductProperty.name.in_(FOLDER_PATH_PROPERTIES))
                      .execution_options(yield_per=1000))
    products = {}
    for code, name, manager, value in rows:
        path = folder_path(value, name)
        if path and any(part.strip().casefold() == "ненужное" for part in path.split("|")):
            products[code] = (code, name, manager)
    return products


def replace_snapshot(db, codes):
    existing = set(db.scalars(select(UnneededFolderSnapshot.product_code)))
    removed = list(existing - set(codes))
    for start in range(0, len(removed), 500):
        db.execute(delete(UnneededFolderSnapshot).where(UnneededFolderSnapshot.product_code.in_(removed[start:start + 500])))
    db.add_all(UnneededFolderSnapshot(product_code=code) for code in set(codes) - existing)


def set_enabled(db, setting, enabled):
    if enabled and not setting.enabled:
        replace_snapshot(db, zero_stock_by_code(db, current_products(db)))
        setting.last_run_date = None
    setting.enabled = enabled


def warehouse_stock_by_code(db, codes):
    quantities = {}
    for start in range(0, len(codes), 500):
        rows = db.execute(
            select(Product.code, func.sum(Stock.quantity))
            .join(Stock, Stock.product_id == Product.id)
            .outerjoin(WarehouseSetting, WarehouseSetting.code == Stock.warehouse)
            .where(
                Product.code.in_(codes[start:start + 500]),
                func.coalesce(WarehouseSetting.name, Stock.warehouse) == WAREHOUSE_NAME,
            )
            .group_by(Product.code)
        )
        quantities.update((code, quantity) for code, quantity in rows)
    return quantities


def zero_stock_by_code(db, products):
    quantities = warehouse_stock_by_code(db, list(products))
    # Missing stock is unknown, not a recorded zero.
    return {code: quantity for code, quantity in quantities.items() if quantity == 0}


def build_preview(products, quantities):
    rows = "".join(
        f"<tr><td>{escape(code)}</td><td>{escape(name)}</td><td>{escape(manager or '')}</td>"
        f"<td>{format(quantities.get(code, 0), '.15g').replace('.', ',')}</td></tr>"
        for code, name, manager in products
    )
    return ("<h2>Товары с нулевым остатком в папке НЕНУЖНОЕ</h2><table border='1' cellpadding='6'>"
            f"<tr><th>Код</th><th>Наименование</th><th>Менеджер</th>"
            f"<th>Остаток: {WAREHOUSE_NAME}</th></tr>" + rows + "</table>")


def build_attachment(products):
    workbook = xlwt.Workbook()
    # XLS supports 65536 rows per sheet. Keep A1 empty on every sheet.
    for start in range(0, max(1, len(products)), 65535):
        sheet = workbook.add_sheet(f"Коды {start // 65535 + 1}")
        for index, (code, _, _) in enumerate(products[start:start + 65535], start=1):
            sheet.write(index, 0, code)  # strings preserve leading zeros
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def run_due(db, now=None):
    started = perf_counter()
    local = (now or datetime.now(ZoneInfo("Europe/Moscow"))).astimezone(ZoneInfo("Europe/Moscow"))
    today = local.strftime("%Y-%m-%d")
    # Serialize workers and settings changes until the send/baseline commit.
    setting = db.query(NotificationScenarioSetting).filter_by(code=CODE).with_for_update().populate_existing().first()
    if setting is None or not setting.enabled or local.strftime("%H:%M") < setting.send_time or setting.last_run_date == today:
        return "skipped"
    targets = recipients(setting)
    if not targets:
        return "no_recipients"
    products = current_products(db)
    known = set(db.scalars(select(UnneededFolderSnapshot.product_code)))
    quantities = zero_stock_by_code(db, products)
    added = [products[code] for code in sorted(quantities.keys() - known)]
    if not added:
        replace_snapshot(db, quantities)
        setting.last_run_date = today
        db.commit()
        return "empty"
    html = build_preview(added, quantities)
    status = "sent"
    try:
        send_email(db, targets, NAME, html, extra_attachments=[
            (build_attachment(added), "НЕНУЖНОЕ.xls", "vnd.ms-excel"),
        ])
    except Exception:
        status = "error"
        logger.warning("unneeded_folder_digest status=error count=%d", len(added))
    # On failure keep previously reported zeros and drop products that are no
    # longer eligible. Unsent products still qualify on the next check.
    replace_snapshot(db, quantities if status == "sent" else known & quantities.keys())
    setting.last_run_date = today
    db.add(NotificationEmailHistory(
        scenario_code=CODE, recipients_json=json.dumps(targets), subject=NAME,
        body_html=html, status=status,
        error_message="Не удалось отправить уведомление" if status == "error" else None,
        duration_ms=(perf_counter() - started) * 1000,
    ))
    db.commit()
    return status


def run_scheduled_if_due():
    if not _lock.acquire(blocking=False):
        return
    try:
        with SessionLocal() as db:
            # Create mail settings before acquiring the scenario row lock: the
            # existing SMTP helper commits only when creating missing settings.
            setting = db.query(NotificationScenarioSetting).filter_by(code=CODE, enabled=True).first()
            if setting is None:
                return
            get_mail_setting(db)
            if db.bind.dialect.name == "postgresql" and not db.scalar(text("SELECT pg_try_advisory_xact_lock(7242027)")):
                return
            run_due(db)
    except Exception:
        logger.warning("unneeded_folder_digest status=failed")
    finally:
        _lock.release()
