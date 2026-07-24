"""add warehouse settings"""
from alembic import op
import sqlalchemy as sa

revision = "0007_add_warehouse_settings"
down_revision = "0006_drop_legacy_price_value_column"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "warehouse_settings" not in inspector.get_table_names():
        op.create_table(
            "warehouse_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("code", sa.String(length=255), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_warehouse_settings_code", "warehouse_settings", ["code"], unique=True)
        op.create_index("ix_warehouse_settings_name", "warehouse_settings", ["name"])


def downgrade():
    pass
