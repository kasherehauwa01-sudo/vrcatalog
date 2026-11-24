import unittest
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
from app.models.catalog import Product
from app.services.catalog import catalog_product_query


class CatalogCodeBatchTests(unittest.TestCase):
    def setUp(self):
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

    def test_long_code_export_keeps_admin_protection_and_forwards_same_filter(self):
        from app.api import routes
        from app.core.admin_auth import require_heavy_admin
        payload = {'code': ' '.join(self.codes)}
        with patch.object(routes.export_executor, 'submit') as submit, patch.object(routes, 'cleanup_export_jobs'), patch.dict(routes.export_jobs, {}, clear=True):
            self.assertEqual(self.client.post('/api/exports/xlsx', json=payload).status_code, 401)
            submit.assert_not_called()
            self.app.dependency_overrides[require_heavy_admin] = lambda: object()
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
            self.assertEqual(self.client.post('/api/exports/xlsx', json={'product_ids': selected_ids}).status_code, 401)
            self.app.dependency_overrides[require_heavy_admin] = lambda: object()
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
