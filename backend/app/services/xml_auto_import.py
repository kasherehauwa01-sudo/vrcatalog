from __future__ import annotations

import tempfile
import threading
import time
from datetime import datetime
from ftplib import FTP
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.importer.xml_importer import XMLCatalogImporter
from app.models.catalog import AutoImportState, XmlServerSetting
from app.services.logging import add_log
from app.services.notifications import add_notification

CHECK_INTERVAL_SECONDS = 600
_lock = threading.Lock()
_worker_started = False


def default_xml_server_setting() -> XmlServerSetting:
    return XmlServerSetting(
        protocol="FTP",
        host="176.53.160.144",
        port=21,
        username="uploader",
        password="9963396",
        xml_dir="/xml",
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


def connect(setting: XmlServerSetting) -> FTP:
    if setting.protocol.upper() != "FTP":
        raise ValueError(f"Протокол {setting.protocol} пока не поддерживается")
    ftp = FTP()
    ftp.connect(setting.host, setting.port, timeout=30)
    ftp.login(setting.username, setting.password)
    ftp.cwd(setting.xml_dir)
    return ftp


def test_connection(db: Session) -> tuple[bool, str]:
    setting = get_xml_server_setting(db)
    try:
        ftp = connect(setting)
        ftp.quit()
        return True, "Подключение успешно."
    except Exception as exc:  # noqa: BLE001 - пользователю нужен полный текст ошибки
        return False, f"Не удалось подключиться.\n\nПричина:\n{exc}"


def _format_dt(value: datetime) -> str:
    return value.strftime("%d.%m.%Y %H:%M")


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
    state.last_run_at = datetime.utcnow()
    db.commit()
    ftp: FTP | None = None
    try:
        add_log(db, "ftp_auto_import_check", "Автоматическая проверка FTP...")
        setting = get_xml_server_setting(db)
        ftp = connect(setting)
        add_log(db, "ftp_auto_import_connected", "Подключение выполнено.")
        files = sorted(name for name in ftp.nlst() if name.lower().endswith(".xml"))
        add_log(db, "ftp_auto_import_files", f"Найдено файлов: {len(files)}")
        for filename in files:
            processed += 1
            temp_path: Path | None = None
            current_name = filename
            try:
                add_log(db, "ftp_auto_import_start", f"Начат импорт:\n{filename}")
                with tempfile.NamedTemporaryFile(delete=False, suffix=".xml", dir=settings.upload_dir) as tmp:
                    temp_path = Path(tmp.name)
                    ftp.retrbinary(f"RETR {filename}", tmp.write)
                run = XMLCatalogImporter().import_file(db, temp_path, filename)
                ftp.delete(filename)
                successful += 1
                now = datetime.utcnow()
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
                now = datetime.utcnow()
                add_notification(
                    db,
                    "ftp_import_error",
                    "Ошибка импорта XML.",
                    f"Файл:\n{current_name}\n\nПричина:\n{last_error}\n\nДата:\n{_format_dt(now)}",
                )
                add_log(db, "ftp_auto_import_error", f"Ошибка импорта:\n{last_error}", "error")
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
        state.last_run_at = datetime.utcnow()
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
        state.last_run_at = datetime.utcnow()
        add_log(db, "ftp_auto_import_error", f"Ошибка импорта:\n{exc}", "error")
        db.commit()
    finally:
        if ftp is not None:
            try:
                ftp.quit()
            except Exception:  # noqa: BLE001
                pass
        db.close()
        _lock.release()


def start_worker() -> None:
    global _worker_started
    if _worker_started:
        return
    _worker_started = True

    def loop() -> None:
        while True:
            run_once()
            time.sleep(CHECK_INTERVAL_SECONDS)

    threading.Thread(target=loop, daemon=True, name="xml-ftp-auto-import").start()
