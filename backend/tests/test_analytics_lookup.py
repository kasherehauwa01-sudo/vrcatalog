"""Analytics lookup contract against a small isolated SQLite catalog."""
from datetime import datetime, timedelta, timezone
import logging
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import routes
from app.core.config import settings
from app.db.session import Base, get_db
from app.models.catalog import CatalogCategory, Price, Product, ProductImage, ProductProperty, Stock
from app.schemas.analytics_lookup import AnalyticsLookupRequest, AnalyticsProductOut
from app.services import analytics_lookup as service


class AnalyticsLookupTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        # SQLite's built-in lower() is ASCII-only. Emulate PostgreSQL Unicode lower
        # for the existing normalized identifier expressions and Russian property aliases.
        @event.listens_for(self.engine, 'connect')
        def unicode_lower(connection, _):
            connection.create_function('lower', 1, lambda value: value.lower() if value is not None else None, deterministic=True)

        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        stamp = datetime(2026, 10, 10, 8, 0, 0, 123456)
        with Session(self.engine) as db:
            db.add(CatalogCategory(id=7, name='Посуда', source_path='/catalog/tableware/'))
            db.add_all([
                Product(id=1, code='001234', article='A-17', name='Товар А',
                        manufacturer=' Прямой производитель ', brand=' Прямой бренд ', material=' Фарфор ',
                        category_id=7, category1=' Посуда ', section=' Тарелки ', updated_at=stamp,
                        properties=[
                            ProductProperty(name='Бренд', value='Не заменять прямой бренд'),
                            ProductProperty(name='Производитель', value='Не заменять производителя'),
                            ProductProperty(name='Материал', value='Не заменять материал'),
                            ProductProperty(name='Категория', value='Не заменять раздел'),
                            ProductProperty(name=' HoReCa ', value=' HORECA '),
                            ProductProperty(name='Unrelated', value='private unrelated data'),
                        ],
                        images=[ProductImage(image_order=1, image_url='https://example.test/private.jpg')],
                        stocks=[Stock(warehouse='MAIN', quantity=3)],
                        prices=[Price(price_type='Розничная', price_value=10)]),
                Product(id=2, code='P-2', article='00017', name='Товар Б',
                        manufacturer=' ', brand=None, section=' ', material=None, updated_at=stamp,
                        properties=[
                            ProductProperty(name=' Производитель ', value=' Фабрика '),
                            ProductProperty(name='brand', value=' Бренд из свойства '),
                            ProductProperty(name=' category ', value=' Раздел из свойства '),
                            ProductProperty(name=' Материал ', value=' Стекло '),
                            ProductProperty(name='HoReCa', value='Нет'),
                            ProductProperty(name='Unrelated', value='private unrelated data'),
                        ]),
                Product(id=3, code='P-3', article='DUP', name='Первый дубль', updated_at=stamp),
                Product(id=4, code='P-4', article=' dup ', name='Второй дубль', updated_at=stamp),
                Product(id=5, code='EMPTY', article=None, name='Без характеристик', updated_at=stamp),
                Product(id=6, code=' AbC ', article='COLLISION-1', name='Код 1', updated_at=stamp),
                Product(id=7, code='abc', article='COLLISION-2', name='Код 2', updated_at=stamp),
            ])
            db.commit()
        self.app = FastAPI()
        self.app.include_router(routes.router, prefix='/api')

        def isolated_db():
            with Session(self.engine) as db:
                yield db

        self.app.dependency_overrides[get_db] = isolated_db
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.token_patch = patch.object(settings, 'internal_api_token', 'test-analytics-token')
        self.token_patch.start()
        self.addCleanup(self.token_patch.stop)
        self.headers = {'Authorization': 'Bearer test-analytics-token'}
        self.statements = []
        event.listen(self.engine, 'before_cursor_execute', lambda *args: self.statements.append(args[2]))

    def lookup(self, items, headers=None):
        return self.client.post('/api/integration/products/analytics/lookup',
                                json={'items': items}, headers=self.headers if headers is None else headers)

    def one(self, identifier):
        response = self.lookup([identifier])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['schema_version'], 1)
        return response.json()['items'][0]

    def test_product_id_has_priority_and_never_falls_back(self):
        item = self.one({'product_id': 1, 'code': 'P-2', 'article': '00017'})
        self.assertEqual((item['matched_by'], item['product']['product_id']), ('product_id', 1))
        self.assertEqual(self.one({'product_id': 9999, 'code': '001234'}),
                         {'request_index': 0, 'status': 'not_found', 'matched_by': None, 'product': None})

    def test_code_and_article_lookup_keep_leading_zeroes_and_case(self):
        for identifier, kind, product_id in (({'code': ' 001234 '}, 'code', 1),
                                             ({'code': ' p-2 '}, 'code', 2),
                                             ({'article': ' a-17 '}, 'article', 1),
                                             ({'article': '00017'}, 'article', 2)):
            with self.subTest(identifier=identifier):
                item = self.one(identifier)
                self.assertEqual(item['status'], 'matched')
                self.assertEqual(item['matched_by'], kind)
                self.assertEqual(item['product']['product_id'], product_id)
        self.assertEqual(self.one({'code': '001234'})['product']['code'], '001234')
        self.assertEqual(self.one({'article': '00017'})['product']['article'], '00017')
        self.assertEqual(self.one({'article': '17'})['status'], 'not_found')

    def test_code_precedes_article_and_missing_code_falls_back(self):
        self.assertEqual(self.one({'code': '001234', 'article': '00017'})['product']['product_id'], 1)
        self.assertEqual(self.one({'code': 'missing', 'article': '00017'})['matched_by'], 'article')
        self.assertEqual(self.one({'code': 'P-3', 'article': 'dup'})['product']['product_id'], 3)

    def test_ambiguous_article_does_not_choose_minimum_id(self):
        self.assertEqual(self.one({'article': ' DUP '}),
                         {'request_index': 0, 'status': 'ambiguous', 'matched_by': None, 'product': None})
        self.assertEqual(len(self.statements), 1)
        old = self.client.post('/api/integration/products/batch-info', headers=self.headers,
                               json={'products': [{'article': ' DUP '}]})
        self.assertEqual(old.status_code, 200, old.text)
        self.assertEqual([item['code'] for item in old.json()['items']], ['P-3'])

    def test_normalized_code_collision_is_ambiguous_even_with_unique_article(self):
        self.assertEqual(self.one({'code': 'ABC', 'article': '00017'})['status'], 'ambiguous')

    def test_missing_product_and_null_characteristics(self):
        self.assertEqual(self.one({'code': 'not-found'})['status'], 'not_found')
        product = self.one({'code': 'EMPTY'})['product']
        for field in ('article', 'manufacturer', 'brand', 'category_id', 'category', 'subcategory', 'legacy_category', 'material'):
            self.assertIsNone(product[field])
        self.assertIs(product['horeca'], False)

    def test_direct_fields_category_levels_and_utc_timestamp(self):
        product = self.one({'code': '001234'})['product']
        self.assertEqual(product, {
            'product_id': 1, 'code': '001234', 'article': 'A-17',
            'manufacturer': 'Прямой производитель', 'brand': 'Прямой бренд', 'material': 'Фарфор',
            'category_id': 7, 'category': 'Посуда', 'subcategory': 'Тарелки', 'legacy_category': 'Тарелки',
            'horeca': True, 'updated_at': '2026-10-10T08:00:00.123456Z',
        })

    def test_fallbacks_match_old_batch_info(self):
        new = self.one({'code': 'P-2'})['product']
        old = self.client.post('/api/integration/products/batch-info', headers=self.headers,
                              json={'products': [{'code': 'P-2'}]}).json()['items'][0]
        for field in ('manufacturer', 'brand', 'material', 'horeca'):
            self.assertEqual(new[field], old[field])
        self.assertEqual(new['manufacturer'], 'Фабрика')
        self.assertEqual(new['brand'], 'Бренд из свойства')
        self.assertEqual(new['material'], 'Стекло')
        self.assertEqual(new['legacy_category'], old['category'])
        self.assertEqual(new['legacy_category'], 'Раздел из свойства')
        self.assertIsNone(new['category'])
        self.assertIsNone(new['subcategory'])
        self.assertIs(new['horeca'], False)

    def test_all_legacy_aliases_whitespace_and_conflict_order(self):
        with Session(self.engine) as db:
            product = db.get(Product, 5)
            product.properties = [
                ProductProperty(name='\tManufacturer\n', value=' Vendor '),
                ProductProperty(name='\u00a0БРЕНД\u00a0', value=' Brand '),
                ProductProperty(name='КАТЕГОРИЯ', value=' Section '),
                ProductProperty(name='MATERIAL', value=' Metal '),
                ProductProperty(name='HoReCa', value='\tHoReCa\u00a0'),
                ProductProperty(name='brand', value='z'),
                ProductProperty(name='brand', value='A'),
                ProductProperty(name='Brand', value='a'),
                ProductProperty(name='brand', value='A'),
                ProductProperty(name='brand', value=' '),
                ProductProperty(name='Производитель', value=None),
                ProductProperty(name='Material', value=''),
            ]
            db.commit()
        new = self.one({'product_id': 5})['product']
        old = self.client.post('/api/integration/products/batch-info', headers=self.headers,
                              json={'products': [{'code': 'EMPTY'}]}).json()['items'][0]
        for field in ('manufacturer', 'brand', 'material', 'horeca'):
            self.assertEqual(new[field], old[field], field)
        self.assertEqual(new['legacy_category'], old['category'])
        self.assertIs(new['horeca'], True)

    def test_no_new_xml_property_code_or_material_alias_rules(self):
        with Session(self.engine) as db:
            db.get(Product, 5).properties = [
                ProductProperty(property_code='PROP_BREND', name='Unrecognized', value='Brand'),
                ProductProperty(property_code='PROP_MATERIAL', name='Материал основной', value='Material'),
                ProductProperty(name='HoReCa', value='true'),
            ]
            db.commit()
        product = self.one({'product_id': 5})['product']
        self.assertIsNone(product['brand'])
        self.assertIsNone(product['material'])
        self.assertIs(product['horeca'], False)

    def test_250_inputs_retain_positions_with_constant_query_count(self):
        inputs = [{'code': '001234'}, {'article': 'dup'}, {'code': 'missing'}, {'product_id': 2}] * 62 + [{'code': '001234'}, {'article': 'dup'}]
        response = self.lookup(inputs)
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()['items']
        self.assertEqual([item['request_index'] for item in items], list(range(250)))
        self.assertEqual([item['status'] for item in items], ['matched', 'ambiguous', 'not_found', 'matched'] * 62 + ['matched', 'ambiguous'])
        self.assertEqual(items[0]['product'], items[4]['product'])
        self.assertEqual(len(self.statements), 3)
        self.statements.clear()
        self.one({'code': '001234'})
        self.assertEqual(len(self.statements), 3)

    def test_250_distinct_products_use_three_queries(self):
        with Session(self.engine) as db:
            db.add_all(Product(code=f'NEW-{index}', name='Товар', article=f'ART-{index}') for index in range(250))
            db.commit()
        self.statements.clear()
        response = self.lookup([{'code': f'NEW-{index}'} for index in range(250)])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(sum(item['status'] == 'matched' for item in response.json()['items']), 250)
        self.assertEqual(len(self.statements), 3)

    def test_candidate_aggregation_is_bounded_for_duplicate_articles(self):
        with Session(self.engine) as db:
            db.add_all(Product(code=f'DUP-{index}', name='Товар', article='dup') for index in range(30))
            db.commit()
            request = AnalyticsLookupRequest(items=[{'article': 'dup'}])
            rows = db.execute(service._matching_query(request.items)).all()
            self.assertEqual(len(rows), 1)
        self.assertEqual(self.one({'article': 'dup'})['status'], 'ambiguous')

    def test_projection_and_selective_properties_never_read_heavy_tables(self):
        with self.assertLogs(service.logger, 'INFO') as logs:
            self.one({'product_id': 1})
        self.assertEqual(len(self.statements), 3)
        sql = '\n'.join(self.statements).lower()
        for table in ('product_images', 'stocks', 'prices', 'service_logs'):
            self.assertNotIn(table, sql)
        for column in ('products.description', 'products.search_text', 'products.quantity', 'products.name'):
            self.assertNotIn(column, sql)
        self.assertTrue(all(statement.lstrip().upper().startswith('SELECT') for statement in self.statements))
        self.assertIn('properties_rows=1', logs.output[0])
        self.assertIn('trim(product_properties.name', sql)
        self.assertIn('product_properties.product_id in', sql)
        self.assertEqual(sql.count('from product_properties'), 1)

    def test_properties_are_read_only_for_matched_products_and_missing_fields(self):
        with self.assertLogs(service.logger, 'INFO') as logs:
            response = self.lookup([{'product_id': 1}, {'product_id': 2}, {'article': 'dup'}])
        self.assertEqual(response.status_code, 200)
        # One HoReCa row for the direct product, four fallback rows for the empty one.
        self.assertIn('properties_rows=5', logs.output[0])
        self.assertEqual(len(self.statements), 3)

    def test_validation_rejects_bad_input_before_sql(self):
        invalid = [[], [{}], [{'code': ' '}], [{'product_id': 0}], [{'product_id': True}],
                   [{'product_id': '1'}], [{'product_id': 1.5}], [{'code': 123}], [{'article': False}],
                   [{'code': 'x' * 129}], [{'article': 'x' * 256}], [{'code': 'x', 'fields': []}],
                   [{'code': '001234'}] * 251]
        for items in invalid:
            with self.subTest(items_type=type(items).__name__, count=len(items)):
                response = self.lookup(items)
                self.assertEqual(response.status_code, 422, response.text)
        for payload in ({}, {'items': None}, {'items': [{'code': 'x'}], 'fields': ['code']}):
            self.assertEqual(self.client.post('/api/integration/products/analytics/lookup', json=payload,
                                             headers=self.headers).status_code, 422)
        self.assertEqual(self.statements, [])

    def test_fallback_selection_across_streamed_property_chunks(self):
        with Session(self.engine) as db:
            db.get(Product, 5).properties = [
                ProductProperty(name=' brand ', value=f'value-{index:03d}') for index in range(260)
            ] + [ProductProperty(name='brand', value='first')]
            db.commit()
        self.statements.clear()
        with self.assertLogs(service.logger, 'INFO') as logs:
            product = self.one({'product_id': 5})['product']
        # The best value is in the second fetch chunk (raw name SQL ordering).
        self.assertEqual(product['brand'], 'first')
        self.assertIn('properties_rows=261', logs.output[0])
        self.assertEqual(len(self.statements), 3)

    def test_matched_product_disappearing_before_projection_is_not_found(self):
        with Session(self.engine) as db:
            execute = db.execute
            calls = 0

            def without_projected_row(statement, *args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    statement = statement.where(Product.id < 0)
                return execute(statement, *args, **kwargs)

            with patch.object(db, 'execute', side_effect=without_projected_row):
                result = service.analytics_product_lookup(db, AnalyticsLookupRequest(items=[{'product_id': 1}]).items)
        self.assertEqual(result.items[0].status, 'not_found')
        self.assertIsNone(result.items[0].product)
        self.assertIsNone(result.items[0].matched_by)
        self.assertEqual(calls, 2)

    def test_authorization_is_required_and_empty_setting_fails_closed(self):
        for headers, expected in (({}, 401), ({'Authorization': 'Bearer wrong'}, 403),
                                   ({'Authorization': 'Basic value'}, 403),
                                   ({'X-Internal-Token': 'test-analytics-token'}, 401)):
            with self.subTest(headers=list(headers)):
                self.assertEqual(self.lookup([{'code': '001234'}], headers).status_code, expected)
        with patch.object(settings, 'internal_api_token', ''):
            self.assertEqual(self.lookup([{'code': '001234'}]).status_code, 403)
        self.assertEqual(self.statements, [])

    def test_failure_is_sanitized_and_logs_only_metrics(self):
        for failing_query in (1, 2, 3):
            with self.subTest(failing_query=failing_query):
                count = 0
                def fail(*args):
                    nonlocal count
                    count += 1
                    if count == failing_query:
                        raise SQLAlchemyError('SELECT secret_token FROM private https://user:password@example.test')
                event.listen(self.engine, 'before_cursor_execute', fail)
                try:
                    with self.assertLogs(service.logger, 'INFO') as logs:
                        response = self.lookup([{'code': '001234'}])
                    self.assertEqual(response.status_code, 500)
                    self.assertEqual(response.json(), {'detail': 'Не удалось получить характеристики товаров'})
                    self.assertEqual(len(logs.records), 1)
                    self.assertIn('status=error', logs.output[0])
                    self.assertIn('total_ms=', logs.output[0])
                    self.assertIsNone(logs.records[0].exc_info)
                    for secret in ('secret_token', 'SELECT', 'password', '001234', 'test-analytics-token'):
                        self.assertNotIn(secret, response.text + logs.output[0])
                finally:
                    event.remove(self.engine, 'before_cursor_execute', fail)

    def test_metrics_do_not_accumulate_between_requests(self):
        with self.assertLogs(service.logger, 'INFO') as logs:
            self.lookup([{'code': '001234'}, {'article': 'dup'}, {'code': 'missing'}])
            self.lookup([{'code': 'missing'}])
        self.assertEqual(len(logs.records), 2)
        self.assertIn('requested=3 matched=1 not_found=1 ambiguous=1', logs.output[0])
        self.assertIn('requested=1 matched=0 not_found=1 ambiguous=0', logs.output[1])
        self.assertIn('properties_rows=0', logs.output[1])
        for record in logs.records:
            self.assertEqual(record.levelno, logging.INFO)
            self.assertEqual(len(record.getMessage().splitlines()), 1)

    def test_utc_serialization_accepts_timezone_aware_dates(self):
        data = self.one({'product_id': 1})['product']
        data['updated_at'] = datetime(2026, 10, 10, 11, 0, 0, 123456, tzinfo=timezone(timedelta(hours=3)))
        self.assertEqual(AnalyticsProductOut(**data).model_dump(mode='json')['updated_at'],
                         '2026-10-10T08:00:00.123456Z')

    def test_old_category_map_and_search_contracts_still_work(self):
        category = self.client.post('/api/integration/products/category-map', headers=self.headers,
                                    json={'products': [{'code': '001234'}, {'code': 'P-2'}]})
        self.assertEqual(category.status_code, 200, category.text)
        self.assertEqual([row['category'] for row in category.json()['items']], ['Тарелки', None])
        search = self.client.post('/api/integration/products/search', headers=self.headers,
                                  json={'search': '001234', 'page_size': 1})
        self.assertEqual(search.status_code, 200, search.text)
        self.assertEqual(search.json()['items'][0]['category_id'], 'Тарелки')
        self.assertIn('properties', search.json()['items'][0])
        self.assertIn('image_url', search.json()['items'][0])


if __name__ == '__main__':
    unittest.main()
