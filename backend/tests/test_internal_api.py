import json
import time
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.session import Base, get_db
from app.main import app
from app.models.catalog import Price, Product, ProductImage, ProductProperty, ServiceLog, Stock, WarehouseSetting


class InternalProductApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        Base.metadata.create_all(cls.engine)

        def override_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        cls.client = TestClient(app)
        cls.original_token = settings.internal_api_token
        settings.internal_api_token = "test-internal-token"

    @classmethod
    def tearDownClass(cls):
        settings.internal_api_token = cls.original_token
        app.dependency_overrides.clear()
        cls.engine.dispose()

    def setUp(self):
        with Session(self.engine) as db:
            db.query(ServiceLog).delete()
            db.query(Price).delete()
            db.query(Stock).delete()
            db.query(ProductImage).delete()
            db.query(ProductProperty).delete()
            db.query(Product).delete()
            db.query(WarehouseSetting).delete()
            db.add_all(
                [
                    WarehouseSetting(code="MAIN", name="Основной склад"),
                    WarehouseSetting(code="BAKHTUROVA", name="Бахтурова"),
                    WarehouseSetting(code="AVIATORS", name="Авиаторов Зал+Склад"),
                ]
            )
            db.add_all(
                [
                    Product(
                        code="P-1",
                        article="10001",
                        name="Товар А",
                        manager="Иванов Иван",
                        section="  <b>Средства&nbsp; для бассейнов</b>  ",
                        search_text="",
                        stocks=[
                            Stock(warehouse="MAIN", quantity=3),
                            Stock(warehouse="MAIN", quantity=4),
                            Stock(warehouse="BAKHTUROVA", quantity=2),
                            Stock(warehouse="AVIATORS", quantity=13),
                        ],
                    ),
                    Product(
                        code="P-2",
                        article="10002",
                        name="Товар Б",
                        manager=None,
                        search_text="",
                    ),
                    Product(
                        code="P-3",
                        article="00123",
                        name="Товар с ведущими нулями",
                        manager="Петров Пётр",
                        section="Семена",
                        search_text="",
                    ),
                    Product(
                        code="ОКА-27134",
                        article=None,
                        name="Базовый товар",
                        manager="  Базовый менеджер  ",
                        quantity=0,
                        search_text="",
                        stocks=[Stock(warehouse="MAIN", quantity=0)],
                    ),
                    Product(
                        code="P-POSITIVE",
                        article="POSITIVE",
                        name="Товар в наличии",
                        manager="Менеджер наличия",
                        quantity=5,
                        search_text="",
                        stocks=[Stock(warehouse="MAIN", quantity=5)],
                    ),
                    Product(
                        code="P-EMPTY-MANAGER",
                        article="EMPTY-MANAGER",
                        name="Товар без менеджера",
                        manager="   ",
                        quantity=0,
                        search_text="",
                    ),
                    Product(
                        code="P-PROPERTY-MANAGER",
                        article="PROPERTY-MANAGER",
                        name="Товар с менеджером в характеристике",
                        manager=None,
                        quantity=0,
                        search_text="",
                        properties=[
                            ProductProperty(name="  мЕнЕдЖеР ", value="  Менеджер свойства  ")
                        ],
                    ),
                ]
            )
            db.commit()

    def test_products_filter_by_normalized_property_for_sales_journal(self):
        with Session(self.engine) as db:
            products = db.query(Product).order_by(Product.id).all()
            products[0].properties.append(ProductProperty(name="HoReCa", value="HoReCa"))
            products[1].properties.append(ProductProperty(name=" horeca ", value=" HORECA "))
            products[2].properties.append(ProductProperty(name="HoReCa", value="Нет"))
            db.commit()

        response = self.client.get(
            "/api/products",
            params={"property": " HORECA ", "property_value": "horeca", "limit": 10000},
            headers={"Authorization": "Bearer test-internal-token"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual({item["code"] for item in payload}, {"P-1", "P-2"})
        self.assertTrue(all(item["article"] for item in payload))
        self.assertTrue(all(next(iter(item["properties"])).strip().casefold() == "horeca" for item in payload))

    def test_products_property_filter_returns_empty_list(self):
        response = self.client.get(
            "/api/products",
            params={"property": "HoReCa", "property_value": "HoReCa"},
            headers={"Authorization": "Bearer test-internal-token"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_products_filter_supports_very_long_property_value(self):
        long_value = "x" * 3501
        with Session(self.engine) as db:
            product = db.query(Product).filter(Product.code == "P-1").one()
            product.properties.append(
                ProductProperty(name="  Long property  ", value=f"  {long_value.upper()}  ")
            )
            db.commit()

        response = self.client.get(
            "/api/products",
            params={"property": "LONG PROPERTY", "property_value": long_value},
            headers={"Authorization": "Bearer test-internal-token"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["code"] for item in response.json()], ["P-1"])

    def test_products_property_filter_authorization(self):
        params = {"property": "HoReCa", "property_value": "HoReCa"}
        self.assertEqual(self.client.get("/api/products", params=params).status_code, 401)
        self.assertEqual(
            self.client.get("/api/products", params=params, headers={"Authorization": "Bearer wrong"}).status_code,
            403,
        )
        self.assertEqual(
            self.client.get("/api/products", params=params, headers={"X-Internal-Token": "test-internal-token"}).status_code,
            200,
        )

    def test_products_property_filter_requires_both_parameters(self):
        response = self.client.get("/api/products", params={"property": "HoReCa"})
        self.assertEqual(response.status_code, 422)

    def test_products_without_property_filter_remains_public(self):
        response = self.client.get("/api/products", params={"limit": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)

    def test_products_property_filter_combines_with_search_and_pagination(self):
        with Session(self.engine) as db:
            products = db.query(Product).order_by(Product.id).all()
            for product in products:
                product.properties.append(ProductProperty(name="HoReCa", value="HoReCa"))
            products[0].search_text = "нужный товар"
            products[1].search_text = "нужный товар"
            products[2].search_text = "другой товар"
            db.commit()

        response = self.client.get(
            "/api/products",
            params={"property": "HoReCa", "property_value": "HoReCa", "search": "нужный", "limit": 1, "offset": 1},
            headers={"Authorization": "Bearer test-internal-token"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["code"] for item in response.json()], ["P-2"])

    def test_products_property_filter_has_fixed_query_count(self):
        with Session(self.engine) as db:
            for product in db.query(Product).all():
                product.properties.append(ProductProperty(name="HoReCa", value="HoReCa"))
            db.commit()
        statements = []

        def record_statement(*args):
            statements.append(args[2])

        event.listen(self.engine, "before_cursor_execute", record_statement)
        try:
            response = self.client.get(
                "/api/products",
                params={"property": "HoReCa", "property_value": "HoReCa", "limit": 10000},
                headers={"Authorization": "Bearer test-internal-token"},
            )
        finally:
            event.remove(self.engine, "before_cursor_execute", record_statement)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 7)
        self.assertLessEqual(len(statements), 8)

    def test_integration_filter_metadata_uses_real_catalog_values(self):
        with Session(self.engine) as db:
            products = db.query(Product).order_by(Product.id).all()
            products[0].brand = "Regent"
            products[1].brand = "Regent"
            products[0].properties.append(ProductProperty(name="Диаметр", value="24 см"))
            db.commit()

        response = self.client.get(
            "/api/integration/product-filters",
            headers={"Authorization": "Bearer test-internal-token"},
        )

        self.assertEqual(response.status_code, 200)
        filters = {item["key"]: item for item in response.json()["filters"]}
        self.assertEqual(filters["brand"]["label"], "Бренд")
        self.assertEqual(filters["brand"]["type"], "multi_select")
        self.assertEqual(filters["brand"]["options"], [{"value": "Regent", "label": "Regent"}])
        self.assertEqual(filters["property:Диаметр"]["options"][0]["value"], "24 см")
        options_response = self.client.get(
            "/api/integration/product-filters/property%3A%D0%94%D0%B8%D0%B0%D0%BC%D0%B5%D1%82%D1%80/options",
            params={"search": "24", "page": 1, "page_size": 1},
            headers={"Authorization": "Bearer test-internal-token"},
        )
        self.assertEqual(options_response.status_code, 200)
        self.assertEqual(options_response.json()["items"], [{"value": "24 см", "label": "24 см"}])
        self.assertEqual(options_response.json()["total"], 1)

    def test_integration_search_combines_property_filters_with_or_and(self):
        with Session(self.engine) as db:
            products = db.query(Product).order_by(Product.id).all()
            products[0].brand = "Regent"
            products[0].properties.extend([
                ProductProperty(name="Диаметр", value="24"),
                ProductProperty(name="Материал корпуса", value="Сталь"),
            ])
            products[1].brand = "Rondell"
            products[1].properties.extend([
                ProductProperty(name="Диаметр", value="26"),
                ProductProperty(name="Материал корпуса", value="Сталь"),
            ])
            products[2].brand = "Другой"
            products[2].properties.append(ProductProperty(name="Диаметр", value="24"))
            db.commit()

        response = self.client.post(
            "/api/integration/products/search",
            headers={"Authorization": "Bearer test-internal-token"},
            json={
                "filters": {
                    "brand": ["Regent", "Rondell"],
                    "property:Диаметр": ["24", "26"],
                    "property:Материал корпуса": ["Сталь"],
                },
                "page": 1,
                "page_size": 50,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 2)
        self.assertEqual({item["code"] for item in payload["items"]}, {"P-1", "P-2"})
        self.assertTrue(all(isinstance(item["code"], str) for item in payload["items"]))

    def test_integration_search_returns_public_primary_image_url(self):
        with Session(self.engine) as db:
            products = db.query(Product).order_by(Product.id).all()
            products[0].images.extend([
                ProductImage(image_order=2, image_url="images/second.jpg"),
                ProductImage(image_order=1, image_url="images/Папка/Первое фото.jpg"),
            ])
            products[0].properties.append(ProductProperty(name="HoReCa", value="HoReCa"))
            products[1].images.append(
                ProductImage(image_order=1, image_url="https://cdn.example.test/Фото товара.jpg")
            )
            db.commit()

        response = self.client.post(
            "/api/integration/products/search",
            headers={"Authorization": "Bearer test-internal-token"},
            json={"filters": {}, "page": 1, "page_size": 500},
        )
        self.assertEqual(response.status_code, 200)
        items = {item["code"]: item for item in response.json()["items"]}
        self.assertEqual(
            items["P-1"]["image_url"],
            "https://volgorost.ru/upload/import_images/images/"
            "%D0%9F%D0%B0%D0%BF%D0%BA%D0%B0/%D0%9F%D0%B5%D1%80%D0%B2%D0%BE%D0%B5%20%D1%84%D0%BE%D1%82%D0%BE.jpg",
        )
        self.assertEqual(
            items["P-2"]["image_url"],
            "https://cdn.example.test/%D0%A4%D0%BE%D1%82%D0%BE%20%D1%82%D0%BE%D0%B2%D0%B0%D1%80%D0%B0.jpg",
        )
        self.assertIsNone(items["P-3"]["image_url"])
        self.assertEqual(items["P-1"]["article"], "10001")
        self.assertNotIn("token", items["P-1"]["image_url"].casefold())

        horeca_response = self.client.post(
            "/api/integration/products/search",
            headers={"Authorization": "Bearer test-internal-token"},
            json={
                "filters": {"property:HoReCa": ["HoReCa"]},
                "page": 1,
                "page_size": 500,
            },
        )
        self.assertEqual(horeca_response.status_code, 200)
        self.assertEqual(horeca_response.json()["total"], 1)
        self.assertEqual(horeca_response.json()["items"][0]["code"], "P-1")
        self.assertTrue(horeca_response.json()["items"][0]["image_url"].startswith("https://"))

    def test_integration_search_supports_search_pagination_sort_and_exclusions(self):
        with Session(self.engine) as db:
            products = db.query(Product).order_by(Product.id).all()
            products[0].name = "сковорода Альфа"
            products[0].code = "000123"
            products[1].name = "сковорода Бета"
            products[1].article = "ART-0002"
            db.commit()

        code_response = self.client.post(
            "/api/integration/products/search",
            headers={"Authorization": "Bearer test-internal-token"},
            json={"search": "000123"},
        )
        article_response = self.client.post(
            "/api/integration/products/search",
            headers={"Authorization": "Bearer test-internal-token"},
            json={"search": "art-0002"},
        )
        page_response = self.client.post(
            "/api/integration/products/search",
            headers={"Authorization": "Bearer test-internal-token"},
            json={
                "search": "СКОВОРОДА",
                "page": 1,
                "page_size": 1,
                "sort_by": "name",
                "sort_dir": "asc",
                "excluded": [{"code": "000123"}],
            },
        )

        self.assertEqual(code_response.json()["items"][0]["code"], "000123")
        self.assertEqual(article_response.json()["items"][0]["article"], "ART-0002")
        self.assertEqual(page_response.status_code, 200)
        self.assertEqual(page_response.json()["total"], 1)
        self.assertEqual(page_response.json()["items"][0]["code"], "P-2")
        self.assertEqual(page_response.json()["pages"], 1)

    def test_integration_api_validates_auth_filters_and_sorting(self):
        endpoint = "/api/integration/products/search"
        self.assertEqual(self.client.post(endpoint, json={}).status_code, 401)
        self.assertEqual(
            self.client.post(endpoint, json={}, headers={"Authorization": "Bearer wrong"}).status_code,
            403,
        )
        unknown = self.client.post(
            endpoint,
            json={"filters": {"unknown": ["value"]}},
            headers={"Authorization": "Bearer test-internal-token"},
        )
        invalid_sort = self.client.post(
            endpoint,
            json={"sort_by": "drop table"},
            headers={"Authorization": "Bearer test-internal-token"},
        )
        self.assertEqual(unknown.status_code, 422)
        self.assertEqual(unknown.json()["detail"], "Неизвестный фильтр: unknown")
        self.assertEqual(invalid_sort.status_code, 422)
        empty = self.client.post(
            endpoint,
            json={"search": "товар, которого нет"},
            headers={"Authorization": "Bearer test-internal-token"},
        )
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json()["items"], [])
        self.assertEqual(empty.json()["total"], 0)

    def test_integration_search_query_count_does_not_depend_on_product_count(self):
        statements = []

        def record_statement(*args):
            statements.append(args[2])

        event.listen(self.engine, "before_cursor_execute", record_statement)
        try:
            response = self.client.post(
                "/api/integration/products/search",
                json={"page_size": 50},
                headers={"Authorization": "Bearer test-internal-token"},
            )
        finally:
            event.remove(self.engine, "before_cursor_execute", record_statement)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 7)
        self.assertLessEqual(len(statements), 4)

    def test_integration_batch_info_requires_authorization(self):
        response = self.client.post(
            "/api/integration/products/batch-info",
            json={"products": [{"code": "P-1"}]},
        )
        self.assertEqual(response.status_code, 401)

    def test_integration_batch_info_matches_by_priority_and_returns_metadata(self):
        with Session(self.engine) as db:
            products = db.query(Product).order_by(Product.id).all()
            products[0].properties.append(ProductProperty(name=" horeca ", value=" HORECA "))
            products[0].images.extend([
                ProductImage(image_order=2, image_url="images/second.jpg"),
                ProductImage(image_order=1, image_url="images/first.jpg"),
            ])
            db.commit()

        response = self.client.post(
            "/api/integration/products/batch-info",
            headers={"Authorization": "Bearer test-internal-token"},
            json={
                "products": [
                    {"code": " p-1 ", "article": "10002"},
                    {"code": "missing", "article": " 10002 "},
                    {"code": "P-3", "article": None},
                    {"code": "not-found", "article": "also-missing"},
                    {"code": "P-1", "article": None},
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual([item["code"] for item in items], ["P-1", "P-2", "P-3"])
        self.assertTrue(items[0]["horeca"])
        self.assertFalse(items[1]["horeca"])
        self.assertEqual(
            items[0]["image_url"],
            "https://volgorost.ru/upload/import_images/images/first.jpg",
        )
        self.assertIsNone(items[1]["image_url"])
        self.assertEqual(items[0]["article"], "10001")
        self.assertEqual(items[0]["name"], "Товар А")
        self.assertEqual(items[1]["properties"], [])
        self.assertEqual(items[1]["stocks"], [])
        self.assertEqual(items[1]["prices"], [])

    def test_integration_batch_info_returns_complete_product_data(self):
        with Session(self.engine) as db:
            first, second = db.query(Product).order_by(Product.id).limit(2).all()
            first.brand = "  Прямой бренд  "
            first.manufacturer = " Фабрика "
            first.section = " Посуда "
            first.material = None
            first.product_type = None
            first.properties.extend([
                ProductProperty(name=" Цвет ", value=" Белый "),
                ProductProperty(name="Материал", value=" Фарфор "),
                ProductProperty(name="Материал", value="Фарфор"),
                ProductProperty(name="Subcategory", value="Тарелки"),
                ProductProperty(name=" ", value="не возвращать"),
                ProductProperty(name="Пустое", value="   "),
            ])
            first.images.extend([
                ProductImage(image_order=5, image_url="images/later.jpg"),
                ProductImage(image_order=1, image_url="images/first.jpg"),
            ])
            first.prices.extend([
                Price(price_type="Розничная", price_value=1490),
                Price(price_type="Оптовая", price_value=1190),
            ])
            second.properties.append(ProductProperty(name="Brand", value="Другой бренд"))
            second.stocks.append(Stock(warehouse="MAIN", quantity=99))
            second.prices.append(Price(price_type="Розничная", price_value=10))
            db.commit()

        response = self.client.post(
            "/api/integration/products/batch-info",
            headers={"Authorization": "Bearer test-internal-token"},
            json={"products": [{"code": "p-1"}, {"article": "10002"}]},
        )

        self.assertEqual(response.status_code, 200)
        items = {item["code"]: item for item in response.json()["items"]}
        first_item = items["P-1"]
        self.assertEqual(first_item["image_url"], "https://volgorost.ru/upload/import_images/images/first.jpg")
        self.assertEqual(first_item["brand"], "Прямой бренд")
        self.assertEqual(first_item["manufacturer"], "Фабрика")
        self.assertEqual(first_item["category"], "Посуда")
        self.assertEqual(first_item["subcategory"], "Тарелки")
        self.assertEqual(first_item["material"], "Фарфор")
        self.assertEqual(
            first_item["properties"],
            [
                {"name": "Subcategory", "value": "Тарелки"},
                {"name": "Материал", "value": "Фарфор"},
                {"name": "Цвет", "value": "Белый"},
            ],
        )
        self.assertEqual(
            first_item["stocks"],
            [
                {"warehouse": "Авиаторов Зал+Склад", "quantity": 13.0},
                {"warehouse": "Бахтурова", "quantity": 2.0},
                {"warehouse": "Основной склад", "quantity": 7.0},
            ],
        )
        self.assertEqual(
            first_item["prices"],
            [
                {"name": "Оптовая", "value": 1190.0, "currency": "RUB"},
                {"name": "Розничная", "value": 1490.0, "currency": "RUB"},
            ],
        )
        self.assertEqual(items["P-2"]["properties"], [{"name": "Brand", "value": "Другой бренд"}])
        self.assertEqual(items["P-2"]["stocks"], [{"warehouse": "Основной склад", "quantity": 99.0}])
        self.assertEqual(len(items["P-2"]["prices"]), 1)

    def test_integration_batch_info_rejects_invalid_token(self):
        response = self.client.post(
            "/api/integration/products/batch-info",
            headers={"Authorization": "Bearer wrong"},
            json={"products": [{"code": "P-1"}]},
        )
        self.assertEqual(response.status_code, 401)

    def test_integration_batch_info_validates_size_and_empty_identifiers(self):
        headers = {"Authorization": "Bearer test-internal-token"}
        empty_identifiers = self.client.post(
            "/api/integration/products/batch-info",
            headers=headers,
            json={"products": [{"code": "   ", "article": ""}]},
        )
        too_many = self.client.post(
            "/api/integration/products/batch-info",
            headers=headers,
            json={"products": [{"code": f"P-{index}"} for index in range(5001)]},
        )
        self.assertEqual(empty_identifiers.status_code, 422)
        self.assertEqual(too_many.status_code, 422)

    def test_integration_batch_info_uses_bounded_query_count(self):
        def request_with_query_count(products):
            statements = []

            def record_statement(*args):
                statements.append(args[2])

            event.listen(self.engine, "before_cursor_execute", record_statement)
            try:
                response = self.client.post(
                    "/api/integration/products/batch-info",
                    headers={"Authorization": "Bearer test-internal-token"},
                    json={"products": products},
                )
            finally:
                event.remove(self.engine, "before_cursor_execute", record_statement)
            return response, len(statements)

        single_response, single_count = request_with_query_count([{"code": "P-1"}])
        large_response, large_count = request_with_query_count([
            {"code": "P-1" if index == 0 else f"missing-{index}"}
            for index in range(5000)
        ])

        self.assertEqual(single_response.status_code, 200)
        self.assertEqual(large_response.status_code, 200)
        self.assertEqual(len(large_response.json()["items"]), 1)
        self.assertEqual(single_count, 5)
        self.assertEqual(large_count, single_count)

    @property
    def headers(self):
        return {"X-Internal-Token": "test-internal-token"}

    def test_get_returns_found_product_and_only_contract_fields(self):
        response = self.client.get(
            "/api/internal/products/by-article/10001", headers=self.headers
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "ok": True,
                "article": "10001",
                "found": True,
                "product_id": response.json()["product_id"],
                "code": "P-1",
                "name": "Товар А",
                "manager_id": None,
                "manager_name": "Иванов Иван",
                "stocks": [],
            },
        )

    def test_batch_preserves_order_duplicates_missing_items_and_leading_zeroes(self):
        response = self.client.post(
            "/api/internal/products/by-articles",
            headers=self.headers,
            json={"articles": ["10002", "missing", "00123", "10002"]},
        )

        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual([item["article"] for item in items], ["10002", "missing", "00123", "10002"])
        self.assertEqual([item["found"] for item in items], [True, False, True, True])
        self.assertEqual(items[0]["manager_name"], "")
        self.assertEqual(items[2]["manager_name"], "Петров Пётр")
        self.assertEqual(items[0], items[3])

    def test_batch_returns_all_missing(self):
        response = self.client.post(
            "/api/internal/products/by-articles",
            headers=self.headers,
            json={"articles": ["none-1", "none-2"]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(not item["found"] for item in response.json()["items"]))
        self.assertTrue(all(item["manager_name"] == "" for item in response.json()["items"]))
        self.assertTrue(all(item["stocks"] == [] for item in response.json()["items"]))

    def test_include_section_returns_normalized_section_and_null_for_missing(self):
        response = self.client.post(
            "/api/internal/products/by-articles",
            headers=self.headers,
            json={"articles": ["10001", "10002", "missing"], "include_section": True},
        )

        self.assertEqual(response.status_code, 200)
        found, without_section, missing = response.json()["items"]
        self.assertEqual(found["section"], "Средства для бассейнов")
        self.assertIsNone(without_section["section"])
        self.assertFalse(missing["found"])
        self.assertIsNone(missing["section"])

    def test_section_is_absent_when_not_requested_for_backward_compatibility(self):
        response = self.client.post(
            "/api/internal/products/by-articles",
            headers=self.headers,
            json={"articles": ["10001"]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("section", response.json()["items"][0])

    def test_multiple_products_receive_their_own_sections_without_duplicates(self):
        response = self.client.post(
            "/api/internal/products/by-articles",
            headers=self.headers,
            json={"articles": ["00123", "10001", "00123"], "include_section": True},
        )

        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual([item["article"] for item in items], ["00123", "10001", "00123"])
        self.assertEqual([item["section"] for item in items], ["Семена", "Средства для бассейнов", "Семена"])

    def test_include_zero_stock_returns_exact_article_and_trimmed_manager(self):
        response = self.client.post(
            "/api/internal/products/by-articles",
            headers=self.headers,
            json={"articles": ["ОКА-27134"], "include_zero_stock": True},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["items"][0],
            {
                "article": "ОКА-27134",
                "found": True,
                "product_id": response.json()["items"][0]["product_id"],
                "code": "ОКА-27134",
                "name": "Базовый товар",
                "manager_id": None,
                "manager_name": "Базовый менеджер",
                "stocks": [],
            },
        )

    def test_zero_stock_keeps_previous_behavior_when_flag_is_false_or_missing(self):
        for payload in (
            {"articles": ["ОКА-27134"]},
            {"articles": ["ОКА-27134"], "include_zero_stock": False},
            {"articles": ["ОКА-27134"], "include_zero_stock": "false"},
            {"articles": ["ОКА-27134"], "include_zero_stock": 0},
        ):
            with self.subTest(payload=payload):
                response = self.client.post(
                    "/api/internal/products/by-articles",
                    headers=self.headers,
                    json=payload,
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["items"][0]["found"])

    def test_positive_stock_and_empty_manager_contract(self):
        response = self.client.post(
            "/api/internal/products/by-articles",
            headers=self.headers,
            json={"articles": ["POSITIVE", "EMPTY-MANAGER"], "include_zero_stock": True},
        )

        self.assertEqual(response.status_code, 200)
        positive, empty_manager = response.json()["items"]
        self.assertTrue(positive["found"])
        self.assertEqual(positive["manager_name"], "Менеджер наличия")
        self.assertTrue(empty_manager["found"])
        self.assertEqual(empty_manager["manager_name"], "")

    def test_manager_can_be_read_from_case_insensitive_property_name(self):
        response = self.client.post(
            "/api/internal/products/by-articles",
            headers=self.headers,
            json={"articles": ["PROPERTY-MANAGER"], "include_zero_stock": True},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["manager_name"], "Менеджер свойства")

    def test_mixed_batch_preserves_input_articles_and_results(self):
        articles = ["POSITIVE", "ОКА-27134", "MISSING", "ОКА-27134"]
        response = self.client.post(
            "/api/internal/products/by-articles",
            headers=self.headers,
            json={"articles": articles, "include_zero_stock": True},
        )

        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual([item["article"] for item in items], articles)
        self.assertEqual([item["found"] for item in items], [True, True, False, True])
        self.assertEqual(items[0]["stocks"], [])
        self.assertEqual(items[1]["stocks"], [])
        self.assertEqual(items[2]["stocks"], [])
        self.assertEqual(items[1], items[3])


    def test_include_warehouse_stocks_returns_canonical_numeric_quantities(self):
        response = self.client.post(
            "/api/internal/products/by-articles",
            headers=self.headers,
            json={
                "articles": ["10001"],
                "include_zero_stock": True,
                "include_warehouse_stocks": True,
                "include_section": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        item = response.json()["items"][0]
        stocks_by_name = {stock["warehouse_name"]: stock for stock in item["stocks"]}
        self.assertEqual(item["code"], "P-1")
        self.assertEqual(item["section"], "Средства для бассейнов")
        self.assertIn("Бахтурова", stocks_by_name)
        self.assertIn("Авиаторов Зал+Склад", stocks_by_name)
        self.assertGreater(stocks_by_name["Бахтурова"]["quantity"], 0)
        self.assertGreater(stocks_by_name["Авиаторов Зал+Склад"]["quantity"], 0)
        self.assertIsInstance(stocks_by_name["Бахтурова"]["quantity"], (int, float))
        self.assertEqual(stocks_by_name["Основной склад"]["quantity"], 7.0)
        self.assertEqual(stocks_by_name["Авиаторов Зал+Склад"]["quantity"], 13.0)

    def test_include_warehouse_stocks_adds_zero_rows_for_known_warehouses(self):
        response = self.client.post(
            "/api/internal/products/by-articles",
            headers=self.headers,
            json={
                "articles": ["ОКА-27134"],
                "include_zero_stock": True,
                "include_warehouse_stocks": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        stocks_by_name = {
            stock["warehouse_name"]: stock["quantity"]
            for stock in response.json()["items"][0]["stocks"]
        }
        self.assertEqual(stocks_by_name["Основной склад"], 0.0)
        self.assertEqual(stocks_by_name["Бахтурова"], 0.0)
        self.assertEqual(stocks_by_name["Авиаторов Зал+Склад"], 0.0)

    def test_boolean_flags_reject_non_boolean_values(self):
        for payload in (
            {"articles": ["ОКА-27134"], "include_zero_stock": "not-a-boolean"},
            {"articles": ["ОКА-27134"], "include_warehouse_stocks": "not-a-boolean"},
            {"articles": ["ОКА-27134"], "include_section": "not-a-boolean"},
        ):
            with self.subTest(payload=payload):
                response = self.client.post(
                    "/api/internal/products/by-articles",
                    headers=self.headers,
                    json=payload,
                )
                self.assertEqual(response.status_code, 422)

    def test_invalid_json_wrong_identifier_type_and_oversized_batch_return_422(self):
        invalid_json = self.client.post(
            "/api/internal/products/by-articles",
            headers={**self.headers, "Content-Type": "application/json"},
            content="{",
        )
        wrong_type = self.client.post(
            "/api/internal/products/by-articles",
            headers=self.headers,
            json={"articles": "ОКА-27134"},
        )
        oversized = self.client.post(
            "/api/internal/products/by-articles",
            headers=self.headers,
            json={"articles": [f"ITEM-{index}" for index in range(1001)]},
        )

        self.assertEqual(invalid_json.status_code, 422)
        self.assertEqual(wrong_type.status_code, 422)
        self.assertEqual(oversized.status_code, 422)

    def test_batch_accepts_empty_list(self):
        response = self.client.post(
            "/api/internal/products/by-articles",
            headers=self.headers,
            json={"articles": []},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "items": []})

    def test_missing_and_invalid_tokens_return_401(self):
        missing = self.client.get("/api/internal/products/by-article/10001")
        invalid = self.client.post(
            "/api/internal/products/by-articles",
            headers={"X-Internal-Token": "wrong"},
            json={"articles": ["10001"]},
        )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(invalid.status_code, 401)

    def test_internal_routes_are_absent_from_openapi(self):
        paths = self.client.get("/api/openapi.json").json()["paths"]
        self.assertFalse(any("/internal/products" in path for path in paths))

    def test_request_log_contains_metrics_but_not_token_or_articles(self):
        self.client.post(
            "/api/internal/products/by-articles",
            headers=self.headers,
            json={"articles": ["10001", "missing"]},
        )

        with Session(self.engine) as db:
            log = db.query(ServiceLog).one()
            metrics = json.loads(log.message)
        self.assertEqual(log.event, "internal_api_request")
        self.assertEqual(metrics["article_count"], 2)
        self.assertEqual(metrics["found_count"], 1)
        self.assertEqual(metrics["not_found_count"], 1)
        self.assertEqual(metrics["status_code"], 200)
        self.assertFalse(metrics["include_warehouse_stocks"])
        self.assertFalse(metrics["include_zero_stock"])
        self.assertFalse(metrics["include_section"])
        self.assertEqual(metrics["section_count"], 0)
        self.assertEqual(metrics["section_missing_count"], 0)
        self.assertEqual(metrics["stock_rows_count"], 0)
        self.assertEqual(metrics["stock_diagnostics"], "warehouse stocks were not requested")
        self.assertNotIn("test-internal-token", log.message)
        self.assertNotIn("10001", log.message)


    def test_request_log_contains_warehouse_stock_diagnostics(self):
        self.client.post(
            "/api/internal/products/by-articles",
            headers=self.headers,
            json={
                "articles": ["10001", "10002"],
                "include_zero_stock": True,
                "include_warehouse_stocks": True,
                "include_section": True,
            },
        )

        with Session(self.engine) as db:
            metrics = json.loads(db.query(ServiceLog).one().message)
        self.assertTrue(metrics["include_warehouse_stocks"])
        self.assertTrue(metrics["include_zero_stock"])
        self.assertTrue(metrics["include_section"])
        self.assertEqual(metrics["section_count"], 1)
        self.assertEqual(metrics["section_missing_count"], 1)
        self.assertEqual(metrics["stock_rows_count"], 6)
        self.assertEqual(
            metrics["warehouses"],
            ["Авиаторов Зал+Склад", "Бахтурова", "Основной склад"],
        )
        self.assertEqual(metrics["stock_diagnostics"], "warehouse stocks added to response")

    def test_batch_uses_one_product_select_for_duplicate_articles(self):
        product_selects = 0
        property_selects = 0
        stock_selects = 0
        warehouse_selects = 0

        def count_product_selects(_conn, _cursor, statement, _parameters, _context, _many):
            nonlocal product_selects, property_selects, stock_selects, warehouse_selects
            normalized = statement.lower()
            if normalized.lstrip().startswith("select") and "from products" in normalized:
                product_selects += 1
            if normalized.lstrip().startswith("select") and "from product_properties" in normalized:
                property_selects += 1
            if normalized.lstrip().startswith("select") and "from stocks" in normalized:
                stock_selects += 1
            if normalized.lstrip().startswith("select") and "from warehouse_settings" in normalized:
                warehouse_selects += 1

        event.listen(self.engine, "before_cursor_execute", count_product_selects)
        try:
            response = self.client.post(
                "/api/internal/products/by-articles",
                headers=self.headers,
                json={"articles": ["10001", "10001", "10002"], "include_section": True},
            )
        finally:
            event.remove(self.engine, "before_cursor_execute", count_product_selects)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(product_selects, 1)
        self.assertEqual(property_selects, 1)
        self.assertEqual(stock_selects, 1)
        self.assertEqual(warehouse_selects, 1)

    def test_batch_performance_for_10_100_and_1000_articles(self):
        with Session(self.engine) as db:
            db.add_all(
                Product(
                    code=f"LOAD-{index}",
                    article=f"LOAD-{index:04d}",
                    name=f"Нагрузочный товар {index}",
                    manager="Менеджер",
                    search_text="",
                )
                for index in range(1000)
            )
            db.commit()

        timings = {}
        for count in (10, 100, 1000):
            started_at = time.perf_counter()
            response = self.client.post(
                "/api/internal/products/by-articles",
                headers=self.headers,
                json={"articles": [f"LOAD-{index:04d}" for index in range(count)]},
            )
            timings[count] = time.perf_counter() - started_at
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()["items"]), count)
            self.assertTrue(all(item["found"] for item in response.json()["items"]))

        print(f"Internal API timings (seconds): {timings}")


if __name__ == "__main__":
    unittest.main()
