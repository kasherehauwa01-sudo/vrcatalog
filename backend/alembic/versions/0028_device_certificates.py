"""Device certificate allowlist."""
from alembic import op
import sqlalchemy as sa

revision = "0028_device_certificates"
down_revision = "0027_unneeded_folder_snapshot"
branch_labels = None
depends_on = None


def upgrade():
    # Migration 0001 imports the current model metadata.
    if sa.inspect(op.get_bind()).has_table("device_certificates"):
        return
    op.create_table(
        "device_certificates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("owner", sa.String(160), nullable=False),
        sa.Column("comment", sa.String(500), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("public_key_fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("common_name", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("revoked_at", sa.DateTime),
        sa.Column("last_seen_at", sa.DateTime),
    )


def downgrade():
    op.drop_table("device_certificates")
