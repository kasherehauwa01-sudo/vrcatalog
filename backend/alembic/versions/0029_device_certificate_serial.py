"""Add serial number to device certificates."""

from alembic import op
import sqlalchemy as sa

revision = "0029_device_certificate_serial"
down_revision = "0028_device_certificates"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "device_certificates",
        sa.Column("serial_number", sa.String(40), nullable=True),
    )
    op.create_unique_constraint(
        "uq_device_certificates_serial_number",
        "device_certificates",
        ["serial_number"],
    )


def downgrade():
    op.drop_constraint(
        "uq_device_certificates_serial_number",
        "device_certificates",
        type_="unique",
    )
    op.drop_column("device_certificates", "serial_number")
