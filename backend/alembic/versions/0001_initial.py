"""Initial catalog schema, frozen from b9c793c (never import live ORM metadata)."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def initial_schema():
    metadata = sa.MetaData()
    sa.Table('import_runs', metadata,
             sa.Column('id', sa.Integer, primary_key=True),
             sa.Column('filename', sa.String(255), nullable=False),
             sa.Column('status', sa.String(32), nullable=False),
             sa.Column('imported_count', sa.Integer, nullable=False),
             sa.Column('errors', sa.Text), sa.Column('created_at', sa.DateTime, nullable=False),
             sa.Column('finished_at', sa.DateTime))
    sa.Table('products', metadata,
             sa.Column('id', sa.Integer, primary_key=True),
             sa.Column('code', sa.String(128), index=True, unique=True, nullable=False),
             sa.Column('name', sa.String(512), index=True, nullable=False),
             *(sa.Column(name, sa.String(255), index=True) for name in
               ('article', 'section', 'manufacturer', 'brand', 'manager', 'country', 'material', 'color')),
             sa.Column('description', sa.Text), sa.Column('tags', sa.Text),
             sa.Column('quantity', sa.Float, nullable=False), sa.Column('search_text', sa.Text, nullable=False))
    def related(name, *columns):
        return sa.Table(name, metadata, sa.Column('id', sa.Integer, primary_key=True),
                        sa.Column('product_id', sa.Integer, sa.ForeignKey('products.id', ondelete='CASCADE'), index=True, nullable=False),
                        *columns)
    related('prices', sa.Column('price_type', sa.String(255), index=True, nullable=False), sa.Column('value', sa.Float, nullable=False))
    related('stocks', sa.Column('warehouse', sa.String(255), index=True, nullable=False), sa.Column('quantity', sa.Float, nullable=False))
    related('product_properties', sa.Column('property_code', sa.String(255), index=True),
            sa.Column('name', sa.String(255), index=True, nullable=False), sa.Column('value', sa.Text))
    related('product_images', sa.Column('url', sa.Text, nullable=False))
    related('analogs', sa.Column('code', sa.String(255), index=True), sa.Column('name', sa.String(512)))
    related('barcodes', sa.Column('value', sa.String(255), index=True, nullable=False))
    related('view_history', sa.Column('viewed_at', sa.DateTime, nullable=False))
    sa.Table('favorites', metadata,
             sa.Column('product_id', sa.Integer, sa.ForeignKey('products.id', ondelete='CASCADE'), primary_key=True),
             sa.Column('created_at', sa.DateTime, nullable=False))
    return metadata


def upgrade():
    initial_schema().create_all(bind=op.get_bind())


def downgrade():
    initial_schema().drop_all(bind=op.get_bind())
