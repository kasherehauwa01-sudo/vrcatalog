"""Merge migration heads"""

revision = "0014_merge_heads"
down_revision = (
    "0013_trim_service_logs",
    "0012_add_product_timestamps",
)
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
