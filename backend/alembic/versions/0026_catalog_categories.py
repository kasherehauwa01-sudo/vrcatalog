"""Persistent catalog hierarchy; no network or product data changes."""
from alembic import op
import sqlalchemy as sa

revision = "0026_catalog_categories"
down_revision = "0025_security_hardening"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("catalog_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_path", sa.String(512), nullable=False, unique=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_table("catalog_section_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("catalog_categories.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("normalized_name", sa.String(255), nullable=False),
        sa.Column("source_path", sa.String(512), nullable=False, unique=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False))
    op.create_index("ix_catalog_section_mappings_category_id", "catalog_section_mappings", ["category_id"])
    op.create_index("ix_catalog_section_mappings_normalized_name", "catalog_section_mappings", ["normalized_name"])
    op.create_table("catalog_sync_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_attempt_at", sa.DateTime()),
        sa.Column("last_success_at", sa.DateTime()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("category_count", sa.Integer(), nullable=False),
        sa.Column("section_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text()))
    op.add_column("products", sa.Column("category_id", sa.Integer(), sa.ForeignKey("catalog_categories.id", name="fk_products_catalog_category")))
    op.add_column("products", sa.Column("category1", sa.String(255)))
    op.create_index("ix_products_category_id", "products", ["category_id"])


def downgrade():
    op.drop_index("ix_products_category_id", table_name="products")
    op.drop_column("products", "category1")
    op.drop_column("products", "category_id")
    op.drop_table("catalog_sync_state")
    op.drop_table("catalog_section_mappings")
    op.drop_table("catalog_categories")
