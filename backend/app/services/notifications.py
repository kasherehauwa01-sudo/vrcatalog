from sqlalchemy.orm import Session

from app.models.catalog import Notification


def add_notification(db: Session, type_: str, title: str, message: str) -> None:
    """Создает понятное уведомление для пользователя."""
    db.add(Notification(type=type_, title=title, message=message, is_read=False))
