"""add a trigram index for catalog search"""

from alembic import op

revision = "0012_product_search_index"
down_revision = "0011_add_service_log_details"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_products_search_text_trgm "
        "ON products USING gin (search_text gin_trgm_ops)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_products_search_text_trgm")
