"""Run on SQLite by default; REGRESSION_DATABASE_URL targets an isolated PostgreSQL test DB."""
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

from openpyxl import load_workbook
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.catalog import Product, Price, ServiceLog
from app.schemas.catalog import IntegrationProductSearchRequest
from app.services.catalog import catalog_product_query, integration_product_search
from app.services.logging import add_log
from app.api.routes import build_export_workbook, write_export_workbook_streaming
from app.importer.xml_importer import XMLCatalogImporter


class DatabaseRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        url = os.environ.get('REGRESSION_DATABASE_URL', 'sqlite:///' + self.temp.name + '/test.sqlite')
        self.root = create_engine(url)
        if self.root.dialect.name == 'postgresql':
            # Never touch existing tables. Retain these isolated schemas for inspection.
            schema = 'regression_' + uuid4().hex
            with self.root.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            self.engine = self.root.execution_options(schema_translate_map={None: schema})
        else:
            self.engine = self.root
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self):
        self.db.close()
        self.root.dispose()
        self.temp.cleanup()

    def test_unicode_search_identifiers_and_integration_pagination(self):
        self.db.add_all([
            Product(code='СТ-001', article='АРТ-1', name='Стул Альфа', section='Мебель', search_text='стул альфа ст-001 арт-1 460123'),
            Product(code='СТ-002', article='АРТ-2', name='СТУЛ Бета', section='Мебель', search_text='стул бета ст-002 арт-2'),
            Product(code='СТ-003', name='Стол', section='Мебель', search_text='стол'),
        ])
        self.db.commit()
        def codes(**params):
            return [p.code for p in catalog_product_query(self.db, params).order_by(Product.code)]
        self.assertEqual(codes(search='  СТУЛ  '), ['СТ-001', 'СТ-002'])
        self.assertEqual(codes(name='сТуЛ'), ['СТ-001', 'СТ-002'])
        self.assertEqual(codes(article='арт-1'), ['СТ-001'])
        self.assertEqual(codes(search='460123'), ['СТ-001'])
        self.assertEqual(codes(code='ст-002, ст-001'), ['СТ-001', 'СТ-002'])
        items, total = integration_product_search(self.db, IntegrationProductSearchRequest(
            search=' стул ', sort_by='code', sort_dir='desc', page=2, page_size=1))
        self.assertEqual((total, [p.code for p in items]), (2, ['СТ-001']))
        items, total = integration_product_search(self.db, IntegrationProductSearchRequest(
            search=' СТУЛ ', excluded=[{'code': 'СТ-002'}]))
        self.assertEqual((total, [p.code for p in items]), (1, ['СТ-001']))

    def test_legacy_prices_in_both_exporters_and_explicit_xml_price_wins(self):
        product = Product(code='P', name='Товар', prices=[Price(price_type='Розничная', price_value=1500)])
        self.db.add(product)
        self.db.commit()
        for expected in (1500, 1700):
            for streaming in (False, True):
                path = Path(self.temp.name) / 'prices.xlsx'
                columns = ['code', 'price:ЦенаРозничная']
                params = {'in_stock_only': False, 'exclude_yyy': False}
                if streaming:
                    write_export_workbook_streaming(self.db, params, columns, str(path), 'test', 1)
                else:
                    book = build_export_workbook(self.db, params, columns)
                    book.save(path)
                    book.close()
                book = load_workbook(path)
                self.assertEqual(book.active['B2'].value, expected)
                book.close()
            if expected == 1500:
                product.prices.append(Price(price_type='ЦенаРозничная', price_value=1700))
                self.db.commit()

    def test_error_retention_with_concurrent_writers_preserves_information(self):
        add_log(self.db, 'info', 'Keep this information')
        for index in range(100):
            add_log(self.db, f'old-{index}', 'Old error', level='error')
        self.db.commit()
        barrier = Barrier(4)
        def writer(number):
            with Session(self.engine) as session:
                barrier.wait(timeout=10)
                for index in range(3):
                    add_log(session, f'new-{number}-{index}', 'New error', level='error')
                session.commit()
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(writer, range(4)))
        self.db.expire_all()
        self.assertEqual(self.db.query(ServiceLog).filter_by(level='error').count(), 100)
        self.assertEqual(self.db.query(ServiceLog).filter(ServiceLog.event.like('new-%')).count(), 12)
        self.assertEqual(self.db.query(ServiceLog).filter_by(level='info').count(), 1)
        self.assertEqual(self.db.query(ServiceLog).filter(ServiceLog.event.in_([f'old-{i}' for i in range(12)])).count(), 0)

    def test_error_retention_rollback_is_atomic(self):
        for index in range(100):
            add_log(self.db, f'old-{index}', 'Error', level='error')
        self.db.commit()
        add_log(self.db, 'rollback', 'Do not keep', level='error')
        self.db.rollback()
        self.assertEqual(self.db.query(ServiceLog).filter_by(level='error').count(), 100)
        self.assertIsNotNone(self.db.query(ServiceLog).filter_by(event='old-0').first())
        self.assertIsNone(self.db.query(ServiceLog).filter_by(event='rollback').first())

    def test_missing_quantity_is_preserved_but_explicit_zero_updates(self):
        product = Product(code='P', name='Товар', quantity=3, search_text='товар')
        self.db.add(product)
        self.db.commit()
        parsed = Product(code='P', name='Товар', search_text='товар')
        importer = XMLCatalogImporter()
        importer._sync_product_scalars(product, parsed)
        self.db.commit()
        self.assertEqual(product.quantity, 3)
        parsed.quantity = 0
        importer._sync_product_scalars(product, parsed)
        self.db.commit()
        self.assertEqual(product.quantity, 0)
