"""add product type settings"""
from alembic import op
import sqlalchemy as sa

revision = "0008_add_product_type_settings"
down_revision = "0007_add_warehouse_settings"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    product_columns = {column["name"] for column in inspector.get_columns("products")}
    if "product_type" not in product_columns:
        op.add_column("products", sa.Column("product_type", sa.String(length=255), nullable=True))
        op.create_index("ix_products_product_type", "products", ["product_type"])
    if "product_type_settings" not in inspector.get_table_names():
        op.create_table(
            "product_type_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("code", sa.String(length=255), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_product_type_settings_code", "product_type_settings", ["code"], unique=True)
        op.create_index("ix_product_type_settings_name", "product_type_settings", ["name"])


def downgrade():
    pass
