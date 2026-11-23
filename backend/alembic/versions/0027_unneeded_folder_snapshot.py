"""Durable membership baseline for the daily unneeded-folder digest."""
from alembic import op
import sqlalchemy as sa

revision = "0027_unneeded_folder_snapshot"
down_revision = "0026_catalog_categories"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("unneeded_folder_snapshot",
                    sa.Column("product_code", sa.String(128), primary_key=True))


def downgrade():
    op.drop_table("unneeded_folder_snapshot")
