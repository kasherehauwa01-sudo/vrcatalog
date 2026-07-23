"""add optional product columns used by XML import"""
from alembic import op
import sqlalchemy as sa

revision = "0002_add_product_optional_columns"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

PRODUCT_COLUMNS = {
    "article": sa.String(length=255),
    "section": sa.String(length=255),
    "description": sa.Text(),
    "quantity": sa.Float(),
    "manufacturer": sa.String(length=255),
    "brand": sa.String(length=255),
    "manager": sa.String(length=255),
    "country": sa.String(length=255),
    "material": sa.String(length=255),
    "color": sa.String(length=255),
    "certificate": sa.Text(),
    "tags": sa.Text(),
    "search_text": sa.Text(),
}


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("products")}
    for name, column_type in PRODUCT_COLUMNS.items():
        if name not in existing:
            op.add_column("products", sa.Column(name, column_type, nullable=True))


def downgrade():
    # Не удаляем пользовательские данные при откате технической миграции.
    pass
