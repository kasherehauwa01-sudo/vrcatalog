from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.catalog import ServiceLog

MAX_ERROR_LOGS = 100

def add_log(
    db: Session,
    event: str,
    message: str,
    level: str = "info",
    error_type: str | None = None,
    traceback_text: str | None = None,
) -> None:
    """Сохраняет служебное событие в БД без прерывания основной бизнес-операции."""
    db.add(
        ServiceLog(
            event=event,
            message=message,
            level=level,
            error_type=error_type,
            traceback=traceback_text,
        )
    )
