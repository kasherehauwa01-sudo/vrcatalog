"""add product image url"""
from alembic import op
import sqlalchemy as sa

revision = "0005_add_product_image_url"
down_revision = "0004_make_prices_flexible_and_add_notifications"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    product_columns = {column["name"] for column in inspector.get_columns("products")}
    if "image_url" not in product_columns:
        op.add_column("products", sa.Column("image_url", sa.Text(), nullable=True))


def downgrade():
    pass
