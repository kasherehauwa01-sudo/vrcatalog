"""add product timestamps"""

from alembic import op
import sqlalchemy as sa


revision = "0012_add_product_timestamps"
down_revision = "0011_add_service_log_details"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("products")}
    if "created_at" not in columns:
        op.add_column(
            "products",
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
    if "updated_at" not in columns:
        op.add_column(
            "products",
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )


def downgrade():
    op.drop_column("products", "updated_at")
    op.drop_column("products", "created_at")
