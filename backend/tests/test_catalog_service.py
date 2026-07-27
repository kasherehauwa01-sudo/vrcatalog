import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.catalog import (
    Barcode,
    Price,
    Product,
    ProductProperty,
    ProductTypeSetting,
    ServiceLog,
    Stock,
    WarehouseSetting,
)
from app.services.catalog import catalog_product_query, list_filters, paginated_products
from app.services.logging import add_log


class CatalogProductQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", future=True)
        Base.metadata.create_all(cls.engine)

    def setUp(self):
        self.db = Session(self.engine)
        for model in (Barcode, Price, Stock, ProductProperty, Product, ProductTypeSetting, WarehouseSetting):
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
        self.assertEqual(filters["product_type"], ["Стулья"])
        self.assertEqual(filters["warehouse"], ["Авиаторов", "Основной", "Резервный"])
        self.assertEqual(filters["barcode"], ["460000000002"])

    def test_property_options_are_limited_by_main_filters(self):
        filters = list_filters(self.db, {"brand": "Beta"})
        self.assertNotIn("property:Наличие свистка", filters)

    def test_sorting_and_server_pagination(self):
        params = {"page": 1, "page_size": 20, "sort": "price", "order": "desc"}
        items, pagination = paginated_products(self.db, params)
        self.assertEqual([p.code for p in items], ["TABLE-3", "PAN-2", "CHAIR-1"])
        self.assertEqual(pagination, {"page": 1, "pageSize": 20, "totalItems": 3, "totalPages": 1})

    def test_empty_result(self):
        self.assertEqual(self.query(search="несуществующий товар"), [])


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


if __name__ == "__main__":
    unittest.main()
