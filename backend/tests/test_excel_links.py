import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from openpyxl import load_workbook
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.catalog import Product, ProductImage
from app.api import routes
from app.services.export_links import product_site_link


class ExcelLinkTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add_all([
            Product(code='001234', name='Первый', images=[ProductImage(image_order=9, image_url='later.jpg'), ProductImage(image_order=2, image_url='/images/photo one.jpg')]),
            Product(code='ИГР-05421', name='Второй', images=[ProductImage(image_order=3, image_url='https://cdn.example.test/фото.jpg')]),
            Product(code='A &B/+', name='Без фото'),
        ])
        self.db.commit()
        self.params = {'in_stock_only': False, 'exclude_yyy': False}
        self.temp = tempfile.TemporaryDirectory()
        self.sql = []
        event.listen(self.engine, 'before_cursor_execute', lambda conn, cursor, sql, params, context, many: self.sql.append(sql))

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.temp.cleanup()

    def workbook(self, streaming, columns):
        path = Path(self.temp.name) / 'export.xlsx'
        if streaming:
            routes.write_export_workbook_streaming(self.db, self.params, columns, str(path), 'link-test', 3)
        else:
            book = routes.build_export_workbook(self.db, self.params, columns)
            book.save(path)
            book.close()
        return load_workbook(path)

    def test_both_exporters_write_clickable_links_without_downloading_images(self):
        for streaming in (False, True):
            with self.subTest(streaming=streaming), patch.object(routes, 'download_export_images') as downloads:
                book = self.workbook(streaming, ['code', 'image_url', 'site_url'])
                sheet = book.active
                self.assertEqual([cell.value for cell in sheet[1]], ['Код', 'Ссылка на фото', 'Ссылка на сайт'])
                self.assertEqual(sheet['A2'].value, '001234')
                self.assertEqual(sheet['B2'].value, 'https://volgorost.ru/upload/import_images/images/photo%20one.jpg')
                self.assertEqual(sheet['B2'].hyperlink.target, sheet['B2'].value)
                self.assertTrue(sheet['B3'].value.startswith('https://cdn.example.test/'))
                self.assertIsNone(sheet['B4'].value)
                self.assertIsNone(sheet['B4'].hyperlink)
                for row in (2, 3, 4):
                    url = sheet.cell(row, 3).value
                    self.assertEqual(sheet.cell(row, 3).hyperlink.target, url)
                    self.assertEqual(parse_qs(urlsplit(url).query), {'q': [sheet.cell(row, 1).value], 's': ['Найти'], 'type': ['catalog']})
                downloads.assert_not_called()
                book.close()

    def test_site_link_only_does_not_read_images_or_add_other_columns(self):
        for streaming in (False, True):
            self.sql.clear()
            book = self.workbook(streaming, ['site_url'])
            self.assertEqual(book.active.max_column, 1)
            self.assertEqual(book.active['A1'].value, 'Ссылка на сайт')
            self.assertFalse(any('product_images' in sql for sql in self.sql))
            book.close()

    def test_image_link_selection_is_one_batch_query(self):
        book = self.workbook(True, ['image_url'])
        self.assertEqual(sum('product_images' in sql for sql in self.sql), 1)
        book.close()

    def test_both_exporters_split_sheets_before_excel_hyperlink_limit(self):
        for streaming in (False, True):
            with self.subTest(streaming=streaming), patch.object(routes, 'MAX_SHEET_HYPERLINKS', 4):
                book = self.workbook(streaming, ['code', 'image_url', 'site_url'])
            self.assertEqual(len(book.worksheets), 2)
            self.assertEqual(book.worksheets[0].max_row, 3)
            self.assertEqual(book.worksheets[1].max_row, 2)
            self.assertEqual(book.worksheets[1]['A2'].value, 'A &B/+')
            self.assertIsNotNone(book.worksheets[1]['C2'].hyperlink)
            book.close()

    def test_embedded_photo_and_photo_link_are_independent(self):
        with patch.object(routes, 'download_export_images', return_value={}):
            book = self.workbook(False, ['photo', 'image_url'])
        self.assertEqual([cell.value for cell in book.active[1]], ['Фото', 'Ссылка на фото'])
        self.assertEqual(book.active['B2'].hyperlink.target, 'https://volgorost.ru/upload/import_images/images/photo%20one.jpg')
        book.close()

    def test_site_search_matches_supplied_url_format(self):
        url = urlsplit(product_site_link('ИГР-05421'))
        self.assertEqual((url.scheme, url.netloc, url.path), ('https', 'volgorost.ru', '/catalog/'))
        self.assertEqual(parse_qs(url.query), {'q': ['ИГР-05421'], 's': ['Найти'], 'type': ['catalog']})
