"""create product images"""
from alembic import op
import sqlalchemy as sa

revision = "0009_create_product_images"
down_revision = "0008_add_product_type_settings"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = inspector.get_table_names()
    if "product_images" not in table_names:
        op.create_table(
            "product_images",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
            sa.Column("image_order", sa.Integer(), nullable=False),
            sa.Column("image_url", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_product_images_product_id", "product_images", ["product_id"])
        op.create_index("uq_product_images_product_order", "product_images", ["product_id", "image_order"], unique=True)

    product_columns = {column["name"] for column in inspector.get_columns("products")}
    if "image_url" in product_columns:
        op.execute(
            """
            INSERT INTO product_images (product_id, image_order, image_url, created_at)
            SELECT id, 1, image_url, CURRENT_TIMESTAMP
            FROM products
            WHERE image_url IS NOT NULL AND image_url != ''
            """
        )
        op.drop_column("products", "image_url")


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    product_columns = {column["name"] for column in inspector.get_columns("products")}
    if "image_url" not in product_columns:
        op.add_column("products", sa.Column("image_url", sa.Text(), nullable=True))
    if "product_images" in inspector.get_table_names():
        op.execute(
            """
            UPDATE products
            SET image_url = (
                SELECT image_url
                FROM product_images
                WHERE product_images.product_id = products.id
                ORDER BY image_order
                LIMIT 1
            )
            """
        )
        op.drop_table("product_images")
