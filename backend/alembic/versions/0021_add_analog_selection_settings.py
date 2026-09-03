"""add dynamic analog selection settings"""

from alembic import op
import sqlalchemy as sa


revision = "0021_analog_settings"
down_revision = "0020_promotion_code"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_products_section_product_type", "products", ["section", "product_type"])
    op.create_table(
        "analog_selection_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("primary_properties_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("minimum_similarity", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("maximum_analogs", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("analog_selection_settings")
    op.drop_index("ix_products_section_product_type", table_name="products")
