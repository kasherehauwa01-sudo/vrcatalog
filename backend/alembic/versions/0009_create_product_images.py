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

    else:
        # The original 0001 table stored url only. Preserve images while upgrading it.
        columns = {column["name"] for column in inspector.get_columns("product_images")}
        with op.batch_alter_table("product_images") as batch:
            if "image_url" not in columns and "url" in columns:
                batch.alter_column("url", new_column_name="image_url", existing_type=sa.Text(), existing_nullable=False)
            if "image_order" not in columns:
                batch.add_column(sa.Column("image_order", sa.Integer(), nullable=True))
            if "created_at" not in columns:
                batch.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
        if "image_order" not in columns:
            op.execute("""UPDATE product_images SET image_order = ranked.position
                          FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY product_id ORDER BY id) AS position
                                FROM product_images) AS ranked WHERE product_images.id = ranked.id""")
        op.execute("UPDATE product_images SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
        with op.batch_alter_table("product_images") as batch:
            batch.alter_column("image_order", existing_type=sa.Integer(), nullable=False)
            batch.alter_column("created_at", existing_type=sa.DateTime(), nullable=False)
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes("product_images")}
        if "uq_product_images_product_order" not in indexes:
            op.create_index("uq_product_images_product_order", "product_images", ["product_id", "image_order"], unique=True)

    product_columns = {column["name"] for column in inspector.get_columns("products")}
    if "image_url" in product_columns:
        op.execute(
            """
            INSERT INTO product_images (product_id, image_order, image_url, created_at)
            SELECT id, COALESCE((SELECT MAX(image_order) FROM product_images WHERE product_id = products.id), 0) + 1, image_url, CURRENT_TIMESTAMP
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
