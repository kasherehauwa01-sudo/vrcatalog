"""add idempotent promotion state and event keys"""

from alembic import op
import sqlalchemy as sa


revision = "0019_promotion_state"
down_revision = "0018_ftp_retries"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("product_type_changes", sa.Column("event_key", sa.String(512)))
    op.add_column("product_type_changes", sa.Column("claim_token", sa.String(64)))
    op.create_index("ix_product_type_changes_event_key", "product_type_changes", ["event_key"], unique=True)
    op.create_index("ix_product_type_changes_claim_token", "product_type_changes", ["claim_token"])
    op.create_table(
        "product_promotion_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("article_key", sa.String(255), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("promo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("current_value", sa.String(255)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_product_promotion_states_article_key", "product_promotion_states", ["article_key"], unique=True)
    op.create_index("ix_product_promotion_states_product_id", "product_promotion_states", ["product_id"])


def downgrade():
    op.drop_table("product_promotion_states")
    op.drop_index("ix_product_type_changes_claim_token", table_name="product_type_changes")
    op.drop_index("ix_product_type_changes_event_key", table_name="product_type_changes")
    op.drop_column("product_type_changes", "claim_token")
    op.drop_column("product_type_changes", "event_key")
