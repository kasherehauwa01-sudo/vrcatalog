import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.catalog import Barcode, Price, Product
from app.services.catalog import catalog_product_query, paginated_products


class CatalogProductQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", future=True)
        Base.metadata.create_all(cls.engine)

    def setUp(self):
        self.db = Session(self.engine)
        self.db.query(Product).delete()
        self.products = [
            Product(code="CHAIR-1", name="Стул Альфа", article="SKU-001", section="Мебель", brand="Alpha", quantity=5, search_text="стул альфа chair-1 sku-001 alpha"),
            Product(code="PAN-2", name="Сковорода Beta", article="SKU-002", section="Посуда", brand="Beta", quantity=0, search_text="сковорода beta pan-2 sku-002 460000000002"),
            Product(code="TABLE-3", name="Стол большой", article="ART-003", section="Мебель", brand="Alpha", quantity=12, search_text="стол большой table-3 art-003 alpha"),
        ]
        self.products[0].prices = [Price(price_type="Розничная", price_value=1500)]
        self.products[1].prices = [Price(price_type="Розничная", price_value=3000)]
        self.products[2].prices = [Price(price_type="Розничная", price_value=5000)]
        self.products[1].barcodes = [Barcode(value="460000000002")]
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

    def test_category_availability_and_price_filters_use_and_logic(self):
        result = self.query(section="Мебель", availability="in_stock", price_from=1000, price_to=2000)
        self.assertEqual([p.code for p in result], ["CHAIR-1"])
        self.assertEqual([p.code for p in self.query(availability="out_of_stock")], ["PAN-2"])

    def test_ranges_include_boundary_values(self):
        self.assertEqual([p.code for p in self.query(quantity_from=5, quantity_to=5)], ["CHAIR-1"])
        self.assertEqual([p.code for p in self.query(price_from=3000, price_to=3000)], ["PAN-2"])

    def test_multiple_values_are_or_within_one_filter(self):
        self.assertEqual(len(self.query(section="Мебель,Посуда", brand="Alpha")), 2)

    def test_sorting_and_server_pagination(self):
        params = {"page": 1, "page_size": 20, "sort": "price", "order": "desc"}
        items, pagination = paginated_products(self.db, params)
        self.assertEqual([p.code for p in items], ["TABLE-3", "PAN-2", "CHAIR-1"])
        self.assertEqual(pagination, {"page": 1, "pageSize": 20, "totalItems": 3, "totalPages": 1})

    def test_empty_result(self):
        self.assertEqual(self.query(search="несуществующий товар"), [])


if __name__ == "__main__":
    unittest.main()
