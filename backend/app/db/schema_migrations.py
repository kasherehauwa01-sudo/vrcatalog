from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.models.catalog import Product

logger = logging.getLogger(__name__)


def _column_sql_type(engine: Engine, column_name: str) -> str:
    column = Product.__table__.columns[column_name]
    sql_type = column.type.compile(dialect=engine.dialect)
    if column_name == "quantity":
        return f"{sql_type} DEFAULT 0"
    if column_name == "search_text":
        return f"{sql_type} DEFAULT ''"
    return sql_type


def ensure_product_columns(engine: Engine) -> None:
    """Автомиграция: сверяет модель Product с таблицей products и добавляет отсутствующие колонки."""

    inspector = inspect(engine)
    if "products" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("products")}
    model_columns = [column.name for column in Product.__table__.columns]
    missing_columns = [name for name in model_columns if name not in existing_columns]
    if not missing_columns:
        return
    dialect = engine.dialect.name
    with engine.begin() as connection:
        for name in missing_columns:
            sql_type = _column_sql_type(engine, name)
            if dialect == "postgresql":
                sql = f'ALTER TABLE products ADD COLUMN IF NOT EXISTS "{name}" {sql_type}'
            else:
                sql = f'ALTER TABLE products ADD COLUMN "{name}" {sql_type}'
            logger.info("Добавляю отсутствующую колонку products.%s", name)
            connection.execute(text(sql))


def ensure_price_columns(engine: Engine) -> None:
    """Добавляет универсальную колонку prices.price_value и переносит старые значения value."""
    inspector = inspect(engine)
    if "prices" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("prices")}
    if "price_value" in existing_columns:
        return
    dialect = engine.dialect.name
    with engine.begin() as connection:
        sql = 'ALTER TABLE prices ADD COLUMN IF NOT EXISTS "price_value" FLOAT DEFAULT 0' if dialect == "postgresql" else 'ALTER TABLE prices ADD COLUMN "price_value" FLOAT DEFAULT 0'
        logger.info("Добавляю отсутствующую колонку prices.price_value")
        connection.execute(text(sql))
        if "value" in existing_columns:
            connection.execute(text('UPDATE prices SET price_value = value WHERE price_value IS NULL OR price_value = 0'))
