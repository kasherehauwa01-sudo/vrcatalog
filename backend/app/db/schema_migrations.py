from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

PRODUCT_COLUMNS: dict[str, str] = {
    "article": "VARCHAR(255)",
    "section": "VARCHAR(255)",
    "description": "TEXT",
    "quantity": "FLOAT DEFAULT 0",
    "manufacturer": "VARCHAR(255)",
    "brand": "VARCHAR(255)",
    "manager": "VARCHAR(255)",
    "country": "VARCHAR(255)",
    "material": "VARCHAR(255)",
    "color": "VARCHAR(255)",
    "certificate": "TEXT",
    "tags": "TEXT",
    "search_text": "TEXT DEFAULT ''",
}


def ensure_product_columns(engine: Engine) -> None:
    """Автомиграция для уже созданных БД: добавляет отсутствующие колонки Product."""

    inspector = inspect(engine)
    if "products" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("products")}
    missing_columns = {name: ddl for name, ddl in PRODUCT_COLUMNS.items() if name not in existing_columns}
    if not missing_columns:
        return
    dialect = engine.dialect.name
    with engine.begin() as connection:
        for name, ddl in missing_columns.items():
            if dialect == "postgresql":
                sql = f'ALTER TABLE products ADD COLUMN IF NOT EXISTS "{name}" {ddl}'
            else:
                sql = f'ALTER TABLE products ADD COLUMN "{name}" {ddl}'
            logger.info("Добавляю отсутствующую колонку products.%s", name)
            connection.execute(text(sql))
