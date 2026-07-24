"""add service log details"""
from alembic import op
import sqlalchemy as sa

revision = "0011_add_service_log_details"
down_revision = "0010_add_xml_auto_import_settings"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("service_logs")}
    if "error_type" not in columns:
        op.add_column(
            "service_logs",
            sa.Column("error_type", sa.String(length=255), nullable=True),
        )
        op.create_index("ix_service_logs_error_type", "service_logs", ["error_type"])
    if "traceback" not in columns:
        op.add_column("service_logs", sa.Column("traceback", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("service_logs", "traceback")
    op.drop_index("ix_service_logs_error_type", table_name="service_logs")
    op.drop_column("service_logs", "error_type")
