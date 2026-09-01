"""add xml auto import settings"""
from alembic import op
import sqlalchemy as sa

revision = "0010_add_xml_auto_import_settings"
down_revision = "0009_create_product_images"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "xml_server_settings" not in tables:
        op.create_table(
            "xml_server_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("protocol", sa.String(length=16), nullable=False, server_default="FTP"),
            sa.Column("host", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("port", sa.Integer(), nullable=False, server_default="21"),
            sa.Column("username", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("password", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("xml_dir", sa.String(length=512), nullable=False, server_default="/xml"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
    if "auto_import_state" not in tables:
        op.create_table(
            "auto_import_state",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="stopped"),
            sa.Column("last_run_at", sa.DateTime(), nullable=True),
            sa.Column("processed_files", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("successful_files", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_files", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("is_running", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )


def downgrade():
    op.drop_table("auto_import_state")
    op.drop_table("xml_server_settings")
