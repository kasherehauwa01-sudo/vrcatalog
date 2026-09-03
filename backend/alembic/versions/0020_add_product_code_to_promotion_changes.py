"""add product code snapshot to promotion changes"""

from alembic import op
import sqlalchemy as sa


revision = "0020_promotion_code"
down_revision = "0019_promotion_state"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("product_type_changes", sa.Column("product_code", sa.String(255)))
    op.execute(
        "UPDATE product_type_changes "
        "SET product_code = (SELECT products.code FROM products "
        "WHERE products.id = product_type_changes.product_id)"
    )


def downgrade():
    op.drop_column("product_type_changes", "product_code")
