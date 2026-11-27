"""Track pending device certificate replacements."""
import sqlalchemy as sa
from alembic import op

revision = "0030_device_pkcs12_replacement"
down_revision = "0029_device_certificate_serial"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("device_certificates") as batch:
        batch.add_column(sa.Column("replaces_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("activated_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("crl_pending", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.create_foreign_key("fk_device_replacement_original", "device_certificates", ["replaces_id"], ["id"])
        batch.create_check_constraint("ck_device_replacement_not_self", "replaces_id <> id")
        batch.create_check_constraint(
            "ck_device_replacement_state", "replaces_id IS NOT NULL OR (activated_at IS NULL AND NOT crl_pending)",
        )
        batch.create_check_constraint("ck_device_replacement_crl", "NOT crl_pending OR activated_at IS NOT NULL")
    where = sa.text("replaces_id IS NOT NULL AND activated_at IS NULL AND revoked_at IS NULL")
    op.create_index("uq_device_pending_replacement", "device_certificates", ["replaces_id"],
                    unique=True, postgresql_where=where, sqlite_where=where)


def downgrade():
    # The old verifier ignores replacement state. Keep every unactivated
    # certificate blocked before removing the columns.
    op.execute(sa.text(
        "UPDATE device_certificates SET revoked_at = CURRENT_TIMESTAMP "
        "WHERE replaces_id IS NOT NULL AND activated_at IS NULL AND revoked_at IS NULL"
    ))
    op.drop_index("uq_device_pending_replacement", table_name="device_certificates")
    with op.batch_alter_table("device_certificates") as batch:
        batch.drop_constraint("ck_device_replacement_crl", type_="check")
        batch.drop_constraint("ck_device_replacement_state", type_="check")
        batch.drop_constraint("ck_device_replacement_not_self", type_="check")
        batch.drop_constraint("fk_device_replacement_original", type_="foreignkey")
        batch.drop_column("crl_pending")
        batch.drop_column("activated_at")
        batch.drop_column("replaces_id")
