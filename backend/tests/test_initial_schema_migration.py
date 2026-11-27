import importlib.util
import os
from uuid import uuid4
from pathlib import Path
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect, text


def migration(filename):
    path = Path(__file__).resolve().parents[1] / 'alembic' / 'versions' / filename
    spec = importlib.util.spec_from_file_location('migration_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def isolated_engine():
    engine = create_engine(os.environ.get('REGRESSION_DATABASE_URL', 'sqlite://'))
    if engine.dialect.name == 'postgresql':
        schema = 'migration_regression_' + uuid4().hex
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        @event.listens_for(engine, 'connect')
        def search_path(connection, _record):
            with connection.cursor() as cursor:
                cursor.execute(f'SET search_path TO "{schema}"')
            connection.commit()
        engine.dispose()
    return engine


class InitialSchemaMigrationTests(unittest.TestCase):
    def test_initial_revision_does_not_create_tables_from_future_revisions(self):
        engine = isolated_engine()
        with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
            migration('0001_initial.py').upgrade()
            tables = inspect(connection).get_table_names()
            self.assertEqual(set(tables), {'import_runs', 'products', 'prices', 'stocks', 'product_properties',
                                         'product_images', 'analogs', 'barcodes', 'view_history', 'favorites'})
            self.assertNotIn('created_at', {c['name'] for c in inspect(connection).get_columns('products')})
        engine.dispose()

    def test_legacy_image_upgrade_preserves_all_urls_and_assigns_stable_order(self):
        engine = isolated_engine()
        with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
            migration('0001_initial.py').upgrade()
            connection.execute(text("INSERT INTO products (id, code, name, quantity, search_text) VALUES (1, 'P', 'Product', 0, '')"))
            connection.execute(text("INSERT INTO product_images (product_id, url) VALUES (1, 'first.jpg'), (1, 'second.jpg')"))
            connection.execute(text('ALTER TABLE products ADD COLUMN image_url TEXT'))
            connection.execute(text("UPDATE products SET image_url='third.jpg'"))
            migration('0009_create_product_images.py').upgrade()
            self.assertEqual(connection.execute(text('SELECT image_order, image_url FROM product_images ORDER BY image_order')).all(),
                             [(1, 'first.jpg'), (2, 'second.jpg'), (3, 'third.jpg')])
            self.assertNotIn('url', {c['name'] for c in inspect(connection).get_columns('product_images')})
            self.assertEqual(connection.execute(text('SELECT count(*) FROM product_images WHERE created_at IS NOT NULL')).scalar_one(), 3)
        engine.dispose()
