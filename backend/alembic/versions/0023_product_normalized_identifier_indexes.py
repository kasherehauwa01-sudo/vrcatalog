"""add normalized product identifier indexes"""

from alembic import op
import sqlalchemy as sa


revision = "0023_product_identifier_indexes"
down_revision = "0022_property_normalized_index"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_products_normalized_code",
        "products",
        [sa.text("lower(trim(code))")],
    )
    op.create_index(
        "ix_products_normalized_article",
        "products",
        [sa.text("lower(trim(article))")],
    )


def downgrade():
    op.drop_index("ix_products_normalized_article", table_name="products")
    op.drop_index("ix_products_normalized_code", table_name="products")
