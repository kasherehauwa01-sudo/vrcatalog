from sqlalchemy.orm import Session

from app.models.catalog import ServiceLog


def add_log(db: Session, event: str, message: str, level: str = "info") -> None:
    """Сохраняет служебное событие в БД без прерывания основной бизнес-операции."""
    db.add(ServiceLog(event=event, message=message, level=level))
