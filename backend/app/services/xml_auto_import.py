from __future__ import annotations

import logging
import errno
import re
import socket
import tempfile
import traceback
import threading
import time
from datetime import datetime, timedelta, timezone
from ftplib import FTP, error_perm, error_temp
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.importer.xml_importer import XMLCatalogImporter, xml_product_count
from app.models.catalog import AutoImportState, FtpConnectionLog, XmlServerSetting
from app.services.logging import add_log
from app.services.notifications import add_notification

CHECK_INTERVAL_SECONDS = 600
MOSCOW_TZ = timezone(timedelta(hours=3))
_lock = threading.Lock()
_worker_started = False
logger = logging.getLogger(__name__)


def _product_code_from_error(exc: Exception) -> str | None:
    match = re.search(r"кодом ([^:]+):", str(exc))
    return match.group(1) if match else None


def _exception_details(stage: str, exc: Exception, **context: object) -> tuple[str, str]:
    lines = [f"Этап:\n{stage}"]
    for key, value in context.items():
        if value is not None:
            lines.append(f"{key}:\n{value}")
    lines.extend([
        f"Ошибка:\n{exc}",
        f"Exception:\n{type(exc).__name__}",
    ])
    if getattr(exc, "errno", None) is not None:
        lines.append(f"Errno:\n{exc.errno}")
    trace = traceback.format_exc()
    lines.append(f"Traceback:\n{trace}")
    return "\n\n".join(lines), trace


def _ftp_size(ftp: FTP | None, filename: str) -> int | None:
    if ftp is None:
        return None
    try:
        return ftp.size(filename)
    except Exception:
        return None


def default_xml_server_setting() -> XmlServerSetting:
    return XmlServerSetting(
        protocol="FTP",
        host="",
        port=21,
        username="",
        password="",
        xml_dir="/xml",
        connection_attempts=5,
        retry_delay_seconds=3,
    )


def get_xml_server_setting(db: Session) -> XmlServerSetting:
    setting = db.query(XmlServerSetting).order_by(XmlServerSetting.id).first()
    if setting:
        return setting
    setting = default_xml_server_setting()
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting


def get_auto_import_state(db: Session) -> AutoImportState:
    state = db.query(AutoImportState).order_by(AutoImportState.id).first()
    if state:
        return state
    state = AutoImportState(status="stopped", processed_files=0, successful_files=0, failed_files=0, is_running=False)
    db.add(state)
    db.commit()
    db.refresh(state)
    return state


NETWORK_ERRNOS = {
    errno.ECONNREFUSED, errno.ETIMEDOUT, errno.EHOSTUNREACH, errno.ENETUNREACH,
    errno.ECONNRESET, errno.ENETDOWN, errno.EHOSTDOWN, errno.EPIPE,
}


def _temporary_connection_error(exc: Exception) -> bool:
    if isinstance(exc, error_perm):
        return False
    if isinstance(exc, (ConnectionRefusedError, TimeoutError, error_temp)):
        return True
    if isinstance(exc, socket.gaierror):
        return exc.errno == socket.EAI_AGAIN
    return isinstance(exc, OSError) and exc.errno in NETWORK_ERRNOS


def _connection_log(db: Session | None, setting: XmlServerSetting, attempt: int, started: float, exc: Exception | None = None) -> None:
    if db is None:
        return
    duration_ms = round((time.perf_counter() - started) * 1000, 3)
    db.add(FtpConnectionLog(
        host=setting.host, port=setting.port, duration_ms=duration_ms,
        attempt_number=attempt, success=exc is None,
        error_type=type(exc).__name__ if exc else None,
        error_message=str(exc) if exc else None,
    ))
    if exc:
        message = f"Попытка {attempt} завершилась ошибкой:\n{type(exc).__name__}: {exc}\nHost: {setting.host}\nPort: {setting.port}"
        add_log(db, "ftp_connection_attempt_error", message, "error", type(exc).__name__)
    else:
        add_log(db, "ftp_connection_attempt_success", f"Подключение выполнено успешно с попытки {attempt}.\nHost: {setting.host}\nPort: {setting.port}\nВремя подключения: {duration_ms} мс")
    db.commit()


def connect(setting: XmlServerSetting, db: Session | None = None) -> FTP:
    if setting.protocol.upper() != "FTP":
        raise ValueError(f"Протокол {setting.protocol} пока не поддерживается")
    if not setting.host.strip() or not setting.username.strip():
        raise ValueError("Не заполнены host или пользователь FTP")
    attempts = max(1, min(int(setting.connection_attempts or 5), 10))
    delay = max(0, min(int(setting.retry_delay_seconds or 3), 60))
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        started = time.perf_counter()
        if db:
            add_log(db, "ftp_connection_attempt", f"Попытка подключения {attempt} из {attempts}\nHost: {setting.host}\nPort: {setting.port}")
            db.commit()
        ftp = FTP()
        try:
            ftp.connect(setting.host, setting.port, timeout=30)
            ftp.login(setting.username, setting.password)
            ftp.cwd(setting.xml_dir)
            setattr(ftp, "_vrcatalog_attempt", attempt)
            setattr(ftp, "_vrcatalog_duration_ms", round((time.perf_counter() - started) * 1000, 3))
            _connection_log(db, setting, attempt, started)
            return ftp
        except Exception as exc:
            last_error = exc
            try:
                ftp.close()
            except Exception:  # noqa: BLE001
                pass
            _connection_log(db, setting, attempt, started, exc)
            if not _temporary_connection_error(exc) or attempt == attempts:
                if db and attempt == attempts and _temporary_connection_error(exc):
                    add_log(db, "ftp_connection_exhausted", f"Не удалось подключиться после {attempts} попыток.\n{type(exc).__name__}: {exc}", "error", type(exc).__name__)
                    db.commit()
                setattr(exc, "vrcatalog_attempts", attempt)
                raise
            time.sleep(delay)
    raise last_error or RuntimeError("Не удалось подключиться к FTP")


def test_connection(db: Session) -> tuple[bool, str]:
    setting = get_xml_server_setting(db)
    started = time.perf_counter()
    try:
        ftp = connect(setting, db)
        attempt = getattr(ftp, "_vrcatalog_attempt", 1)
        ftp.quit()
        return True, (
            f"Host: {setting.host}\nPort: {setting.port}\nПротокол: {setting.protocol}\n"
            f"Время подключения: {round((time.perf_counter() - started) * 1000, 3)} мс\n"
            f"Количество попыток: {attempt}\nРезультат: Подключено"
        )
    except Exception as exc:  # noqa: BLE001 - пользователю нужен полный текст ошибки
        return False, (
            f"Host: {setting.host}\nPort: {setting.port}\nПротокол: {setting.protocol}\n"
            f"Время подключения: {round((time.perf_counter() - started) * 1000, 3)} мс\n"
            f"Количество попыток: {getattr(exc, 'vrcatalog_attempts', 1)}\n"
            f"Результат: Ошибка\nПричина: {type(exc).__name__}: {exc}"
        )


def moscow_now() -> datetime:
    return datetime.now(MOSCOW_TZ).replace(tzinfo=None)


def _format_dt(value: datetime) -> str:
    if value.tzinfo is None:
        return value.strftime("%d.%m.%Y %H:%M")
    return value.astimezone(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M")


def _rename_error_file(ftp: FTP, filename: str) -> str:
    if filename.startswith("ERROR_"):
        return filename
    error_name = f"ERROR_{filename}"
    ftp.rename(filename, error_name)
    return error_name


def run_once() -> None:
    if not _lock.acquire(blocking=False):
        return
    db = SessionLocal()
    processed = successful = failed = 0
    last_error: str | None = None
    state = get_auto_import_state(db)
    state.is_running = True
    state.status = "running"
    state.last_run_at = moscow_now()
    db.commit()
    ftp: FTP | None = None
    setting: XmlServerSetting | None = None
    try:
        add_log(db, "ftp_auto_import_check", "Автоматическая проверка FTP...")
        setting = get_xml_server_setting(db)
        try:
            ftp = connect(setting, db)
        except Exception as exc:
            logger.exception("Ошибка подключения к FTP")
            message, trace = _exception_details(
                "Подключение к FTP",
                exc,
                Host=setting.host,
                Port=setting.port,
                Login=setting.username,
            )
            add_log(db, "ftp_connect_error", message, "error", type(exc).__name__, trace)
            raise
        add_log(db, "ftp_auto_import_connected", "Подключение выполнено.")
        files = sorted(name for name in ftp.nlst() if name.lower().endswith(".xml"))
        add_log(db, "ftp_auto_import_files", f"Найдено файлов: {len(files)}")
        for filename in files:
            processed += 1
            temp_path: Path | None = None
            current_name = filename
            error_message: str | None = None
            error_trace: str | None = None
            error_type: str | None = None
            try:
                add_log(db, "ftp_auto_import_start", f"Начат импорт:\n{filename}")
                with tempfile.NamedTemporaryFile(delete=False, suffix=".xml", dir=settings.upload_dir) as tmp:
                    temp_path = Path(tmp.name)
                    try:
                        ftp.retrbinary(f"RETR {filename}", tmp.write)
                    except Exception as exc:
                        logger.exception("Ошибка скачивания XML с FTP")
                        message, trace = _exception_details(
                            "Скачивание файла",
                            exc,
                            File=filename,
                            FtpPath=getattr(setting, "xml_dir", None),
                            Size=_ftp_size(ftp, filename),
                        )
                        error_message = message
                        error_trace = trace
                        error_type = type(exc).__name__
                        raise
                try:
                    product_count = xml_product_count(temp_path)
                except Exception as exc:
                    logger.exception("Ошибка чтения XML")
                    position = getattr(exc, "position", None)
                    message, trace = _exception_details(
                        "Чтение XML",
                        exc,
                        File=filename,
                        Line=position[0] if position else None,
                        Column=position[1] if position else None,
                    )
                    error_message = message
                    error_trace = trace
                    error_type = type(exc).__name__
                    raise
                if product_count == 0:
                    ftp.delete(filename)
                    add_log(
                        db,
                        "ftp_auto_import_empty_file",
                        f"Файл {filename} не содержит товаров.\nФайл удален с FTP.",
                    )
                    db.commit()
                    continue
                try:
                    run = XMLCatalogImporter().import_file(db, temp_path, filename)
                except Exception as exc:
                    logger.exception("Ошибка импорта XML в базу")
                    message, trace = _exception_details(
                        "Импорт XML в базу",
                        exc,
                        File=filename,
                        ProductCode=_product_code_from_error(exc),
                    )
                    error_message = message
                    error_trace = trace
                    error_type = type(exc).__name__
                    raise
                ftp.delete(filename)
                successful += 1
                now = moscow_now()
                add_notification(
                    db,
                    "ftp_import_success",
                    "Импорт XML выполнен успешно.",
                    f"Файл:\n{filename}\n\nДобавлено товаров: {getattr(run, 'created_count', 0)}\n\nОбновлено товаров: {getattr(run, 'updated_count', 0)}\n\nДата:\n{_format_dt(now)}",
                )
                add_log(db, "ftp_auto_import_success", "Импорт завершен успешно.")
                db.commit()
            except Exception as exc:  # noqa: BLE001 - продолжаем остальные файлы
                db.rollback()
                failed += 1
                last_error = str(exc)
                try:
                    if ftp is not None:
                        current_name = _rename_error_file(ftp, filename)
                except Exception as rename_exc:  # noqa: BLE001
                    last_error = f"{exc}\nОшибка переименования FTP-файла: {rename_exc}"
                now = moscow_now()
                add_notification(
                    db,
                    "ftp_import_error",
                    "Ошибка импорта XML.",
                    f"Файл:\n{current_name}\n\nПричина:\n{last_error}\n\nДата:\n{_format_dt(now)}",
                )
                if error_message is None:
                    error_message, error_trace = _exception_details(
                        "Обработка файла", exc, File=current_name
                    )
                    error_type = type(exc).__name__
                add_log(db, "ftp_auto_import_error", error_message, "error", error_type, error_trace)
                db.commit()
            finally:
                if temp_path:
                    temp_path.unlink(missing_ok=True)
        state = get_auto_import_state(db)
        state.status = "error" if failed else "success"
        state.processed_files = processed
        state.successful_files = successful
        state.failed_files = failed
        state.last_error = last_error
        state.is_running = False
        state.last_run_at = moscow_now()
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        state = get_auto_import_state(db)
        state.status = "error"
        state.processed_files = processed
        state.successful_files = successful
        state.failed_files = failed
        state.last_error = str(exc)
        state.is_running = False
        state.last_run_at = moscow_now()
        logger.exception("Ошибка автоматического импорта XML")
        context = {}
        if setting is not None:
            context = {"Host": setting.host, "Port": setting.port, "Login": setting.username}
        stage = (
            "Подключение к FTP"
            if ftp is None and setting is not None
            else "Автоматическая проверка FTP"
        )
        message, trace = _exception_details(stage, exc, **context)
        add_log(db, "ftp_auto_import_error", message, "error", type(exc).__name__, trace)
        db.commit()
    finally:
        if ftp is not None:
            try:
                ftp.quit()
            except Exception:  # noqa: BLE001
                pass
        db.close()
        _lock.release()


def start_manual_import() -> bool:
    if _lock.locked():
        return False
    threading.Thread(target=run_once, daemon=True, name="xml-ftp-manual-import").start()
    return True


def start_worker() -> None:
    global _worker_started
    if _worker_started:
        return
    _worker_started = True

    def loop() -> None:
        while True:
            run_once()
            from app.services.monthly_promotion import run_scheduled_if_due
            run_scheduled_if_due()
            time.sleep(CHECK_INTERVAL_SECONDS)

    threading.Thread(target=loop, daemon=True, name="xml-ftp-auto-import").start()
