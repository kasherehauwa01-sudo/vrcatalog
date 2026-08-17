"""add monthly promotion notification settings and change journal"""

from alembic import op
import sqlalchemy as sa


revision = "0016_monthly_promotion"
down_revision = "0015_product_article_index"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mail_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("smtp_host", sa.String(255), nullable=False, server_default=""),
        sa.Column("smtp_port", sa.Integer(), nullable=False, server_default="587"),
        sa.Column("encryption", sa.String(16), nullable=False, server_default="starttls"),
        sa.Column("username", sa.String(255), nullable=False, server_default=""),
        sa.Column("encrypted_password", sa.Text(), nullable=False, server_default=""),
        sa.Column("sender_name", sa.String(255), nullable=False, server_default="VR Catalog"),
        sa.Column("sender_email", sa.String(255), nullable=False, server_default=""),
        sa.Column("connection_status", sa.String(32), nullable=False, server_default="not_configured"),
        sa.Column("last_success_at", sa.DateTime()),
        sa.Column("last_sent_at", sa.DateTime()),
        sa.Column("last_error", sa.Text()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "notification_scenario_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("send_time", sa.String(5), nullable=False, server_default="22:00"),
        sa.Column("recipients_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("last_run_date", sa.String(10)),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_notification_scenario_settings_code", "notification_scenario_settings", ["code"], unique=True)
    op.create_index("ix_notification_scenario_settings_last_run_date", "notification_scenario_settings", ["last_run_date"])
    op.create_table(
        "product_type_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("article", sa.String(255)),
        sa.Column("product_name", sa.String(512), nullable=False),
        sa.Column("old_value", sa.String(255)),
        sa.Column("new_value", sa.String(255)),
        sa.Column("source", sa.String(64), nullable=False, server_default="api"),
        sa.Column("processed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime()),
    )
    op.create_index("ix_product_type_changes_product_id", "product_type_changes", ["product_id"])
    op.create_index("ix_product_type_changes_processed", "product_type_changes", ["processed"])
    op.create_index("ix_product_type_changes_changed_at", "product_type_changes", ["changed_at"])


def downgrade():
    op.drop_table("product_type_changes")
    op.drop_table("notification_scenario_settings")
    op.drop_table("mail_settings")
