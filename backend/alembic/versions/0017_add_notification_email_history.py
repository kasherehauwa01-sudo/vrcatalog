"""add persistent notification email history"""

from alembic import op
import sqlalchemy as sa


revision = "0017_email_history"
down_revision = "0016_monthly_promotion"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notification_email_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scenario_code", sa.String(64), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("recipients_json", sa.Text(), nullable=False),
        sa.Column("subject", sa.String(512), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("duration_ms", sa.Float(), nullable=False, server_default="0"),
    )
    op.create_index("ix_notification_email_history_scenario_code", "notification_email_history", ["scenario_code"])
    op.create_index("ix_notification_email_history_sent_at", "notification_email_history", ["sent_at"])
    op.create_index("ix_notification_email_history_status", "notification_email_history", ["status"])


def downgrade():
    op.drop_table("notification_email_history")
