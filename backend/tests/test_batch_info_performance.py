"""Small, in-memory checks for batch diagnostics; no external services."""
import itertools
import logging
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.catalog import Price, Product, ProductImage, ProductProperty, Stock
from app.services import catalog


STAGES = (
    'search', 'matching', 'properties_sql', 'properties_processing',
    'images_sql', 'images_processing', 'stocks_sql', 'stocks_processing',
    'prices_sql', 'prices_processing',
)


class BatchInfoPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.db.add_all([
            Product(id=1, code='PRIVATE-CODE', article='PRIVATE-ARTICLE',
                    name='Private product', manager='Private person',
                    properties=[
                        ProductProperty(name=' Secret ', value=' Value '),
                        ProductProperty(name='Secret', value='Value'),
                        ProductProperty(name=' ', value='Skip'),
                    ],
                    images=[ProductImage(image_order=1, image_url='https://user:password@example.test/image'),
                            ProductImage(image_order=2, image_url='private-later-image')],
                    stocks=[Stock(warehouse='private-warehouse', quantity=2),
                            Stock(warehouse='private-warehouse', quantity=3)],
                    prices=[Price(price_type=' private-price ', price_value=10),
                            Price(price_type=' ', price_value=20)]),
            Product(id=2, code='OTHER-CODE', article='OTHER-ARTICLE', name='Other product'),
            Product(id=3, code='UNMATCHED-CODE', article='OTHER-ARTICLE', name='Duplicate article'),
        ])
        self.db.commit()
        self.request = [
            SimpleNamespace(code='private-code', article='OTHER-ARTICLE'),
            SimpleNamespace(code='missing-code', article='other-article'),
            SimpleNamespace(code='PRIVATE-CODE', article=None),
            SimpleNamespace(code='missing-code', article=None),
        ]

    def metrics(self, captured):
        self.assertEqual(len(captured.records), 1)
        record = captured.records[0]
        self.assertEqual(record.levelno, logging.INFO)
        self.assertIsNone(record.exc_info)
        self.assertIsNone(record.stack_info)
        message = record.getMessage()
        self.assertEqual(len(message.splitlines()), 1)
        prefix, *fields = message.split()
        self.assertEqual(prefix, 'batch_info_perf')
        values = dict(field.split('=', 1) for field in fields)
        expected = {'status', 'requested', 'matched', 'candidates', 'total_ms',
                    'properties_rows', 'images_rows', 'stocks_rows', 'prices_rows'}
        expected.update(stage + '_ms' for stage in STAGES)
        self.assertEqual(set(values), expected)
        for key, value in values.items():
            if key != 'status':
                self.assertGreaterEqual(float(value), 0)
        return values

    def test_stage_durations_counts_output_and_five_queries(self):
        statements = []
        event.listen(self.engine, 'before_cursor_execute', lambda *args: statements.append(args[2]))
        ticks = [value / 1000 for value in (0, 1, 3, 6, 10, 15, 21, 28, 36, 45, 55, 66)]
        with patch.object(catalog.time, 'perf_counter', side_effect=ticks), self.assertLogs(catalog.logger, 'INFO') as logs:
            products, details = catalog.integration_batch_product_info(self.db, self.request)
        metrics = self.metrics(logs)
        self.assertEqual(metrics['status'], 'ok')
        self.assertEqual([metrics[key] for key in ('requested', 'candidates', 'matched')], ['4', '3', '2'])
        self.assertEqual([metrics[key + '_rows'] for key in ('properties', 'images', 'stocks', 'prices')], ['3', '1', '1', '2'])
        for index, stage in enumerate(STAGES, 1):
            self.assertEqual(float(metrics[stage + '_ms']), index)
        self.assertEqual(float(metrics['total_ms']), 66)
        self.assertEqual(len(statements), 5)
        self.assertTrue(all(statement.lstrip().upper().startswith('SELECT') for statement in statements))
        self.assertEqual([product.id for product in products], [1, 2])
        self.assertEqual(details, {
            1: {'properties': [{'name': 'Secret', 'value': 'Value'}],
                'image_url': 'https://user:password@example.test/image',
                'stocks': [{'warehouse': 'private-warehouse', 'quantity': 5}],
                'prices': [{'name': 'private-price', 'value': 10, 'currency': 'RUB'}]},
            2: {'properties': [], 'image_url': None, 'stocks': [], 'prices': []},
        })
        for secret in ('PRIVATE', 'Private', 'Secret', 'Value', 'password', 'example.test', 'private-warehouse'):
            self.assertNotIn(secret, logs.output[0])

    def test_no_matches_logs_once_and_resets_metrics_between_requests(self):
        with self.assertLogs(catalog.logger, 'INFO'):
            catalog.integration_batch_product_info(self.db, self.request)
        statements = []
        event.listen(self.engine, 'before_cursor_execute', lambda *args: statements.append(args[2]))
        with self.assertLogs(catalog.logger, 'INFO') as logs:
            result = catalog.integration_batch_product_info(
                self.db, [SimpleNamespace(code='not-found', article=None)])
        self.assertEqual(result, ([], {}))
        metrics = self.metrics(logs)
        self.assertEqual(metrics['status'], 'ok')
        self.assertEqual(metrics['requested'], '1')
        for key in ('candidates', 'matched', 'properties_rows', 'images_rows', 'stocks_rows', 'prices_rows'):
            self.assertEqual(metrics[key], '0')
        for stage in STAGES[2:]:
            self.assertEqual(float(metrics[stage + '_ms']), 0)
        self.assertEqual(len(statements), 1)

    def test_each_query_failure_logs_total_without_exception_data_and_reraises(self):
        for failing_query in range(1, 6):
            with self.subTest(failing_query=failing_query):
                error = RuntimeError('PRIVATE-CODE PRIVATE-ARTICLE token=secret https://user:password@example.test\nprivate person')
                count = 0

                def fail(*args):
                    nonlocal count
                    count += 1
                    if count == failing_query:
                        raise error

                event.listen(self.engine, 'before_cursor_execute', fail)
                try:
                    with patch.object(catalog.time, 'perf_counter', side_effect=itertools.count(0, 0.001)), self.assertLogs(catalog.logger, 'INFO') as logs:
                        with self.assertRaises(RuntimeError) as raised:
                            catalog.integration_batch_product_info(self.db, self.request)
                    self.assertIs(raised.exception, error)
                    metrics = self.metrics(logs)
                    self.assertEqual(metrics['status'], 'error')
                    self.assertGreater(float(metrics['total_ms']), 0)
                    self.assertEqual(count, failing_query)
                    for secret in ('PRIVATE', 'token', 'secret', 'password', 'example.test', 'private person', 'Traceback'):
                        self.assertNotIn(secret, logs.output[0])
                finally:
                    event.remove(self.engine, 'before_cursor_execute', fail)
                    self.db.rollback()

    def test_processing_failure_is_logged_without_changing_exception(self):
        # Raise from the original matching logic, after the product SELECT.
        with patch.object(self.db, 'query') as query:
            query.return_value.filter.return_value.order_by.return_value.all.return_value = [
                SimpleNamespace(code=None, article=None, id=1)]
            with self.assertLogs(catalog.logger, 'INFO') as logs:
                with self.assertRaises(AttributeError):
                    catalog.integration_batch_product_info(self.db, self.request)
        self.assertEqual(self.metrics(logs)['status'], 'error')

    def test_info_reaches_stderr_with_existing_backend_logging_configuration(self):
        # Execute only main.py's logging setup: importing the app also starts DB setup.
        script = '''
import ast
import logging
import logging.config
from pathlib import Path
from unittest.mock import Mock
import uvicorn.config
from app.services.catalog import integration_batch_product_info
logging.config.dictConfig(uvicorn.config.LOGGING_CONFIG)
module = ast.parse(Path('app/main.py').read_text())
setup = [node for node in module.body if isinstance(node, ast.Expr)
         and isinstance(node.value, ast.Call)
         and ast.unparse(node.value.func) == 'logging.basicConfig']
assert len(setup) == 1
exec(compile(ast.Module(body=setup, type_ignores=[]), 'logging_setup', 'exec'))
db = Mock()
db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
integration_batch_product_info(db, [])
'''
        result = subprocess.run(
            [sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, 'DATABASE_URL': 'sqlite://'}, capture_output=True, text=True, check=True,
        )
        lines = [line for line in result.stderr.splitlines() if 'batch_info_perf' in line]
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith('INFO:app.services.catalog:batch_info_perf status=ok'))


if __name__ == '__main__':
    unittest.main()
