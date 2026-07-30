"""add an index for internal product lookup by article"""

from alembic import op
import sqlalchemy as sa


revision = "0015_product_article_index"
down_revision = "0014_merge_heads"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("products")}
    if "ix_products_article" not in indexes:
        op.create_index("ix_products_article", "products", ["article"], unique=False)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("products")}
    if "ix_products_article" in indexes:
        op.drop_index("ix_products_article", table_name="products")
