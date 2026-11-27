import sqlite3
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

@event.listens_for(Engine, "connect")
def sqlite_unicode_case(connection, _record):
    # SQLite's built-in lower/upper only handle ASCII; ILIKE uses these on SQLite.
    # PostgreSQL retains its native collation-aware functions.
    if isinstance(connection, sqlite3.Connection):
        connection.create_function("lower", 1, lambda value: None if value is None else str(value).lower(), deterministic=True)
        connection.create_function("upper", 1, lambda value: None if value is None else str(value).upper(), deterministic=True)


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    except SQLAlchemyError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
