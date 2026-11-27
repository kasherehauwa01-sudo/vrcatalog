import unittest
from base64 import b64decode
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import router
from app.db.session import Base, get_db
from app.models.catalog import Price, Product, ProductImage, ProductProperty, Stock, WarehouseSetting
from app.services.catalog import catalog_product_query


class CatalogCodeBatchTests(unittest.TestCase):
    def setUp(self):
        from app.core.admin_auth import _operations
        _operations.clear()
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.codes = [f'CODE-{index:06d}' for index in range(300)]
        with Session(self.engine) as db:
            db.add_all(Product(code=code, name=code, quantity=5) for code in self.codes)
            db.add_all(Product(code=code, name=code, quantity=5) for code in ('XCODE-000001', 'CODE-000001-extra', '0001', '1', 'A%B', 'AXXB', 'A_B', 'ACB'))
            db.commit()
        self.sql = []
        event.listen(self.engine, 'before_cursor_execute', lambda conn, cursor, statement, params, context, many: self.sql.append(statement))
        app = FastAPI()
        app.include_router(router, prefix='/api')
        def database():
            with Session(self.engine) as db:
                yield db
        app.dependency_overrides[get_db] = database
        self.app = app
        self.client = TestClient(app)
        self.query = {'inStockOnly': 'false', 'excludeYyy': 'false', 'pageSize': 100, 'sort': 'code'}

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_300_codes_post_exact_results_and_pagination(self):
        code = ' \n'.join(self.codes)
        self.assertGreater(len(code), 2000)
        found = []
        for page in (1, 2, 3):
            response = self.client.post('/api/products/search', params={**self.query, 'page': page}, json={'code': code})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['pagination']['totalItems'], 300)
            self.assertEqual(response.json()['pagination']['totalPages'], 3)
            found.extend(item['code'] for item in response.json()['items'])
        self.assertEqual(found, self.codes)
        product_queries = [sql.lower() for sql in self.sql if 'FROM products' in sql]
        self.assertTrue(product_queries)
        self.assertTrue(all('lower(trim(products.code)) in' in sql for sql in product_queries))
        self.assertTrue(all(' like ' not in sql for sql in product_queries))

    def test_get_and_post_compatibility_with_other_filters(self):
        params = {**self.query, 'name': '000001'}
        code = 'CODE-000001 CODE-000002'
        get = self.client.get('/api/products/search', params={**params, 'code': code})
        post = self.client.post('/api/products/search', params=params, json={'code': code})
        self.assertEqual(get.status_code, 200)
        self.assertEqual(get.json(), post.json())
        self.assertEqual([item['code'] for item in get.json()['items']], ['CODE-000001'])

    def test_leading_zeroes_case_duplicates_and_literal_wildcards(self):
        with Session(self.engine) as db:
            for value, expected in (
                ('0001 0001', {'0001'}),
                ('code-000001,\tCODE-000002\nCODE-000002', {'CODE-000001', 'CODE-000002'}),
                ('A%B A_B', {'A%B', 'A_B'}),
                ('missing othermissing', set()),
            ):
                with self.subTest(value=value):
                    query = catalog_product_query(db, {'code': value}, eager_load=False)
                    self.assertEqual({row.code for row in query}, expected)
            self.assertGreater(catalog_product_query(db, {'code': 'CODE-'}, eager_load=False).count(), 300)

    def test_invalid_body_and_conflicting_sources_rejected_before_sql(self):
        for payload in ({'code': ''}, {'code': ' '}, {'code': 'x' * 129}, {'code': 'a ' * 1001}, {'code': ['a']}, {'code': 'a', 'unknown': 1}):
            self.assertEqual(self.client.post('/api/products/search', params=self.query, json=payload).status_code, 422)
        self.assertEqual(self.client.post('/api/products/search?code=a', json={'code': 'b'}).status_code, 422)
        self.assertEqual(self.sql, [])

    def test_photo_report_accepts_same_long_code_body(self):
        with patch('app.api.routes.photo_report_page', return_value={'items': [], 'page': 1, 'page_size': 50, 'total_items': 0, 'total_pages': 0}) as report:
            response = self.client.post('/api/reports/photos', params=self.query, json={'code': ' '.join(self.codes)})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(report.call_args.args[1]['code'], ' '.join(self.codes))

    def test_long_code_export_is_public_and_forwards_same_filter(self):
        from app.api import routes
        from app.core.admin_auth import require_heavy_admin
        payload = {'code': ' '.join(self.codes)}
        with patch.object(routes.export_executor, 'submit') as submit, patch.object(routes, 'cleanup_export_jobs'), patch.dict(routes.export_jobs, {}, clear=True):
            response = self.client.post('/api/exports/xlsx', params={'inStockOnly': 'false', 'column': 'code'}, json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            submit.assert_called_once()
            self.assertEqual(submit.call_args.args[2]['code'], payload['code'])
            self.assertEqual(submit.call_args.args[3], ['code'])

    def test_xlsx_contains_checked_ids_or_all_filtered_rows_without_pagination(self):
        from app.api import routes
        from app.core.admin_auth import require_heavy_admin

        selected_codes = {self.codes[2], self.codes[7]}
        with Session(self.engine) as db:
            selected_ids = [row.id for row in db.query(Product.id).filter(Product.code.in_(selected_codes))]
        with (
            patch.object(routes.export_executor, 'submit', side_effect=lambda task, *args: task(*args)),
            patch.object(routes, 'SessionLocal', side_effect=lambda: Session(self.engine)),
            patch.dict(routes.export_jobs, {}, clear=True),
        ):
            for params, body, expected in (
                ({'column': 'code'}, {'product_ids': selected_ids + selected_ids}, selected_codes),
                ({'column': 'code'}, {'product_ids': [2147483647]}, set()),
                ({**self.query, 'column': 'code', 'page': 2, 'pageSize': 1},
                 {'code': ' '.join(self.codes[:3])}, set(self.codes[:3])),
            ):
                with self.subTest(params=params, body=body):
                    response = self.client.post('/api/exports/xlsx', params=params, json=body)
                    self.assertEqual(response.status_code, 200, response.text)
                    job_id = response.json()['job_id']
                    status = self.client.get(f'/api/exports/xlsx/{job_id}').json()
                    self.assertEqual(status['status'], 'ready', status)
                    self.addCleanup(Path(routes.export_jobs[job_id]['path']).unlink, missing_ok=True)
                    self.assertEqual(status['total'], len(expected))
                    download = self.client.get(f'/api/exports/xlsx/{job_id}/download')
                    self.assertEqual(download.status_code, 200, download.text if not download.is_success else '')
                    workbook = load_workbook(BytesIO(download.content), read_only=True)
                    try:
                        rows = list(workbook.active.values)[1:]
                        self.assertCountEqual([row[0] for row in rows], expected)
                    finally:
                        workbook.close()

    def test_zip_export_selection_download_and_single_price_validation(self):
        from zipfile import ZipFile
        from app.api import routes
        from app.core.admin_auth import require_heavy_admin

        self.app.dependency_overrides[require_heavy_admin] = lambda: object()
        with patch.object(routes.export_executor, 'submit') as submit:
            response = self.client.post('/api/exports/xlsx', params=[('promotion', 'true'), ('column', 'code')])
            self.assertEqual(response.status_code, 422)
            submit.assert_not_called()
        with (
            patch.object(routes.export_executor, 'submit', side_effect=lambda task, *args: task(*args)),
            patch.object(routes, 'SessionLocal', side_effect=lambda: Session(self.engine)),
            patch.dict(routes.export_jobs, {}, clear=True),
        ):
            response = self.client.post('/api/exports/xlsx', params={
                'zip_categories': 'true', 'group_categories': 'true', 'column': 'code',
            }, json={'product_ids': [1, 2]})
            self.assertEqual(response.status_code, 200, response.text)
            job_id = response.json()['job_id']
            status = self.client.get(f'/api/exports/xlsx/{job_id}').json()
            self.assertEqual(status['status'], 'ready', status)
            self.addCleanup(Path(routes.export_jobs[job_id]['path']).unlink, missing_ok=True)
            self.assertEqual(status['filename'], 'products.zip')
            self.assertEqual(status['media_type'], 'application/zip')
            self.assertEqual((status['total'], status['processed']), (2, 2))
            download = self.client.get(f'/api/exports/xlsx/{job_id}/download')
            self.assertEqual(download.headers['content-type'], 'application/zip')
            chunk = self.client.get(f'/api/exports/xlsx/{job_id}/chunk?offset=0')
            self.assertEqual(chunk.content, download.content)
            with ZipFile(BytesIO(download.content)) as archive:
                self.assertEqual(archive.namelist(), ['Без подкатегории.xlsx'])
                book = load_workbook(BytesIO(archive.read(archive.namelist()[0])))
                self.assertEqual([row[0].value for row in book.active][3:], self.codes[:2])
                book.close()

    def test_public_export_keeps_rate_limit_and_validates_new_options(self):
        from app.api import routes
        from app.core.admin_auth import _operations
        with patch.object(routes.export_executor, 'submit') as submit, patch.dict(routes.export_jobs, {}, clear=True):
            for params in ({'promotion': True}, {'promotion': True, 'promotion_type': 'Другое'},
                           {'adjustment': True}, {'adjustment': True, 'adjustment_percent': 'nan'}):
                response = self.client.post('/api/exports/xlsx', params={**params, 'column': 'price:ЦенаОптовая'})
                self.assertEqual(response.status_code, 422, response.text)
            submit.assert_not_called()
            _operations.clear()
            for _ in range(10):
                self.assertEqual(self.client.post('/api/exports/xlsx', params={'column': 'code'}).status_code, 200)
            self.assertEqual(self.client.post('/api/exports/xlsx', params={'column': 'code'}).status_code, 429)
            self.assertEqual(submit.call_count, 10)

    def test_invalid_xlsx_selection_does_not_start_an_export_job(self):
        from app.api import routes
        from app.core.admin_auth import require_heavy_admin

        self.app.dependency_overrides[require_heavy_admin] = lambda: object()
        with patch.object(routes.export_executor, 'submit') as submit:
            for body in ({'product_ids': []}, {'product_ids': [0]}, {'product_ids': [True]},
                         {'product_ids': [1], 'code': 'CODE-000001'}):
                with self.subTest(body=body):
                    response = self.client.post('/api/exports/xlsx', json=body)
                    self.assertEqual(response.status_code, 422, response.text)
            submit.assert_not_called()

    def test_filter_options_query_only_the_requested_field_and_preserve_scope(self):
        with Session(self.engine) as db:
            for index, brand in enumerate(("Амфора", "Другой")):
                product = db.query(Product).filter_by(code=self.codes[index]).one()
                product.brand = brand
                product.section = "Посуда"
                product.properties.append(ProductProperty(name="Коллекция", value=f"Серия {index}"))
            db.commit()

        self.sql.clear()
        response = self.client.get('/api/filters', params={**self.query, 'filterKey': 'brand'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'brand': ['Амфора', 'Другой']})
        self.assertEqual(len(self.sql), 1)
        self.assertNotIn('product_properties', self.sql[0])

        self.sql.clear()
        response = self.client.get('/api/filters', params={
            **self.query, 'filterKey': 'property:Коллекция', 'brand': 'Амфора',
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'property:Коллекция': ['Серия 0']})
        self.assertEqual(len(self.sql), 1)
        sections = self.client.get('/api/filters/sections')
        self.assertEqual(sections.status_code, 200, sections.text)
        combined = self.client.get('/api/filters', params={**self.query, 'tree': 'true'})
        self.assertEqual(combined.status_code, 200, combined.text)
        self.assertEqual(combined.json()['section_tree'], sections.json())
        self.assertEqual(combined.json()['filters']['brand'], ['Амфора', 'Другой'])

    def test_xlsx_applies_markup_and_warehouse_limits_to_selected_or_filtered_products(self):
        from app.api import routes

        with Session(self.engine) as db:
            db.add(WarehouseSetting(code='AVIATORS', name='Авиаторов'))
            products = db.query(Product).filter(Product.code.in_(self.codes[:8])).order_by(Product.code).all()
            for product, (purchase, sale, balance) in zip(products, [
                (100, 120, 5), (0.2, 0.23, 3), (100, 120, 0), (100, 130, 6),
                (0, 130, 1), (None, 130, 1), (100, 130, None), (100, 130, 0.5),
            ], strict=True):
                if purchase is not None:
                    product.prices.append(Price(price_type='Закупочная', price_value=purchase))
                product.prices.append(Price(price_type='Оптовая', price_value=sale))
                product.stocks.append(Stock(warehouse='OTHER', quantity=99))
                if balance is not None:
                    product.stocks.append(Stock(warehouse='AVIATORS', quantity=balance))
            # Explicit XML prices win over labels, even when the label is newer.
            products[0].prices.extend([
                Price(price_type='ЦенаЗакупочная', price_value=200),
                Price(price_type='ЦенаЗакупочная', price_value=100),
                Price(price_type='Закупочная', price_value=300),
                Price(price_type='ЦенаОптовая', price_value=110),
                Price(price_type='ЦенаОптовая', price_value=120),
                Price(price_type='Оптовая', price_value=90),
            ])
            products[0].stocks[1].quantity = 2
            products[0].stocks.append(Stock(warehouse='AVIATORS', quantity=3))
            for product in products:
                product.images.append(ProductImage(image_order=1, image_url='https://example.test/photo.png'))
            ids = [product.id for product in products]
            db.commit()

        base_params = {
            'inStockOnly': 'false', 'column': ['photo', 'code', 'purchase_price', 'price:ЦенаОптовая', 'stock:AVIATORS'],
            'markup_percent': '15', 'stock_warehouse': 'AVIATORS', 'stock_limit': '5',
        }
        thumbnail = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        with (
            patch.object(routes, 'download_export_images', side_effect=lambda urls, *args, **kwargs: dict.fromkeys(urls, thumbnail)),
            patch.object(routes.export_executor, 'submit', side_effect=lambda task, *args: task(*args)),
            patch.object(routes, 'SessionLocal', side_effect=lambda: Session(self.engine)),
            patch.dict(routes.export_jobs, {}, clear=True),
        ):
            for body, comparison, expected in (
                ({'product_ids': ids}, 'less', (None, self.codes[0], 100, 120, 5)),
                ({'code': ' '.join(self.codes[:8])}, 'less', (None, self.codes[0], 100, 120, 5)),
                ({'product_ids': ids}, 'more', (None, self.codes[3], 100, 130, 6)),
            ):
                with self.subTest(body=body, comparison=comparison):
                    response = self.client.post('/api/exports/xlsx', params={
                        **base_params, 'stock_comparison': comparison,
                    }, json=body)
                    self.assertEqual(response.status_code, 200, response.text)
                    job_id = response.json()['job_id']
                    job = routes.export_jobs[job_id]
                    self.assertEqual(job['status'], 'ready', job)
                    self.addCleanup(Path(job['path']).unlink, missing_ok=True)
                    self.assertEqual((job['total'], job['processed']), (1, 1))
                    with Path(job['path']).open('rb') as file:
                        workbook = load_workbook(file)
                        try:
                            self.assertEqual(list(workbook.active.values), [
                                ('Фото', 'Код', 'Закупочная цена', 'ЦенаОптовая', 'Авиаторов'), expected,
                            ])
                            self.assertEqual(len(workbook.active._images), 1)
                            self.assertEqual(workbook.active._images[0].anchor.pic.nvPicPr.cNvPr.descr, 'Фото товара')
                        finally:
                            workbook.close()

    def test_legacy_xlsx_keeps_price_aliases_and_sums_duplicate_warehouse_rows(self):
        from app.api import routes

        with Session(self.engine) as db:
            product = db.query(Product).filter_by(code=self.codes[0]).one()
            product.prices.extend([
                Price(price_type='Закупочная', price_value=80),
                Price(price_type='Оптовая', price_value=120),
            ])
            product.stocks.extend([Stock(warehouse='AVIATORS', quantity=2), Stock(warehouse='AVIATORS', quantity=3)])
            db.add(WarehouseSetting(code='AVIATORS', name='Авиаторов'))
            db.commit()
            book = routes.build_export_workbook(db, {'id': product.id}, [
                'code', 'purchase_price', 'price:ЦенаОптовая', 'stock:AVIATORS',
            ])
            try:
                self.assertEqual(list(book.active.values), [
                    ('Код', 'Закупочная цена', 'ЦенаОптовая', 'Авиаторов'),
                    (self.codes[0], 80, 120, 5),
                ])
            finally:
                book.close()

    def test_xlsx_rejects_incomplete_stock_filter_and_requires_one_sale_price_for_markup(self):
        from app.api import routes

        with patch.object(routes.export_executor, 'submit') as submit:
            for params in (
                {'column': 'purchase_price', 'markup_percent': 0},
                {'column': ['price:ЦенаОптовая', 'price:ЦенаРозничная'], 'markup_percent': 10},
                {'stock_warehouse': 'AVIATORS', 'stock_comparison': 'less'},
                {'stock_warehouse': 'AVIATORS', 'stock_comparison': 'less', 'stock_limit': -1},
            ):
                with self.subTest(params=params):
                    response = self.client.post('/api/exports/xlsx', params=params)
                    self.assertEqual(response.status_code, 422, response.text)
            submit.assert_not_called()
