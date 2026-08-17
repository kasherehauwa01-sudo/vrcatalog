"""add FTP retry settings and connection diagnostics"""

from alembic import op
import sqlalchemy as sa


revision = "0018_ftp_retries"
down_revision = "0017_email_history"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("xml_server_settings", sa.Column("connection_attempts", sa.Integer(), nullable=False, server_default="5"))
    op.add_column("xml_server_settings", sa.Column("retry_delay_seconds", sa.Integer(), nullable=False, server_default="3"))
    op.create_table(
        "ftp_connection_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("attempted_at", sa.DateTime(), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_type", sa.String(255)),
        sa.Column("error_message", sa.Text()),
    )
    op.create_index("ix_ftp_connection_logs_attempted_at", "ftp_connection_logs", ["attempted_at"])
    op.create_index("ix_ftp_connection_logs_success", "ftp_connection_logs", ["success"])


def downgrade():
    op.drop_table("ftp_connection_logs")
    op.drop_column("xml_server_settings", "retry_delay_seconds")
    op.drop_column("xml_server_settings", "connection_attempts")
