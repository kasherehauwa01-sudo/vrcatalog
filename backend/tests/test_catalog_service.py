import unittest
from base64 import b64decode
from datetime import datetime, timedelta
from io import BytesIO

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.catalog import (
    Barcode,
    Price,
    Product,
    ProductProperty,
    ProductImage,
    ProductTypeSetting,
    ServiceLog,
    Stock,
    WarehouseSetting,
)
from app.api.routes import build_export_workbook, download_export_images, normalize_image_url
from app.services.catalog import catalog_product_query, list_filters, paginated_products
from app.services.logging import add_log
from app.schemas.catalog import ProductDetailOut


class CatalogProductQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", future=True)
        Base.metadata.create_all(cls.engine)

    def setUp(self):
        self.db = Session(self.engine)
        for model in (Barcode, Price, Stock, ProductProperty, ProductImage, Product, ProductTypeSetting, WarehouseSetting):
            self.db.query(model).delete()
        self.products = [
            Product(code="CHAIR-1", name="Стул Альфа", article="SKU-001", section="Мебель", brand="Alpha", product_type="TYPE-1", quantity=5, search_text="стул альфа chair-1 sku-001 alpha"),
            Product(code="PAN-2", name="Сковорода Beta", article="SKU-002", section="Посуда", brand="Beta", quantity=0, search_text="сковорода beta pan-2 sku-002 460000000002"),
            Product(code="TABLE-3", name="Стол большой", article="ART-003", section="Мебель", brand="Alpha", quantity=12, search_text="стол большой table-3 art-003 alpha"),
        ]
        self.products[0].prices = [Price(price_type="Розничная", price_value=1500)]
        self.products[1].prices = [Price(price_type="Розничная", price_value=3000)]
        self.products[2].prices = [Price(price_type="Розничная", price_value=5000)]
        self.products[1].barcodes = [Barcode(value="460000000002")]
        self.products[0].stocks = [Stock(warehouse="WH1", quantity=0)]
        self.products[1].stocks = [Stock(warehouse="WH1", quantity=3)]
        self.products[2].stocks = [
            Stock(warehouse="WH2", quantity=4),
            Stock(warehouse="WH3", quantity=2),
        ]
        self.products[0].properties = [
            ProductProperty(name="Коллекция", value="Лето"),
            ProductProperty(name="Артикул", value="Скрытое значение"),
            ProductProperty(name="Вид товара", value="TYPE-1"),
            ProductProperty(name="Производитель", value="Дубликат"),
            ProductProperty(name="Наличие свистка", value="Да"),
        ]
        self.db.add_all(
            [
                ProductTypeSetting(code="TYPE-1", name="Стулья"),
                WarehouseSetting(code="WH1", name="Основной"),
                WarehouseSetting(code="WH2", name="Резервный"),
                WarehouseSetting(code="WH3", name="Авиаторов"),
            ]
        )
        self.db.add_all(self.products)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def query(self, **params):
        return catalog_product_query(self.db, params).order_by(Product.id).all()

    def test_searches_name_article_and_barcode_case_insensitively(self):
        self.assertEqual([p.code for p in self.query(search="  СТУЛ  ")], ["CHAIR-1"])
        self.assertEqual([p.code for p in self.query(search="sku-002")], ["PAN-2"])
        self.assertEqual([p.code for p in self.query(search="000002")], ["PAN-2"])
        self.assertEqual([p.code for p in self.query(code="chair")], ["CHAIR-1"])

    def test_multiple_codes_can_be_separated_by_spaces_or_commas(self):
        self.assertEqual(
            [product.code for product in self.query(code="CHAIR-1, PAN-2")],
            ["CHAIR-1", "PAN-2"],
        )
        self.assertEqual(
            [product.code for product in self.query(code="CHAIR-1 TABLE-3")],
            ["CHAIR-1", "TABLE-3"],
        )

    def test_multiple_articles_can_be_separated_by_spaces_or_commas(self):
        self.assertEqual(
            [product.code for product in self.query(article="SKU-001,ART-003")],
            ["CHAIR-1", "TABLE-3"],
        )
        self.assertEqual(
            [product.code for product in self.query(article="SKU-001 SKU-002")],
            ["CHAIR-1", "PAN-2"],
        )

    def test_category_availability_and_price_filters_use_and_logic(self):
        result = self.query(section="Мебель", availability="in_stock", price_from=1000, price_to=2000)
        self.assertEqual([p.code for p in result], ["CHAIR-1"])
        self.assertEqual([p.code for p in self.query(availability="out_of_stock")], ["PAN-2"])

    def test_ranges_include_boundary_values(self):
        self.assertEqual([p.code for p in self.query(quantity_from=5, quantity_to=5)], ["CHAIR-1"])
        self.assertEqual([p.code for p in self.query(price_from=3000, price_to=3000)], ["PAN-2"])

    def test_multiple_values_are_or_within_one_filter(self):
        self.assertEqual(len(self.query(section="Мебель,Посуда", brand="Alpha")), 2)

    def test_warehouse_filter_requires_positive_stock_in_selected_warehouse(self):
        self.assertEqual([p.code for p in self.query(warehouse="Основной")], ["PAN-2"])

    def test_default_stock_scope_uses_positive_warehouse_balances(self):
        self.assertEqual(
            [p.code for p in self.query(in_stock_only=True)],
            ["PAN-2", "TABLE-3"],
        )
        self.assertEqual(
            [p.code for p in self.query(in_stock_only=False)],
            ["CHAIR-1", "PAN-2", "TABLE-3"],
        )

    def test_filter_metadata_hides_excluded_properties_and_uses_mapping_names(self):
        filters = list_filters(self.db)
        self.assertNotIn("property:Артикул", filters)
        self.assertNotIn("property:Вид товара", filters)
        self.assertNotIn("property:Производитель", filters)
        self.assertEqual(filters["property:Коллекция"], ["Лето"])
        self.assertEqual(filters["product_type"], ["Новинка", "Стулья"])
        self.assertEqual(filters["warehouse"], ["Авиаторов", "Основной", "Резервный"])
        self.assertEqual(filters["barcode"], ["460000000002"])

    def test_property_options_are_limited_by_main_filters(self):
        filters = list_filters(self.db, {"brand": "Beta"})
        self.assertNotIn("property:Наличие свистка", filters)

    def test_new_product_type_filter_finds_products_loaded_within_seven_days(self):
        self.products[0].created_at = datetime.utcnow() - timedelta(days=8)
        self.products[1].created_at = datetime.utcnow() - timedelta(days=6)
        self.products[2].created_at = datetime.utcnow()
        self.db.commit()

        result = self.query(product_type="Новинка")

        self.assertEqual([product.code for product in result], ["PAN-2", "TABLE-3"])

    def test_new_product_type_filter_does_not_depend_on_xml_characteristic(self):
        self.products[0].created_at = datetime.utcnow() - timedelta(days=8)
        self.products[0].properties.append(ProductProperty(name="Новинка", value="Да"))
        self.db.commit()

        result = self.query(product_type="Новинка")

        self.assertEqual(result, [])

    def test_new_product_type_filter_uses_or_with_regular_product_types(self):
        self.products[0].created_at = datetime.utcnow() - timedelta(days=8)
        self.products[1].created_at = datetime.utcnow() - timedelta(days=2)
        self.products[2].created_at = datetime.utcnow() - timedelta(days=9)
        self.db.commit()

        result = self.query(product_type="Новинка,Стулья")

        self.assertEqual([product.code for product in result], ["CHAIR-1", "PAN-2"])

    def test_sorting_and_server_pagination(self):
        params = {"page": 1, "page_size": 20, "sort": "price", "order": "desc"}
        items, pagination = paginated_products(self.db, params)
        self.assertEqual([p.code for p in items], ["TABLE-3", "PAN-2", "CHAIR-1"])
        self.assertEqual(pagination, {"page": 1, "pageSize": 20, "totalItems": 3, "totalPages": 1})

    def test_default_sort_puts_recently_updated_products_first(self):
        self.products[0].updated_at = datetime(2026, 7, 28, 13, 0)
        self.products[1].updated_at = datetime(2026, 7, 28, 13, 15)
        self.products[2].updated_at = datetime(2026, 7, 28, 13, 10)
        self.db.commit()

        items, _ = paginated_products(self.db, {"page": 1, "page_size": 20})

        self.assertEqual([product.code for product in items], ["PAN-2", "TABLE-3", "CHAIR-1"])

    def test_only_new_filter_uses_created_at_and_combines_with_other_filters(self):
        self.products[0].created_at = datetime.utcnow() - timedelta(days=8)
        self.products[1].created_at = datetime.utcnow() - timedelta(days=6)
        self.products[2].created_at = datetime.utcnow()
        self.db.commit()

        result = self.query(only_new=True, section="Мебель")

        self.assertEqual([product.code for product in result], ["TABLE-3"])
        self.assertFalse(self.products[0].is_new)
        self.assertTrue(self.products[2].is_new)

    def test_new_products_can_be_sorted_before_old_products(self):
        self.products[0].created_at = datetime.utcnow() - timedelta(days=8)
        self.products[1].created_at = datetime.utcnow() - timedelta(days=2)
        self.products[2].created_at = datetime.utcnow() - timedelta(days=9)
        self.db.commit()

        items, _ = paginated_products(
            self.db,
            {"page": 1, "page_size": 20, "sort": "is_new", "order": "desc"},
        )

        self.assertEqual(items[0].code, "PAN-2")

    def test_empty_result(self):
        self.assertEqual(self.query(search="несуществующий товар"), [])

    def test_excel_export_uses_selected_main_price_and_warehouse_columns(self):
        self.products[0].manager = "Иванова"
        self.products[0].barcodes = [Barcode(value="460000000001")]
        workbook = build_export_workbook(
            self.db,
            {"in_stock_only": False},
            ["code", "name", "section", "manager", "barcodes", "price:ЦенаРозничная", "stock:WH1"],
        )

        rows = list(workbook.active.values)

        self.assertEqual(
            rows[0],
            ("Код", "Наименование", "Раздел", "Менеджер", "Штрихкоды", "ЦенаРозничная", "Основной"),
        )
        chair_row = next(row for row in rows[1:] if row[0] == "CHAIR-1")
        self.assertEqual(chair_row, ("CHAIR-1", "Стул Альфа", "Мебель", "Иванова", "460000000001", 1500, 0))

    def test_excel_export_orders_main_columns_and_formats_their_widths(self):
        self.products[0].certificate = "CERTIFICATE-12345"
        self.products[0].manufacturer = "Очень длинное название производителя"
        self.products[0].manager = "Очень длинное имя менеджера"
        self.products[0].material = "Очень длинное название материала"
        self.products[0].barcodes = [Barcode(value="46000000000123456789")]
        workbook = build_export_workbook(
            self.db,
            {"in_stock_only": False},
            ["photo", "section", "certificate", "name", "barcodes", "code", "material", "article", "manager", "manufacturer", "marking_code", "quantity"],
        )
        worksheet = workbook.active

        self.assertEqual(
            tuple(cell.value for cell in worksheet[1]),
            ("Код", "Артикул", "Наименование", "Раздел", "Фото", "Сертификат", "Штрихкоды", "Материал", "Менеджер", "Производитель", "Код маркировки", "Остаток"),
        )
        self.assertEqual(worksheet.column_dimensions["A"].width, len("CHAIR-1") + 2)
        self.assertEqual(worksheet.column_dimensions["B"].width, len("Артикул") + 2)
        self.assertEqual(worksheet.column_dimensions["C"].width, 50)
        self.assertEqual(worksheet.column_dimensions["D"].width, 12)
        self.assertEqual(worksheet.column_dimensions["F"].width, len("CERTIFICATE-12345") + 2)
        self.assertEqual(worksheet.column_dimensions["G"].width, 13)
        self.assertEqual(worksheet.column_dimensions["H"].width, 12)
        self.assertEqual(worksheet.column_dimensions["I"].width, 12)
        self.assertEqual(worksheet.column_dimensions["J"].width, 12)
        self.assertEqual(worksheet.column_dimensions["K"].width, len("Код маркировки") + 2)
        self.assertEqual(worksheet.column_dimensions["L"].width, len("Остаток") + 2)
        self.assertTrue(worksheet["C2"].alignment.wrap_text)
        self.assertTrue(worksheet["G2"].alignment.wrap_text)
        self.assertTrue(all(
            cell.alignment.vertical == "center"
            for row in worksheet.iter_rows()
            for cell in row
        ))

    def test_excel_export_rejects_unknown_columns(self):
        with self.assertRaisesRegex(Exception, "Неизвестные колонки экспорта"):
            build_export_workbook(self.db, {}, ["unknown"])

    def test_excel_export_embeds_first_photo_at_one_hundred_pixels(self):
        self.products[0].images = [
            ProductImage(image_order=1, image_url="https://example.test/first.png"),
            ProductImage(image_order=2, image_url="https://example.test/second.png"),
        ]
        requested_urls = []
        png = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")

        def image_loader(url):
            requested_urls.append(url)
            return BytesIO(png)

        workbook = build_export_workbook(
            self.db,
            {"code": "CHAIR-1", "in_stock_only": False},
            ["code", "photo", "name"],
            image_loader=image_loader,
        )
        worksheet = workbook.active

        self.assertEqual(requested_urls, ["https://example.test/first.png"])
        self.assertEqual(len(worksheet._images), 1)
        self.assertEqual((worksheet._images[0].width, worksheet._images[0].height), (100, 100))
        self.assertEqual(worksheet.row_dimensions[2].height, 82.5)
        self.assertEqual(worksheet.column_dimensions["B"].width, 16)
        self.assertGreater(worksheet._images[0].anchor._from.colOff, 0)
        self.assertGreater(worksheet._images[0].anchor._from.rowOff, 0)
        self.assertEqual(worksheet["B2"].value, None)
        workbook.save(BytesIO())

    def test_excel_export_encodes_cyrillic_image_path(self):
        self.assertEqual(
            normalize_image_url("https://volgorost.ru/images/Новая папка/Фото 1.jpg"),
            "https://volgorost.ru/images/%D0%9D%D0%BE%D0%B2%D0%B0%D1%8F%20%D0%BF%D0%B0%D0%BF%D0%BA%D0%B0/%D0%A4%D0%BE%D1%82%D0%BE%201.jpg",
        )

    def test_excel_export_downloads_duplicate_photos_only_once(self):
        requested_urls = []

        def image_loader(url):
            requested_urls.append(url)
            return BytesIO(url.encode())

        images = download_export_images(["first", "first", "second"], image_loader)

        self.assertCountEqual(requested_urls, ["first", "second"])
        self.assertEqual(images, {"first": b"first", "second": b"second"})


class ServiceLoggingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", future=True)
        Base.metadata.create_all(cls.engine)

    def setUp(self):
        self.db = Session(self.engine)
        self.db.query(ServiceLog).delete()

    def tearDown(self):
        self.db.close()

    def test_keeps_only_latest_one_hundred_errors(self):
        add_log(self.db, "info", "Не сохранять")
        for index in range(105):
            add_log(self.db, f"error_{index}", "Ошибка", level="error")
        self.db.commit()

        logs = self.db.query(ServiceLog).order_by(ServiceLog.id).all()
        self.assertEqual(len(logs), 100)
        self.assertTrue(all(log.level == "error" for log in logs))
        self.assertEqual(logs[0].event, "error_5")


class ProductDetailSchemaTests(unittest.TestCase):
    def test_formats_product_dates_consistently(self):
        payload = ProductDetailOut(
            id=1,
            code="TEST-1",
            name="Тестовый товар",
            article=None,
            section=None,
            product_type=None,
            quantity=0,
            is_new=True,
            created_at=datetime(2026, 7, 28, 13, 0),
            updated_at=datetime(2026, 7, 28, 13, 15),
            description=None,
            manufacturer=None,
            brand=None,
            manager=None,
            country=None,
            material=None,
            color=None,
            certificate=None,
            tags=None,
            prices=[],
            stocks=[],
            properties=[],
            analogs=[],
            barcodes=[],
        )

        result = payload.model_dump(mode="json")

        self.assertEqual(result["created_at"], "28.07.2026 16:00")
        self.assertEqual(result["updated_at"], "28.07.2026 16:15")


if __name__ == "__main__":
    unittest.main()
