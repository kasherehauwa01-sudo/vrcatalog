"""add immutable product history snapshots"""

from alembic import op
import sqlalchemy as sa


revision = "0024_history_snapshots"
down_revision = "0023_product_identifier_indexes"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "history_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_type", sa.String(64), nullable=False),
        sa.Column("save_for_next_month", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_history_settings_snapshot_type", "history_settings", ["snapshot_type"], unique=True)
    op.create_table(
        "history_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_type", sa.String(64), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("source_property", sa.String(255), nullable=False),
        sa.Column("source_value", sa.String(255), nullable=False),
        sa.Column("creation_source", sa.String(64), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="success"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("snapshot_type", "period", name="uq_history_snapshots_type_period"),
    )
    op.create_index("ix_history_snapshots_snapshot_type", "history_snapshots", ["snapshot_type"])
    op.create_index("ix_history_snapshots_period", "history_snapshots", ["period"])
    op.create_index("ix_history_snapshots_type_period", "history_snapshots", ["snapshot_type", "period"])
    op.create_table(
        "history_snapshot_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.Integer(), sa.ForeignKey("history_snapshots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL")),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("article", sa.String(255)),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("base_price", sa.Numeric(18, 2)),
        sa.Column("promo_price", sa.Numeric(18, 2)),
        sa.Column("product_type_code", sa.String(255)),
        sa.Column("product_type_name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("snapshot_id", "code", name="uq_history_snapshot_items_snapshot_code"),
    )
    op.create_index("ix_history_snapshot_items_snapshot_id", "history_snapshot_items", ["snapshot_id"])
    op.create_index("ix_history_snapshot_items_product_id", "history_snapshot_items", ["product_id"])
    op.create_index("ix_history_snapshot_items_code", "history_snapshot_items", ["code"])
    op.create_table(
        "history_snapshot_item_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_item_id", sa.Integer(), sa.ForeignKey("history_snapshot_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("price_type", sa.String(255), nullable=False),
        sa.Column("price_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_history_snapshot_item_prices_snapshot_item_id", "history_snapshot_item_prices", ["snapshot_item_id"])
    op.create_index("ix_history_snapshot_item_prices_price_type", "history_snapshot_item_prices", ["price_type"])


def downgrade():
    op.drop_table("history_snapshot_item_prices")
    op.drop_table("history_snapshot_items")
    op.drop_table("history_snapshots")
    op.drop_table("history_settings")
