import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import router
from app.db.session import Base, get_db
from app.models.catalog import Product, ProductProperty
from app.services.catalog import catalog_product_query, folder_paths
from app.services.catalog_folders import folder_path
from app.services.unneeded_folder import current_products

NAME = 'Мочалка люфа лента с х|б ручками, овальная Банные штучки (30)'
PREFIX = 'БАНЯ|ЛИНК ГРУПП|БАНЯ'


class FolderProductNamesTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add_all([
            Product(code='001', name=NAME, properties=[ProductProperty(name='ПолныйПуть', value=PREFIX + '|' + NAME)]),
            Product(code='002', name='Мочалка нейлон', properties=[ProductProperty(name='Полныйпуть', value=PREFIX + '|Мочалка нейлон')]),
            Product(code='003', name='Тандыр', properties=[ProductProperty(name='ПолныйПуть', value='МЕТАЛЛ|ПОСУДА|АМФОРА|Тандыр')]),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_actual_pipe_in_product_name_never_becomes_a_folder(self):
        self.assertEqual(folder_paths(self.db), [PREFIX, 'МЕТАЛЛ|ПОСУДА|АМФОРА'])
        self.assertEqual({product.code for product in catalog_product_query(self.db, {'folder': [PREFIX]}, eager_load=False)}, {'001', '002'})

    def test_split_stale_name_is_removed_from_filter_tree(self):
        self.db.add(Product(code='board', name='Доска с обновлённым названием', properties=[
            ProductProperty(name='ПолныйПуть', value='МЕТАЛЛ|ПОСУДА для ПРИГОТОВЛЕНИЯ|ТАЛЛЕР|Доска разделочная|34,5*18*1|АКРОС')]))
        self.db.commit()
        self.assertIn('МЕТАЛЛ|ПОСУДА для ПРИГОТОВЛЕНИЯ|ТАЛЛЕР', folder_paths(self.db))
        self.assertFalse(any('Доска' in path or '34,5' in path or 'АКРОС' in path for path in folder_paths(self.db)))

    def test_parser_preserves_deep_folders_and_legacy_paths(self):
        cases = [
            (PREFIX + '|' + NAME, NAME, PREFIX),
            ('A|B|C|D|E|Name|with|pipes', 'Name|with|pipes', 'A|B|C|D|E'),
            ('A|Name|Name', 'Name', 'A'),
            ('A| Name  with | spaces |', 'name with|spaces', 'A'),
            ('A|Old name', 'Renamed product', 'A'),
            ('Name|with|pipes', 'Name|with|pipes', None),
            ('A||Name', 'Name', None),
            ('МЕТАЛЛ|ПОСУДА для ПРИГОТОВЛЕНИЯ|ТАЛЛЕР|Доска разделочная|34,5*18*1|АРКОС', 'Другое имя', 'МЕТАЛЛ|ПОСУДА для ПРИГОТОВЛЕНИЯ|ТАЛЛЕР'),
            ('БАНЯ|34,5*18*1|АРКОС|Товар', 'Товар', 'БАНЯ'),
            ('МЕТАЛЛ|АКРОС|НОЖ', 'НОЖ', 'МЕТАЛЛ|АКРОС'),
            ('Name', 'Name', None),
            ('', '', None),
        ]
        for value, name, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(folder_path(value, name, uppercase_only=True), expected)

    def test_endpoint_returns_only_folder_prefixes_in_one_narrow_query(self):
        app = FastAPI()
        app.include_router(router, prefix='/api')
        def database():
            with Session(self.engine) as db:
                yield db
        app.dependency_overrides[get_db] = database
        statements = []
        event.listen(self.engine, 'before_cursor_execute', lambda conn, cursor, sql, params, context, many: statements.append(sql))
        with TestClient(app) as client:
            response = client.get('/api/filters/folders')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [PREFIX, 'МЕТАЛЛ|ПОСУДА|АМФОРА'])
        self.assertEqual(len(statements), 1)
        self.assertIn('products.name', statements[0])
        self.assertNotIn('products.description', statements[0])
        self.assertNotIn('product_images', statements[0])

    def test_notification_does_not_mistake_name_fragment_for_unneeded_folder(self):
        self.db.add_all([
            Product(code='004', name='Мочалка|НЕНУЖНОЕ|ручки', properties=[ProductProperty(name='ПолныйПуть', value='БАНЯ|Мочалка|НЕНУЖНОЕ|ручки')]),
            Product(code='005', name=NAME, properties=[ProductProperty(name='ПолныйПуть', value='НЕНУЖНОЕ|' + NAME)]),
        ])
        self.db.commit()
        self.assertEqual(set(current_products(self.db)), {'005'})
