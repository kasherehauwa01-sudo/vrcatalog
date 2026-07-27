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
    """Сохраняет только ошибки и ограничивает журнал последними 100 записями."""
    if level != "error":
        return
    db.add(ServiceLog(
        event=event,
        message=message,
        level=level,
        error_type=error_type,
        traceback=traceback_text,
    ))
    db.flush()
    retained_ids = (
        select(ServiceLog.id)
        .where(ServiceLog.level == "error")
        .order_by(ServiceLog.created_at.desc(), ServiceLog.id.desc())
        .limit(MAX_ERROR_LOGS)
    )
    db.query(ServiceLog).filter(ServiceLog.id.notin_(retained_ids)).delete(
        synchronize_session=False,
    )
