"""keep only the latest 100 error logs"""

from alembic import op

revision = "0013_trim_service_logs"
down_revision = "0012_product_search_index"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DELETE FROM service_logs WHERE level <> 'error'")
    op.execute(
        "DELETE FROM service_logs WHERE id NOT IN ("
        "SELECT id FROM service_logs "
        "ORDER BY created_at DESC, id DESC LIMIT 100)"
    )


def downgrade():
    pass
