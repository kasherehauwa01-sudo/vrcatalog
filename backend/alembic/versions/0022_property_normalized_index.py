"""add normalized product property lookup index"""

from alembic import op
import sqlalchemy as sa


revision = "0022_property_normalized_index"
down_revision = "0021_analog_settings"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_product_properties_normalized_name_value",
        "product_properties",
        [sa.text("lower(trim(name))"), sa.text("lower(trim(value))")],
    )


def downgrade():
    op.drop_index("ix_product_properties_normalized_name_value", table_name="product_properties")
