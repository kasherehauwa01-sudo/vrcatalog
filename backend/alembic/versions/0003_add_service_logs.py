"""add service logs"""
from alembic import op
import sqlalchemy as sa

revision = "0003_add_service_logs"
down_revision = "0002_add_product_optional_columns"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "service_logs" in inspector.get_table_names():
        return
    op.create_table(
        "service_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("level", sa.String(length=32), nullable=False, server_default="info"),
        sa.Column("event", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_service_logs_level", "service_logs", ["level"])
    op.create_index("ix_service_logs_event", "service_logs", ["event"])
    op.create_index("ix_service_logs_created_at", "service_logs", ["created_at"])


def downgrade():
    op.drop_table("service_logs")
