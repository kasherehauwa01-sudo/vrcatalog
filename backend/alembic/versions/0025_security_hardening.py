"""add admin sessions and encrypted FTP credentials"""

from alembic import op
import sqlalchemy as sa


revision = "0025_security_hardening"
down_revision = "0024_history_snapshots"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_hash", sa.String(64), nullable=False),
        sa.Column("csrf_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_admin_sessions_session_hash", "admin_sessions", ["session_hash"], unique=True)
    op.create_index("ix_admin_sessions_expires_at", "admin_sessions", ["expires_at"])
    op.add_column("xml_server_settings", sa.Column("encrypted_password", sa.Text(), nullable=False, server_default=""))


def downgrade():
    op.drop_column("xml_server_settings", "encrypted_password")
    op.drop_table("admin_sessions")
