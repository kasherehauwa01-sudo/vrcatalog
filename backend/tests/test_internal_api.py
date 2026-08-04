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
from app.models.catalog import Product, ProductProperty, ServiceLog, Stock, WarehouseSetting


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
            db.query(Stock).delete()
            db.query(ProductProperty).delete()
            db.query(Product).delete()
            db.query(WarehouseSetting).delete()
            db.add_all(
                [
                    WarehouseSetting(code="MAIN", name="Основной склад"),
                    WarehouseSetting(code="AVIATORS", name="Авиаторов"),
                ]
            )
            db.add_all(
                [
                    Product(
                        code="P-1",
                        article="10001",
                        name="Товар А",
                        manager="Иванов Иван",
                        search_text="",
                        stocks=[
                            Stock(warehouse="MAIN", quantity=3),
                            Stock(warehouse="MAIN", quantity=4),
                            Stock(warehouse="AVIATORS", quantity=2),
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
                "name": "Товар А",
                "manager_id": None,
                "manager_name": "Иванов Иван",
                "stocks": [
                    {
                        "warehouse": "AVIATORS",
                        "warehouse_name": "Авиаторов",
                        "quantity": 2.0,
                    },
                    {
                        "warehouse": "MAIN",
                        "warehouse_name": "Основной склад",
                        "quantity": 7.0,
                    },
                ],
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
                "name": "Базовый товар",
                "manager_id": None,
                "manager_name": "Базовый менеджер",
                "stocks": [
                    {
                        "warehouse": "MAIN",
                        "warehouse_name": "Основной склад",
                        "quantity": 0.0,
                    }
                ],
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
        self.assertEqual(items[0]["stocks"][0]["quantity"], 5.0)
        self.assertEqual(items[1]["stocks"][0]["quantity"], 0.0)
        self.assertEqual(items[2]["stocks"], [])
        self.assertEqual(items[1], items[3])

    def test_include_zero_stock_rejects_non_boolean_value(self):
        response = self.client.post(
            "/api/internal/products/by-articles",
            headers=self.headers,
            json={"articles": ["ОКА-27134"], "include_zero_stock": "not-a-boolean"},
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
        self.assertNotIn("test-internal-token", log.message)
        self.assertNotIn("10001", log.message)

    def test_batch_uses_one_product_select_for_duplicate_articles(self):
        product_selects = 0
        stock_selects = 0
        warehouse_selects = 0

        def count_product_selects(_conn, _cursor, statement, _parameters, _context, _many):
            nonlocal product_selects, stock_selects, warehouse_selects
            normalized = statement.lower()
            if normalized.lstrip().startswith("select") and "from products" in normalized:
                product_selects += 1
            if normalized.lstrip().startswith("select") and "from stocks" in normalized:
                stock_selects += 1
            if normalized.lstrip().startswith("select") and "from warehouse_settings" in normalized:
                warehouse_selects += 1

        event.listen(self.engine, "before_cursor_execute", count_product_selects)
        try:
            response = self.client.post(
                "/api/internal/products/by-articles",
                headers=self.headers,
                json={"articles": ["10001", "10001", "10002"]},
            )
        finally:
            event.remove(self.engine, "before_cursor_execute", count_product_selects)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(product_selects, 1)
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
