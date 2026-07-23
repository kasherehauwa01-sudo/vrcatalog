"""make prices flexible and add notifications"""
from alembic import op
import sqlalchemy as sa

revision = "0004_make_prices_flexible_and_add_notifications"
down_revision = "0003_add_service_logs"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    price_columns = {column["name"] for column in inspector.get_columns("prices")}
    if "price_value" not in price_columns:
        op.add_column("prices", sa.Column("price_value", sa.Float(), nullable=True, server_default="0"))
        if "value" in price_columns:
            op.execute("UPDATE prices SET price_value = value WHERE price_value IS NULL OR price_value = 0")
    if "notifications" not in inspector.get_table_names():
        op.create_table(
            "notifications",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("type", sa.String(length=64), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.create_index("ix_notifications_type", "notifications", ["type"])
        op.create_index("ix_notifications_created_at", "notifications", ["created_at"])
        op.create_index("ix_notifications_is_read", "notifications", ["is_read"])


def downgrade():
    pass
