"""drop legacy price value column"""
from alembic import op
import sqlalchemy as sa

revision = "0006_drop_legacy_price_value_column"
down_revision = "0005_add_product_image_url"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    price_columns = {column["name"] for column in inspector.get_columns("prices")}

    if "price_value" not in price_columns:
        op.add_column("prices", sa.Column("price_value", sa.Float(), nullable=True))
        price_columns.add("price_value")

    if "value" in price_columns:
        op.execute("UPDATE prices SET price_value = value WHERE price_value IS NULL")

    op.execute("UPDATE prices SET price_value = 0 WHERE price_value IS NULL")
    op.alter_column("prices", "price_value", existing_type=sa.Float(), nullable=False, server_default=None)

    if "value" in price_columns:
        op.drop_column("prices", "value")


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    price_columns = {column["name"] for column in inspector.get_columns("prices")}
    if "value" not in price_columns:
        op.add_column("prices", sa.Column("value", sa.Float(), nullable=False, server_default="0"))
    op.execute("UPDATE prices SET value = price_value WHERE value = 0")
