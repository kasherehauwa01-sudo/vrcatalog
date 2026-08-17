from __future__ import annotations

import json
import logging
import smtplib
import ssl
import threading
from datetime import datetime, timedelta
from email.message import EmailMessage
from html import escape
from time import perf_counter

from cryptography.fernet import Fernet
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.catalog import MailSetting, NotificationEmailHistory, NotificationScenarioSetting, Product, ProductTypeChange, ProductTypeSetting
from app.services.logging import add_log

PROMOTION_VALUE = "Акция месяца"
SCENARIO_CODE = "monthly_promotion"
MOSCOW_OFFSET_HOURS = 3
logger = logging.getLogger(__name__)
_run_lock = threading.Lock()


def _fernet() -> Fernet:
    import base64
    import hashlib

    key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())
    return Fernet(key)


def encrypt_password(password: str) -> str:
    return _fernet().encrypt(password.encode()).decode() if password else ""


def decrypt_password(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode() if value else ""


def get_mail_setting(db: Session) -> MailSetting:
    value = db.query(MailSetting).order_by(MailSetting.id).first()
    if value:
        return value
    value = MailSetting(updated_at=datetime.utcnow())
    db.add(value)
    db.commit()
    db.refresh(value)
    return value


def get_scenario_setting(db: Session) -> NotificationScenarioSetting:
    value = db.query(NotificationScenarioSetting).filter_by(code=SCENARIO_CODE).first()
    if value:
        return value
    value = NotificationScenarioSetting(code=SCENARIO_CODE, updated_at=datetime.utcnow())
    db.add(value)
    db.commit()
    db.refresh(value)
    return value


def recipients(setting: NotificationScenarioSetting) -> list[str]:
    try:
        return [str(item).strip() for item in json.loads(setting.recipients_json) if str(item).strip()]
    except (TypeError, ValueError):
        return []


def _smtp(mail: MailSetting):
    context = ssl.create_default_context()
    if mail.encryption == "ssl":
        client = smtplib.SMTP_SSL(mail.smtp_host, mail.smtp_port, timeout=15, context=context)
    else:
        client = smtplib.SMTP(mail.smtp_host, mail.smtp_port, timeout=15)
        if mail.encryption == "starttls":
            client.starttls(context=context)
    if mail.username:
        client.login(mail.username, decrypt_password(mail.encrypted_password))
    return client


def check_connection(db: Session, mail: MailSetting | None = None) -> tuple[bool, str]:
    mail = mail or get_mail_setting(db)
    try:
        with _smtp(mail) as client:
            client.noop()
        mail.connection_status = "connected"
        mail.last_success_at = datetime.utcnow()
        mail.last_error = None
        result = (True, "Подключено")
    except Exception as exc:  # noqa: BLE001
        mail.connection_status = "error"
        mail.last_error = str(exc)
        result = (False, f"Ошибка подключения: {exc}")
    db.commit()
    return result


def send_email(db: Session, to: list[str], subject: str, html: str) -> None:
    mail = get_mail_setting(db)
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{mail.sender_name} <{mail.sender_email}>" if mail.sender_name else mail.sender_email
    message["To"] = ", ".join(to)
    message.set_content("Для просмотра письма требуется HTML-клиент.")
    message.add_alternative(html, subtype="html")
    with _smtp(mail) as client:
        client.send_message(message)
    mail.connection_status = "connected"
    mail.last_success_at = datetime.utcnow()
    mail.last_sent_at = datetime.utcnow()
    mail.last_error = None
    db.flush()


def build_preview(changes: list[ProductTypeChange]) -> str:
    sections = []
    for title, selected in (
        ("Добавлены в Акцию месяца", [item for item in changes if item.new_value == PROMOTION_VALUE]),
        ("Исключены из Акции месяца", [item for item in changes if item.old_value == PROMOTION_VALUE]),
    ):
        if not selected:
            continue
        rows = "".join(
            f"<tr><td>{escape(item.article or '')}</td><td>{escape(item.product_name)}</td>"
            f"<td>{escape(item.old_value or '')}</td><td>{escape(item.new_value or '')}</td>"
            f"<td>{item.changed_at:%d.%m.%Y %H:%M}</td></tr>"
            for item in selected
        )
        sections.append(
            f"<h2>{title}</h2><table border='1' cellpadding='6' cellspacing='0'>"
            "<tr><th>Артикул</th><th>Наименование</th><th>Было</th><th>Стало</th><th>Время изменения</th></tr>"
            f"{rows}</table>"
        )
    return "".join(sections)


def log_scenario_run(db: Session, result: dict, started: float) -> None:
    add_log(db, "monthly_promotion_scenario", json.dumps({
        **{key: value for key, value in result.items() if key != "html"},
        "duration_ms": round((perf_counter() - started) * 1000, 3),
    }, ensure_ascii=False), "error" if result.get("status") == "error" else "info")
    db.commit()


def run_scenario(db: Session, *, force: bool = False) -> dict:
    started = perf_counter()
    scenario = get_scenario_setting(db)
    targets = recipients(scenario)
    changes = db.query(ProductTypeChange).filter(ProductTypeChange.processed.is_(False)).order_by(ProductTypeChange.changed_at).all()
    result = {"changes": len(changes), "sent": 0, "recipients": targets, "html": build_preview(changes)}
    if not force and not scenario.enabled:
        result["status"] = "disabled"
        log_scenario_run(db, result, started)
        return result
    if not changes:
        result["status"] = "empty"
        log_scenario_run(db, result, started)
        return result
    if not targets:
        result["status"] = "no_recipients"
        log_scenario_run(db, result, started)
        return result
    subject = 'Изменения товаров "Акция месяца"'
    try:
        send_email(db, targets, subject, result["html"])
        now = datetime.utcnow()
        for item in changes:
            item.processed = True
            item.processed_at = now
        result.update(status="sent", sent=1)
        db.add(NotificationEmailHistory(
            scenario_code=SCENARIO_CODE, sent_at=now, recipients_json=json.dumps(targets, ensure_ascii=False),
            subject=subject, body_html=result["html"], status="sent",
            duration_ms=round((perf_counter() - started) * 1000, 3),
        ))
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        mail = get_mail_setting(db)
        mail.connection_status = "error"
        mail.last_error = str(exc)
        result.update(status="error", error=str(exc))
        db.add(NotificationEmailHistory(
            scenario_code=SCENARIO_CODE, sent_at=datetime.utcnow(), recipients_json=json.dumps(targets, ensure_ascii=False),
            subject=subject, body_html=result["html"], status="error", error_message=str(exc),
            duration_ms=round((perf_counter() - started) * 1000, 3),
        ))
    finally:
        log_scenario_run(db, result, started)
    return result


def run_scheduled_if_due() -> None:
    if not _run_lock.acquire(blocking=False):
        return
    db = SessionLocal()
    try:
        scenario = get_scenario_setting(db)
        now = datetime.utcnow() + timedelta(hours=MOSCOW_OFFSET_HOURS)
        current = now.strftime("%H:%M")
        today = now.strftime("%Y-%m-%d")
        if scenario.enabled and current >= scenario.send_time and scenario.last_run_date != today:
            run_scenario(db)
            scenario = get_scenario_setting(db)
            scenario.last_run_date = today
            db.commit()
    finally:
        db.close()
        _run_lock.release()


@event.listens_for(Session, "before_flush")
def track_product_type_changes(session: Session, _flush_context, _instances) -> None:
    source = str(session.info.get("change_source", "api"))
    dirty_products = [item for item in session.dirty if isinstance(item, Product)]
    if not dirty_products:
        return
    type_names = dict(session.query(ProductTypeSetting.code, ProductTypeSetting.name).all())
    for product in dirty_products:
        history = inspect(product).attrs.product_type.history
        old = history.deleted[0] if history.deleted else None
        new = history.added[0] if history.added else product.product_type
        old_display = type_names.get(old, old)
        new_display = type_names.get(new, new)
        if old == new or PROMOTION_VALUE not in {old_display, new_display}:
            continue
        session.add(ProductTypeChange(
            product_id=product.id,
            article=product.article,
            product_name=product.name,
            old_value=old_display,
            new_value=new_display,
            source=source,
            changed_at=datetime.utcnow(),
        ))
