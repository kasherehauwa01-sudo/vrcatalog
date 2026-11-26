import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch

import xlrd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.catalog import MailSetting, NotificationEmailHistory, Product, ProductProperty, Stock, UnneededFolderSnapshot, WarehouseSetting
from app.services import unneeded_folder as service
from app.services.catalog import folder_paths
from app.schemas.catalog import ScenarioSettingIn
from app.api.routes import update_unneeded_folder_settings
from fastapi import HTTPException


class UnneededFolderTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add(MailSetting())
        self.setting = service.get_setting(self.db)
        self.setting.recipients_json = '["one@example.test", "two@example.test"]'
        self.add('001', 'Исходный', 'НЕНУЖНОЕ|Исходный')
        service.set_enabled(self.db, self.setting, True)
        self.db.commit()
        self.now = datetime(2026, 11, 23, 22, 30, tzinfo=ZoneInfo('Europe/Moscow'))

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def add(self, code, name, path, manager='Менеджер', stock=0, warehouse=service.WAREHOUSE_NAME):
        product = Product(code=code, name=name, manager=manager,
                          properties=[ProductProperty(name='ПолныйПуть', value=path)],
                          stocks=[] if stock is None else [Stock(warehouse=warehouse, quantity=stock)])
        self.db.add(product)
        self.db.flush()
        return product

    def test_baseline_no_mail_and_daily_aggregate(self):
        self.assertEqual(self.setting.send_time, '22:30')
        self.assertEqual(service.run_due(self.db, self.now), 'empty')
        self.db.add(WarehouseSetting(code='AVIATORS', name='Авиаторов Зал+Склад'))
        new_product = self.add('0002', '<Новый>', 'Каталог|НЕНУЖНОЕ|Дочерняя|<Новый>')
        new_product.stocks.extend([
            Stock(warehouse='AVIATORS', quantity=0),
            Stock(warehouse='Авиаторов Зал+Склад', quantity=0),
            Stock(warehouse='OTHER', quantity=99),
        ])
        self.add('0003', 'Третий', 'НЕНУЖНОЕ|Третий').stocks.append(
            Stock(warehouse='OTHER', quantity=5)
        )
        self.db.commit()
        with patch.object(service, 'send_email') as send:
            self.assertEqual(service.run_due(self.db, self.now), 'skipped')
            self.assertEqual(service.run_due(self.db, self.now.replace(day=24)), 'sent')
            send.assert_called_once()
            args = send.call_args
            self.assertEqual(args.args[1], ['one@example.test', 'two@example.test'])
            self.assertIn('&lt;Новый&gt;', args.args[3])
            self.assertIn('<th>Остаток: Авиаторов Зал+Склад</th>', args.args[3])
            self.assertIn('<td>0002</td><td>&lt;Новый&gt;</td><td>Менеджер</td><td>0</td>', args.args[3])
            self.assertIn('<td>0003</td><td>Третий</td><td>Менеджер</td><td>0</td>', args.args[3])
            self.assertNotIn('Исходный', args.args[3])
            data, filename, mime = args.kwargs['extra_attachments'][0]
            self.assertTrue(filename.endswith('.xls'))
            self.assertEqual(mime, 'vnd.ms-excel')
            sheet = xlrd.open_workbook(file_contents=data).sheet_by_index(0)
            self.assertEqual(sheet.ncols, 1)
            self.assertEqual(sheet.col_values(0), ['', '0002', '0003'])
            self.assertEqual(service.run_due(self.db, self.now.replace(day=25)), 'empty')
        self.assertEqual(self.db.query(NotificationEmailHistory).one().body_html, args.args[3])

    def test_error_retains_products_for_next_day_without_same_day_duplicate(self):
        self.add('002', 'Новый', 'НЕНУЖНОЕ|Новый')
        self.db.commit()
        with patch.object(service, 'send_email', side_effect=RuntimeError('secret password')):
            self.assertEqual(service.run_due(self.db, self.now), 'error')
        self.assertEqual(self.db.query(NotificationEmailHistory).one().error_message, 'Не удалось отправить уведомление')
        self.assertEqual(set(self.db.scalars(select(UnneededFolderSnapshot.product_code))), {'001'})
        with patch.object(service, 'send_email') as send:
            self.assertEqual(service.run_due(self.db, self.now), 'skipped')
            self.assertEqual(service.run_due(self.db, self.now.replace(day=24)), 'sent')
            send.assert_called_once()

    def test_disabled_before_time_and_no_recipients_do_not_scan(self):
        with patch.object(service, 'current_products', side_effect=AssertionError('unexpected scan')):
            self.assertEqual(service.run_due(self.db, self.now.replace(minute=29)), 'skipped')
            self.setting.enabled = False
            self.db.commit()
            self.assertEqual(service.run_due(self.db, self.now), 'skipped')
            self.setting.enabled = True
            self.setting.recipients_json = '[]'
            self.db.commit()
            self.assertEqual(service.run_due(self.db, self.now), 'no_recipients')

    def test_exact_folder_component_duplicates_and_product_name_not_membership(self):
        self.add('002', 'НЕНУЖНОЕ', 'Обычная|НЕНУЖНОЕ')
        self.add('003', 'Товар', 'НЕНУЖНОЕ старое|Товар')
        product = self.add('004', 'Товар', 'Каталог| ненужное |Товар')
        product.properties.append(ProductProperty(name='ПолныйПуть', value='НЕНУЖНОЕ|Товар'))
        self.db.flush()
        self.assertEqual(set(service.current_products(self.db)), {'001', '004'})

    def test_removal_and_observed_reentry(self):
        product = self.db.query(Product).filter_by(code='001').one()
        product.properties[0].value = 'Другая|Исходный'
        self.db.commit()
        self.assertEqual(service.run_due(self.db, self.now), 'empty')
        product.properties[0].value = 'НЕНУЖНОЕ|Исходный'
        self.db.commit()
        with patch.object(service, 'send_email') as send:
            self.assertEqual(service.run_due(self.db, self.now.replace(day=24)), 'sent')
            send.assert_called_once()

    def test_folder_paths_strip_product_leaf_and_trailing_separator(self):
        self.add('002', 'Мочалка', 'БАНЯ|ЛИНК ГРУПП|БАНЯ|Мочалка')
        self.add('003', 'Другая', 'БАНЯ|ЛИНК ГРУПП|БАНЯ|Другая|')
        self.assertEqual(folder_paths(self.db), ['БАНЯ|ЛИНК ГРУПП|БАНЯ', 'НЕНУЖНОЕ'])

    def test_real_full_path_and_filter_use_canonical_property_case(self):
        from app.services.catalog import catalog_product_query, list_filters
        name = 'Тандыр глина 125л Дастархан со съемной крышкой и стойкой-подставкой под крышку (1)'
        parent = 'МЕТАЛЛ|ПОСУДА для ПРИГОТОВЛЕНИЯ|АМФОРА (тандыры)'
        self.add('005', name, parent + '|' + name)
        self.assertIn(parent, folder_paths(self.db))
        self.assertTrue(all(name not in path for path in folder_paths(self.db)))
        self.assertEqual([row.code for row in catalog_product_query(self.db, {'folder': [parent]}, eager_load=False)], ['005'])
        self.assertNotIn('property:ПолныйПуть', list_filters(self.db))

    def test_settings_validation_and_preserved_baseline(self):
        result = update_unneeded_folder_settings(ScenarioSettingIn(
            enabled=True, send_time='21:15', recipients=[' one@example.test ', '', 'one@example.test']), self.db)
        self.assertEqual(result['recipients'], ['one@example.test'])
        self.assertEqual(result['send_time'], '21:15')
        with self.assertRaises(HTTPException):
            update_unneeded_folder_settings(ScenarioSettingIn(enabled=True, send_time='22:30', recipients=['bad']), self.db)

    def test_real_email_mime_has_only_xls_attachment(self):
        self.add('0002', 'Новый', 'НЕНУЖНОЕ|Новый')
        self.db.commit()
        with patch('app.services.monthly_promotion._smtp') as smtp:
            self.assertEqual(service.run_due(self.db, self.now), 'sent')
            message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
            attachments = list(message.iter_attachments())
            self.assertEqual(len(attachments), 1)
            self.assertEqual(attachments[0].get_content_type(), 'application/vnd.ms-excel')
            sheet = xlrd.open_workbook(file_contents=attachments[0].get_payload(decode=True)).sheet_by_index(0)
            self.assertEqual(sheet.col_values(0), ['', '0002'])

    def test_no_catalog_scan_on_repeated_same_day_execution(self):
        self.assertEqual(service.run_due(self.db, self.now), 'empty')
        with patch.object(service, 'current_products', side_effect=AssertionError('unexpected scan')):
            self.assertEqual(service.run_due(self.db, self.now), 'skipped')

    def test_http_settings_auth_toggle_validation_and_history(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from sqlalchemy.pool import StaticPool
        from app.api.routes import router
        from app.core.admin_auth import require_admin
        from app.db.session import get_db
        engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        app = FastAPI()
        app.include_router(router, prefix='/api')
        def database():
            with Session(engine) as db:
                yield db
        app.dependency_overrides[get_db] = database
        with TestClient(app) as client:
            url = '/api/notification-scenarios/unneeded-folder'
            self.assertEqual(client.get(url).status_code, 401)
            self.assertEqual(client.put(url, json={'enabled': True, 'send_time': '22:30', 'recipients': []}).status_code, 401)
            app.dependency_overrides[require_admin] = lambda: object()
            self.assertEqual(client.get(url).json()['send_time'], '22:30')
            codes = [item['code'] for item in client.get('/api/notification-scenarios').json()]
            self.assertIn('monthly_promotion', codes)
            self.assertIn(service.CODE, codes)
            payload = {'enabled': True, 'send_time': '22:30', 'recipients': ['one@example.test']}
            self.assertEqual(client.put(url, json=payload).status_code, 200)
            self.assertEqual(client.put(url, json={**payload, 'send_time': '25:30'}).status_code, 422)
            self.assertEqual(client.put(url, json={**payload, 'recipients': ['invalid']}).status_code, 422)
            toggle = client.patch('/api/notification-scenarios/unneeded_folder/enabled', json={'enabled': False})
            self.assertEqual(toggle.status_code, 200)
            self.assertFalse(toggle.json()['enabled'])
            history = client.get('/api/notification-scenarios/unneeded_folder/history')
            self.assertEqual(history.status_code, 200)
            self.assertEqual(history.json(), [])
        engine.dispose()

    def test_restart_does_not_resend_and_reenable_resets_baseline(self):
        self.add('002', 'Новый', 'НЕНУЖНОЕ|Новый')
        self.db.commit()
        with patch.object(service, 'send_email'):
            self.assertEqual(service.run_due(self.db, self.now), 'sent')
        self.db.close()
        self.db = Session(self.engine)
        self.assertEqual(service.run_due(self.db, self.now), 'skipped')
        setting = service.get_setting(self.db)
        service.set_enabled(self.db, setting, False)
        self.add('003', 'Пока выключен', 'НЕНУЖНОЕ|Пока выключен')
        service.set_enabled(self.db, setting, True)
        self.db.commit()
        self.assertEqual(service.run_due(self.db, self.now.replace(day=24)), 'empty')

    def test_only_members_with_zero_target_stock_enter_mail_and_xls(self):
        self.add('002', 'Подходит', 'НЕНУЖНОЕ|Подходит', stock=0)
        self.add('003', 'Положительный', 'НЕНУЖНОЕ|Положительный', stock=4)
        self.add('004', 'Отрицательный', 'НЕНУЖНОЕ|Отрицательный', stock=-1)
        self.add('005', 'Нет записи', 'НЕНУЖНОЕ|Нет записи', stock=None)
        self.add('006', 'Другой склад', 'НЕНУЖНОЕ|Другой склад', stock=0, warehouse='Авиаторов')
        self.add('007', 'Другая папка', 'Другая|Другая папка', stock=0)
        self.db.commit()
        with patch.object(service, 'send_email') as send:
            self.assertEqual(service.run_due(self.db, self.now), 'sent')
            html = send.call_args.args[3]
            self.assertIn('Подходит', html)
            for name in ('Исходный', 'Положительный', 'Отрицательный', 'Нет записи', 'Другой склад', 'Другая папка'):
                self.assertNotIn(name, html)
            sheet = xlrd.open_workbook(file_contents=send.call_args.kwargs['extra_attachments'][0][0]).sheet_by_index(0)
            self.assertEqual(sheet.col_values(0), ['', '002'])
        self.assertEqual(set(self.db.scalars(select(UnneededFolderSnapshot.product_code))), {'001', '002'})

    def test_warehouse_mapping_and_aggregate_ignore_other_warehouses(self):
        self.db.add(WarehouseSetting(code='AVIATOR', name=service.WAREHOUSE_NAME))
        product = self.add('002', 'Новый', 'НЕНУЖНОЕ|Новый', stock=2, warehouse='AVIATOR')
        product.stocks.extend([Stock(warehouse='AVIATOR', quantity=-2), Stock(warehouse='OTHER', quantity=10)])
        blocked = self.add('003', 'Не ноль', 'НЕНУЖНОЕ|Не ноль', stock=0)
        blocked.stocks.append(Stock(warehouse=service.WAREHOUSE_NAME, quantity=1))
        self.db.flush()
        self.assertEqual(service.warehouse_stock_by_code(self.db, ['002', '003']), {'002': 0, '003': 1})

    def test_stock_drop_of_existing_folder_member_is_reported_and_can_repeat(self):
        product = self.add('002', 'В папке', 'НЕНУЖНОЕ|В папке', stock=3)
        self.db.commit()
        with patch.object(service, 'send_email') as send:
            self.assertEqual(service.run_due(self.db, self.now), 'empty')
            product.stocks[0].quantity = 0
            self.db.commit()
            self.assertEqual(service.run_due(self.db, self.now.replace(day=24)), 'sent')
            self.assertIn('<td>002</td><td>В папке</td><td>Менеджер</td><td>0</td>', send.call_args.args[3])
            self.assertEqual(service.run_due(self.db, self.now.replace(day=25)), 'empty')
            send.assert_called_once()

            product.stocks[0].quantity = 5
            self.db.commit()
            self.assertEqual(service.run_due(self.db, self.now.replace(day=26)), 'empty')
            product.stocks[0].quantity = 0
            self.db.commit()
            self.assertEqual(service.run_due(self.db, self.now.replace(day=27)), 'sent')
            self.assertEqual(send.call_count, 2)

    def test_legacy_baseline_drops_ineligible_codes_and_preserves_known_zeros(self):
        product = self.add('002', 'В папке', 'НЕНУЖНОЕ|В папке', stock=3)
        self.db.add(UnneededFolderSnapshot(product_code='002'))
        self.db.commit()
        with patch.object(service, 'send_email') as send:
            self.assertEqual(service.run_due(self.db, self.now), 'empty')
            self.assertEqual(set(self.db.scalars(select(UnneededFolderSnapshot.product_code))), {'001'})
            send.assert_not_called()
            product.stocks[0].quantity = 0
            self.db.commit()
            self.assertEqual(service.run_due(self.db, self.now.replace(day=24)), 'sent')
            self.assertIn('<td>002</td>', send.call_args.args[3])
            self.assertNotIn('<td>001</td>', send.call_args.args[3])

    def test_stock_selection_uses_one_query_per_batch_not_per_product(self):
        from sqlalchemy import event
        statements = []
        for i in range(20):
            self.add(f'NEW-{i}', 'Новый', 'НЕНУЖНОЕ|Новый')
        self.db.commit()
        event.listen(self.engine, 'before_cursor_execute', lambda conn, cursor, sql, params, context, many: statements.append(sql))
        self.assertEqual(len(service.warehouse_stock_by_code(self.db, [f'NEW-{i}' for i in range(20)])), 20)
        self.assertEqual(len(statements), 1)
        self.assertEqual(service.warehouse_stock_by_code(self.db, []), {})
        self.assertEqual(len(statements), 1)
