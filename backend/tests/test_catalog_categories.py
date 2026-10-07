import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.session import Base
from app.models.catalog import CatalogCategory, CatalogSectionMapping, CatalogSyncState, Product
from app.services import catalog_categories as service
from app.services.catalog import catalog_product_query, product_query
from app.importer.xml_importer import XMLCatalogImporter


def fixture():
    return ''.join(f'<a href="/catalog/c{i}/" title="Категория {i}"></a>' + ''.join(
        f'<a href="/catalog/c{i}/s{j}/" title="Раздел {i} {j}"></a>' for j in range(10)) for i in range(10))


class ParserTests(unittest.TestCase):
    def test_category_title(self):
        categories, _ = service.parse_catalog('<a href="/catalog/interior/" title="Интерьер">Wrong</a>')
        self.assertEqual(categories[0]['name'], 'Интерьер')

    def test_subcategory_title_and_parent(self):
        categories, sections = service.parse_catalog('<a href="/catalog/interior/vases/" title="Вазы для цветов"></a><a href="/catalog/interior/" title="Интерьер"></a>')
        self.assertEqual(sections[0]['parent'], categories[0]['source_path'])
        self.assertEqual(sections[0]['name'], 'Вазы для цветов')

    def test_excludes_all_catalog(self):
        self.assertEqual(service.parse_catalog('<a href="/catalog/ves-katalog/" title="Все"></a>'), ([], []))

    def test_excludes_products_services_and_external_links(self):
        links = ['/catalog/c/s/product/', '/catalog/c/product.html', '/compare/', '/catalog/compare/', '/catalog/c/?sort=price', '/catalog/c/#x', 'https://evil.test/catalog/c/', '/catalog/c/s/product.html']
        self.assertEqual(service.parse_catalog(''.join(f'<a href="{url}" title="x"></a>' for url in links)), ([], []))

    def test_normalization(self):
        self.assertEqual(service.normalize_section('  ЁЛКИ\t  зелёные '), 'елки зеленые')

    def test_orphan_rejected(self):
        with self.assertRaises(ValueError):
            service.parse_catalog('<a href="/catalog/c/s/" title="Раздел"></a>')

    def test_suspicious_catalog_rejected(self):
        with self.assertRaises(ValueError):
            service.validate_catalog([], [])
        categories, sections = service.parse_catalog(fixture())
        with self.assertRaises(ValueError):
            service.validate_catalog(categories, sections, 40, 620)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.engine_patch = patch.object(service, 'engine', self.engine)
        self.engine_patch.start()

    def tearDown(self):
        self.db.close()
        self.engine_patch.stop()
        self.engine.dispose()

    def sync(self, html=None):
        with patch.object(service, 'fetch_catalog', return_value=html or fixture()):
            return service.sync_categories()

    def test_repeat_keeps_ids_and_no_duplicates(self):
        self.assertEqual(self.sync()['status'], 'success')
        ids = self.db.query(CatalogCategory.id, CatalogCategory.source_path).all()
        mapping_ids = self.db.query(CatalogSectionMapping.id).all()
        self.sync()
        self.assertEqual(ids, self.db.query(CatalogCategory.id, CatalogCategory.source_path).all())
        self.assertEqual(mapping_ids, self.db.query(CatalogSectionMapping.id).all())
        self.assertEqual(self.db.query(CatalogCategory).count(), 10)

    def test_failure_preserves_dictionary_and_products(self):
        self.sync()
        self.db.add(Product(code='1', name='Товар', section='Раздел 0 0'))
        self.db.commit()
        self.sync()
        before = self.db.query(Product.category_id, Product.category1).one()
        for exc in (TimeoutError('timeout'), OSError('HTTP 503')):
            with patch.object(service, 'fetch_catalog', side_effect=exc):
                result = service.sync_categories()
            self.assertEqual(result['status'], 'failed')
            self.assertIsNotNone(result['last_success_at'])
        self.assertEqual(self.sync('<html>Changed HTML</html>')['status'], 'failed')
        self.assertEqual(self.db.query(CatalogCategory).filter_by(active=True).count(), 10)
        self.assertEqual(before, self.db.query(Product.category_id, Product.category1).one())

    def test_mapping_unknown_and_uncategorized_group(self):
        self.db.add_all([Product(code='1', name='X', section='  РАЗДЕЛ   0 0 '), Product(code='2', name='X', section='Неизвестный')])
        self.db.commit()
        self.sync()
        self.db.expire_all()
        products = self.db.query(Product).order_by(Product.code).all()
        self.assertEqual(products[0].category1, 'Категория 0')
        self.assertIsNone(products[1].category1)
        tree = service.category_tree(self.db)
        self.assertEqual(tree[-1]['name'], 'Без категории')
        self.assertEqual(tree[-1]['subcategories'], [{'name': 'Неизвестный', 'product_count': 1}])
        self.assertTrue(any(s['name'] == '  РАЗДЕЛ   0 0 ' for s in tree[0]['subcategories']))

    def test_no_uncategorized_group_without_products(self):
        self.sync()
        self.assertNotIn('Без категории', [node['name'] for node in service.category_tree(self.db)])

    def test_xml_import_and_reimport(self):
        self.sync()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.xml'
            path.write_text('<Товары><Товар><Код>1</Код><Название>Товар</Название><Раздел>Раздел 0 0</Раздел></Товар></Товары>')
            importer = XMLCatalogImporter()
            importer.import_file(self.db, path, 'test.xml')
            product = self.db.query(Product).one()
            self.assertEqual(product.section, 'Раздел 0 0')
            self.assertEqual(product.category1, 'Категория 0')
            path.write_text(path.read_text().replace('Раздел 0 0', 'Новый раздел'))
            importer.import_file(self.db, path, 'test.xml')
            self.assertEqual(product.section, 'Новый раздел')
            self.assertIsNone(product.category1)
            self.assertEqual(self.db.query(Product).count(), 1)

    def test_category_and_section_union(self):
        self.db.add_all([Product(code=str(i), name='X', section=f'Раздел {i} 0') for i in range(3)])
        self.db.commit()
        self.sync()
        category_id = self.db.query(CatalogCategory.id).filter_by(name='Категория 0').scalar()
        for query in (catalog_product_query, product_query):
            self.assertEqual([p.code for p in query(self.db, {'category': str(category_id)})], ['0'])
            self.assertEqual([p.code for p in query(self.db, {'section': 'Раздел 1 0'})], ['1'])
            self.assertEqual({p.code for p in query(self.db, {'category': str(category_id), 'section': 'Раздел 1 0'})}, {'0', '1'})

    def test_move_updates_existing_product_without_xml(self):
        self.db.add(Product(code='1', name='X', section='Раздел 0 0'))
        self.db.commit()
        self.sync()
        html = fixture().replace('/catalog/c0/s0/', '/catalog/c1/moved/')
        self.sync(html)
        self.assertEqual(self.db.query(Product.category1).scalar(), 'Категория 1')

    def test_ambiguous_name_does_not_guess(self):
        self.db.add(Product(code='1', name='X', section='Раздел 0 0'))
        self.db.commit()
        self.sync(fixture().replace('Раздел 1 0', 'Раздел 0 0'))
        self.assertIsNone(self.db.query(Product.category1).scalar())

    def test_scheduled_attempt_at_most_once_per_day(self):
        self.sync()
        with patch.object(service, 'fetch_catalog') as fetch:
            self.assertEqual(service.sync_categories(scheduled=True)['status'], 'not_due')
            fetch.assert_not_called()

    def test_product_refresh_is_single_update(self):
        self.db.add_all([Product(code=str(i), name='X', section=f'Раздел 0 {i % 10}') for i in range(100)])
        self.db.commit()
        updates = []
        def capture(conn, cursor, statement, params, context, many):
            if statement.startswith('UPDATE products'):
                updates.append(statement)
        event.listen(self.engine, 'before_cursor_execute', capture)
        self.sync()
        self.assertEqual(len(updates), 1)

    def test_api_tree_compatibility_filtering_and_admin_protection(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.routes import router
        from app.db.session import get_db
        app = FastAPI()
        app.include_router(router, prefix="/api")
        def get_test_db():
            with Session(self.engine) as db:
                yield db
        app.dependency_overrides[get_db] = get_test_db
        self.db.add(Product(code="api", name="Товар", section="Раздел 0 0"))
        self.db.commit()
        self.sync()
        with TestClient(app) as client:
            old = client.get("/api/filters?inStockOnly=false").json()
            new = client.get("/api/filters?tree=true&inStockOnly=false").json()
            self.assertEqual(new["filters"], old)
            self.assertIn("section", old)
            self.assertNotIn("section_tree", old)
            category_id = new["section_tree"][0]["id"]
            response = client.get(f"/api/products/search?inStockOnly=false&category={category_id}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["items"][0]["category1"], "Категория 0")
            self.assertEqual(client.post("/api/catalog-categories/sync").status_code, 401)
            self.assertEqual(client.get("/api/catalog-categories/status").status_code, 401)

    def test_transaction_failure_rolls_back_dictionary(self):
        self.sync()
        with patch.object(service, "refresh_products", side_effect=RuntimeError("SQL failed")):
            self.assertEqual(self.sync(fixture().replace("Категория 0", "Renamed"))["status"], "failed")
        self.assertEqual(self.db.query(CatalogCategory.name).filter_by(source_path="/catalog/c0/").scalar(), "Категория 0")
