"""Small real-XLSX tests; no external services or production database."""
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from fastapi import HTTPException
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.catalog import Product, Price, ProductProperty
from app.api import routes
from app.services.export_layout import PRICE_PAIRS, archive_name, export_plan


class ExcelLayoutTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.temp = tempfile.TemporaryDirectory()
        self.params = {'in_stock_only': False, 'exclude_yyy': False}
        # Interleave sections and folders so tests require global sorting, not batch sorting.
        for index, (section, folder) in enumerate([
            ('Уборка', 'БЫТОВАЯ химия|СИМА ЮГ'),
            ('Аксессуары для бани', 'БЫТОВАЯ химия|СИМА ЮГ'),
            ('Уборка', 'ДРУГАЯ папка'),
            ('Аксессуары для бани', 'БЫТОВАЯ химия|СИМА ЮГ'),
        ]):
            name = 'Товар х|б ' + str(index)
            product = Product(code=f'00{index}', name=name, category1='Баня и сауна', section=section,
                              properties=[ProductProperty(name='ПолныйПуть', value=folder + '|' + name)])
            for i, (price, previous) in enumerate(PRICE_PAIRS.items()):
                product.prices.extend([Price(price_type=price, price_value=100 + i), Price(price_type=previous, price_value=150 + i)])
            self.db.add(product)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.temp.cleanup()

    def output(self, options, columns=None, params=None):
        path = str(Path(self.temp.name) / ('products.zip' if options.get('zip_categories') else 'products.xlsx'))
        params = params or self.params
        ids = routes.filtered_product_ids_subquery(self.db, params)
        total = self.db.query(ids).count()
        processed = routes.write_export_output(self.db, params, columns or ['code', 'name'], path, 'test', total, ids, options)
        self.assertEqual(processed, total)
        return path

    def test_group_hierarchy_matches_example_and_does_not_include_product_name(self):
        book = load_workbook(self.output({'group_categories': True, 'group_folders': True}))
        titles = [row[0].value for row in book.active]
        self.assertEqual(titles, ['Код', 'Баня и сауна', 'Аксессуары для бани', 'БЫТОВАЯ химия', 'СИМА ЮГ',
                                  '001', '003', 'Уборка', 'БЫТОВАЯ химия', 'СИМА ЮГ', '000', 'ДРУГАЯ папка', '002'])
        self.assertEqual(book.active['B6'].value, 'Товар х|б 1')
        self.assertFalse(book.active.auto_filter.ref)  # Sorting/filtering must not mix headings with products.
        book.close()

    def test_category_and_folder_toggles_are_independent(self):
        for options, present, absent in [({'group_categories': True}, 'Аксессуары для бани', 'СИМА ЮГ'),
                                         ({'group_folders': True}, 'СИМА ЮГ', 'Аксессуары для бани')]:
            book = load_workbook(self.output(options, ['code']))
            titles = [row[0].value for row in book.active]
            self.assertIn(present, titles)
            self.assertNotIn(absent, titles)
            self.assertEqual(sum(isinstance(value, str) and value.startswith('00') for value in titles), 4)
            book.close()

    def test_all_price_pairs_and_combined_order_form_have_correct_formula_row(self):
        for i, price in enumerate(PRICE_PAIRS):
            book = load_workbook(self.output({'promotion': True, 'order_form': True, 'group_categories': True}, ['code', 'price:' + price]))
            sheet = book.active
            self.assertEqual([cell.value for cell in sheet[1]], ['Код', 'Акция! Новая цена', 'Старая цена', 'Заказ', 'Сумма заказа'])
            self.assertEqual(sheet['B4'].value, 100 + i)
            self.assertEqual(sheet['C4'].value, 150 + i)
            self.assertIsNone(sheet['D4'].value)
            self.assertEqual(sheet['E4'].value, '=IF(OR(B4="",D4=""),"",B4*D4)')
            self.assertEqual(sheet['E7'].value, '=IF(OR(B7="",D7=""),"",B7*D7)')
            book.close()

    def test_order_without_promotion_uses_selected_price_and_missing_prices_are_blank(self):
        self.db.query(Price).delete()
        self.db.commit()
        book = load_workbook(self.output({'order_form': True}, ['code', 'price:ЦенаРозничная']))
        sheet = book.active
        self.assertEqual([cell.value for cell in sheet[1]], ['Код', 'ЦенаРозничная', 'Заказ', 'Сумма заказа'])
        self.assertIsNone(sheet['B2'].value)
        self.assertEqual(sheet['D2'].value, '=IF(OR(B2="",C2=""),"",B2*C2)')
        book.close()
        book = load_workbook(self.output({'promotion': True}, ['code', 'price:ЦенаОптовая']))
        self.assertIsNone(book.active['C2'].value)
        book.close()

    def test_invalid_price_selection_rejected_before_scheduling(self):
        for columns in (['code'], ['price:ЦенаОптовая', 'price:ЦенаРозничная'], ['price:Неизвестная']):
            with patch.object(routes.export_executor, 'submit') as submit, self.assertRaises(HTTPException) as error:
                routes.start_xlsx_export(column=columns, promotion=True)
            self.assertEqual(error.exception.status_code, 422)
            submit.assert_not_called()

    def test_zip_contains_exact_selected_subcategories_and_combined_forms(self):
        path = self.output({'zip_categories': True, 'group_categories': True, 'group_folders': True,
                            'promotion': True, 'order_form': True}, ['code', 'price:ЦенаОптовая'])
        with ZipFile(path) as archive:
            self.assertEqual(set(archive.namelist()), {'Аксессуары для бани.xlsx', 'Уборка.xlsx'})
            codes = []
            for name in archive.namelist():
                book = load_workbook(BytesIO(archive.read(name)))
                rows = list(book.active.values)
                self.assertEqual(rows[2][0] + '.xlsx', name)
                codes.extend(row[0] for row in rows if isinstance(row[0], str) and row[0].startswith('00'))
                self.assertEqual(rows[0][-2:], ('Заказ', 'Сумма заказа'))
                book.close()
            self.assertEqual(sorted(codes), ['000', '001', '002', '003'])
        with ZipFile(self.output({'zip_categories': True}, params={'product_ids': [2, 4]})) as archive:
            self.assertEqual(archive.namelist(), ['Аксессуары для бани.xlsx'])

    def test_safe_unique_archive_names_and_empty_selection(self):
        used = set()
        names = [archive_name(value, used) for value in ('../A', '..\\A', 'CON', 'a/b', 'a\\b', '', 'A/B')]
        self.assertEqual(len(set(name.casefold() for name in names)), len(names))
        self.assertTrue(all('/' not in name and '\\' not in name and not name.startswith('.') for name in names))
        with ZipFile(self.output({'zip_categories': True}, params={'product_ids': [999]})) as archive:
            self.assertEqual(archive.namelist(), [])

    def test_ordering_across_small_batches_and_sheet_break_repeats_headings(self):
        ids = routes.filtered_product_ids_subquery(self.db, self.params)
        options = {'group_categories': True, 'order_form': True}
        with export_plan(self.db, ids, options, self.temp.name) as plan:
            path = str(Path(self.temp.name) / 'split.xlsx')
            with patch.object(routes, 'MAX_SHEET_HYPERLINKS', 4):
                routes.write_export_workbook_streaming(self.db, self.params, ['code', 'site_url', 'price:ЦенаОптовая'], path, 'test', 4,
                                                       ids, options=options, batches=plan.batches(size=1))
        book = load_workbook(path)
        self.assertEqual(len(book.worksheets), 2)
        for sheet in book:
            self.assertEqual(sheet['A2'].value, 'Баня и сауна')
            self.assertEqual(sheet['E4'].value, '=IF(OR(C4="",D4=""),"",C4*D4)')
        self.assertEqual(book.worksheets[0]['A4'].value, '001')
        self.assertEqual(book.worksheets[1]['A4'].value, '000')
        book.close()

    def test_missing_category_and_folder_have_explicit_headings(self):
        self.db.add(Product(code='empty', name='Без папки'))
        self.db.commit()
        product = self.db.query(Product).filter_by(code='empty').one()
        book = load_workbook(self.output({'group_categories': True, 'group_folders': True}, params={'product_ids': [product.id]}))
        self.assertEqual([row[0].value for row in book.active], ['Код', 'Без категории', 'Без подкатегории', 'Без папки', 'empty'])
        book.close()

    def test_zip_job_publishes_download_metadata_and_cleans_temporary_files(self):
        with patch.object(routes, 'SessionLocal', side_effect=lambda: Session(self.engine)), \
             patch.object(routes.settings, 'upload_dir', self.temp.name), \
             patch.dict(routes.export_jobs, {'zip-test': {}}, clear=True):
            routes.create_xlsx_export('zip-test', self.params, ['code'], {'zip_categories': True})
            job = routes.export_jobs['zip-test']
            self.assertEqual(job['status'], 'ready', job)
            self.assertEqual(job['filename'], 'products.zip')
            self.assertEqual(job['media_type'], 'application/zip')
            self.assertEqual(job['processed'], 4)
            with ZipFile(job['path']) as archive:
                self.assertEqual(len(archive.namelist()), 2)
            self.assertEqual(list((Path(self.temp.name) / 'xlsx-exports').iterdir()), [Path(job['path'])])

    def test_failed_zip_job_removes_partial_archive_and_temporary_files(self):
        with patch.object(routes, 'SessionLocal', side_effect=lambda: Session(self.engine)), \
             patch.object(routes.settings, 'upload_dir', self.temp.name), \
             patch.dict(routes.export_jobs, {'failed-zip': {}}, clear=True), \
             patch.object(routes, 'write_export_workbook_streaming', side_effect=RuntimeError('test failure')), \
             patch.object(routes.logger, 'exception'):
            routes.create_xlsx_export('failed-zip', self.params, ['code'], {'zip_categories': True})
            self.assertEqual(routes.export_jobs['failed-zip']['status'], 'error')
            self.assertEqual(list((Path(self.temp.name) / 'xlsx-exports').iterdir()), [])

    def test_promotion_filters_before_counting_selected_ids_and_zip_creation(self):
        from app.models.catalog import ProductTypeSetting
        products = self.db.query(Product).order_by(Product.id).all()
        products[0].product_type = '10'
        products[1].product_type = '1'
        products[2].product_type = 'Акция месяца'
        products[3].properties.append(ProductProperty(name='Вид товара', value='Акция месяца'))
        self.db.add(Product(code='conflict', name='Обычный', product_type='1',
                            properties=[ProductProperty(name='ВидТовара', value='10')]))
        self.db.add(ProductTypeSetting(code='99', name='Акция месяца'))
        self.db.add(Product(code='custom', name='Настроенный вид', product_type='99', section='Тест'))
        self.db.commit()
        for zip_mode, params, expected in (
            (False, self.params, {'000', '002', '003', 'custom'}),
            (True, {'product_ids': [1, 2, 3]}, {'000', '002'}),
        ):
            with patch.object(routes, 'SessionLocal', side_effect=lambda: Session(self.engine)), \
                 patch.object(routes.settings, 'upload_dir', self.temp.name), \
                 patch.dict(routes.export_jobs, {'promo': {}}, clear=True):
                routes.create_xlsx_export('promo', params, ['code', 'price:ЦенаОптовая'],
                                          {'promotion': True, 'zip_categories': zip_mode})
                job = routes.export_jobs['promo']
                self.assertEqual(job['status'], 'ready', job)
                self.assertEqual(job['total'], len(expected))
                self.assertEqual(job['processed'], len(expected))
                if zip_mode:
                    with ZipFile(job['path']) as archive:
                        books = [load_workbook(BytesIO(archive.read(name))) for name in archive.namelist()]
                else:
                    books = [load_workbook(job['path'])]
                codes = {row[0].value for book in books for row in list(book.active)[1:]}
                self.assertEqual(codes, expected)
                for book in books:
                    book.close()

    def test_folder_headers_stop_before_stale_product_fragments(self):
        product = self.db.query(Product).first()
        product.properties[0].value = 'МЕТАЛЛ|ПОСУДА для ПРИГОТОВЛЕНИЯ|ТАЛЛЕР|Доска разделочная дерево набор|34,5*18*1|АКРОС'
        self.db.commit()
        book = load_workbook(self.output({'group_folders': True}, ['code'], {'product_ids': [product.id]}))
        self.assertEqual([row[0].value for row in book.active], ['Код', 'МЕТАЛЛ', 'ПОСУДА для ПРИГОТОВЛЕНИЯ', 'ТАЛЛЕР', product.code])
        book.close()
