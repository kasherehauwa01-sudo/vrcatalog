from sqlalchemy import select, text
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
    if level == "error" and db.get_bind().dialect.name == "postgresql":
        # Serialize error retention across writers until the caller commits/rolls back.
        with db.no_autoflush:
            db.execute(text("SELECT pg_advisory_xact_lock(82461932)"))
    db.add(
        ServiceLog(
            event=event,
            message=message,
            level=level,
            error_type=error_type,
            traceback=traceback_text,
        )
    )
    if level == "error":
        db.flush()
        retained_ids = (select(ServiceLog.id).where(ServiceLog.level == "error")
                        .order_by(ServiceLog.created_at.desc(), ServiceLog.id.desc())
                        .limit(MAX_ERROR_LOGS))
        db.query(ServiceLog).filter(ServiceLog.level == "error", ServiceLog.id.notin_(retained_ids)).delete(synchronize_session=False)
