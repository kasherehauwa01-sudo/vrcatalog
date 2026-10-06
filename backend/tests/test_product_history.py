import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.admin_auth import require_admin
from app.db.session import Base, get_db
from app.main import app
from app.models.catalog import HistorySetting, HistorySnapshot, HistorySnapshotItem, HistorySnapshotItemPrice, Price, Product, ProductTypeSetting, ServiceLog
from app.services.product_history import create_snapshot, run_history_snapshot_if_due, scheduled_period


class ProductHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True,
        )
        Base.metadata.create_all(cls.engine)

        def override_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[require_admin] = lambda: True
        cls.client = TestClient(app)
        cls.original_token = settings.internal_api_token
        settings.internal_api_token = "history-test-token"

    @classmethod
    def tearDownClass(cls):
        settings.internal_api_token = cls.original_token
        app.dependency_overrides.clear()
        cls.engine.dispose()

    def setUp(self):
        with Session(self.engine) as db:
            for model in (HistorySnapshotItemPrice, HistorySnapshotItem, HistorySnapshot, HistorySetting, Price, Product, ProductTypeSetting, ServiceLog):
                db.query(model).delete()
            db.add(ProductTypeSetting(code="PROMO", name="Акция месяца"))
            db.add_all([
                Product(
                    code="P-1", article="A-1", name="Товар акции", product_type="PROMO", search_text="",
                    prices=[
                        Price(price_type="ЦенаПредыдущаяРозничная", price_value=1000),
                        Price(price_type="ЦенаРозничная", price_value=799),
                        Price(price_type="ЦенаОптовая", price_value=700),
                        Price(price_type="ЦенаКорпоративная", price_value=750),
                        Price(price_type="ЦенаПредыдущаяОптовая", price_value=900),
                        Price(price_type="ЦенаПредыдущаяКорпоративная", price_value=950),
                    ],
                ),
                Product(
                    code="P-2", article=None, name="Без базовой цены", product_type="PROMO", search_text="",
                    prices=[Price(price_type="ЦенаРозничная", price_value=399)],
                ),
                Product(code="P-3", article="A-3", name="Обычный", product_type="OTHER", search_text=""),
            ])
            db.commit()

    def test_snapshot_uses_mapping_prices_and_keeps_missing_price(self):
        with Session(self.engine) as db:
            snapshot, created = create_snapshot(db, date(2026, 10, 1), "manual")
            db.commit()
            items = db.query(HistorySnapshotItem).filter_by(snapshot_id=snapshot.id).order_by(HistorySnapshotItem.code).all()

            self.assertTrue(created)
            self.assertEqual(snapshot.item_count, 2)
            self.assertEqual([item.code for item in items], ["P-1", "P-2"])
            self.assertEqual(items[0].base_price, Decimal("1000.00"))
            self.assertEqual(items[0].promo_price, Decimal("799.00"))
            self.assertIsNone(items[1].base_price)
            self.assertEqual(items[1].promo_price, Decimal("399.00"))
            self.assertEqual(items[0].product_type_code, "PROMO")
            self.assertEqual(items[0].product_type_name, "Акция месяца")
            self.assertEqual(
                {price.price_type: price.price_value for price in items[0].prices},
                {
                    "ЦенаПредыдущаяРозничная": Decimal("1000.00"),
                    "ЦенаРозничная": Decimal("799.00"),
                    "ЦенаОптовая": Decimal("700.00"),
                    "ЦенаКорпоративная": Decimal("750.00"),
                    "ЦенаПредыдущаяОптовая": Decimal("900.00"),
                    "ЦенаПредыдущаяКорпоративная": Decimal("950.00"),
                },
            )

    def test_repeated_run_is_idempotent_and_snapshot_is_immutable(self):
        with Session(self.engine) as db:
            first, created = create_snapshot(db, date(2026, 10, 1), "manual")
            db.commit()
            original_id = first.id
            product = db.query(Product).filter_by(code="P-1").one()
            product.name = "Новое имя"
            product.prices[0].price_value = 9999
            product.product_type = "OTHER"
            db.commit()

            existing, created_again = create_snapshot(db, date(2026, 10, 1), "automatic")
            db.commit()
            item = db.query(HistorySnapshotItem).filter_by(snapshot_id=original_id, code="P-1").one()

            self.assertTrue(created)
            self.assertFalse(created_again)
            self.assertEqual(existing.id, original_id)
            self.assertEqual(db.query(HistorySnapshot).count(), 1)
            self.assertEqual(item.name, "Товар акции")
            self.assertEqual(item.base_price, Decimal("1000.00"))
            self.assertEqual(
                {price.price_type: price.price_value for price in item.prices}["ЦенаПредыдущаяРозничная"],
                Decimal("1000.00"),
            )

    def test_schedule_targets_next_month_and_catches_up_before_28th(self):
        self.assertEqual(scheduled_period(date(2026, 9, 28), True), date(2026, 10, 1))
        self.assertEqual(scheduled_period(date(2026, 10, 5), True), date(2026, 10, 1))
        self.assertEqual(scheduled_period(date(2026, 9, 28), False), date(2026, 9, 1))

        with patch("app.services.product_history.SessionLocal", side_effect=lambda: Session(self.engine)):
            run_history_snapshot_if_due(datetime(2026, 10, 5, 12, 0))
            run_history_snapshot_if_due(datetime(2026, 10, 6, 12, 0))
        with Session(self.engine) as db:
            self.assertEqual(db.query(HistorySnapshot).count(), 1)
            self.assertEqual(db.query(HistorySnapshot).one().period, date(2026, 10, 1))

    def test_failure_rolls_back_snapshot_and_items(self):
        with Session(self.engine) as db, patch("app.services.product_history._price", side_effect=RuntimeError("test failure")):
            with self.assertRaises(RuntimeError):
                create_snapshot(db, date(2026, 10, 1), "manual")
            db.rollback()
            self.assertEqual(db.query(HistorySnapshot).count(), 0)
            self.assertEqual(db.query(HistorySnapshotItem).count(), 0)

    def test_manual_and_internal_api_are_read_only_and_authorized(self):
        created = self.client.post("/api/history/monthly-promotion?period=2026-10")
        with Session(self.engine) as db:
            product = db.query(Product).filter_by(code="P-1").one()
            product.name = "Обновленное имя акции"
            next(price for price in product.prices if price.price_type == "ЦенаРозничная").price_value = 749
            db.commit()
        updated = self.client.post("/api/history/monthly-promotion?period=2026-10")
        unauthorized = self.client.get("/api/internal/history/monthly-promotion")
        periods = self.client.get(
            "/api/internal/history/monthly-promotion",
            headers={"X-Internal-Token": "history-test-token"},
        )
        detail = self.client.get(
            "/api/internal/history/monthly-promotion/2026-10",
            headers={"X-Internal-Token": "history-test-token"},
        )

        self.assertEqual(created.status_code, 200)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(periods.status_code, 200)
        self.assertEqual(periods.json()["items"][0]["period"], "2026-10")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["type"], "monthly_promotion")
        self.assertEqual(detail.json()["items"][0]["name"], "Обновленное имя акции")
        self.assertEqual(detail.json()["items"][0]["base_price"], "1000.00")
        self.assertEqual(detail.json()["items"][0]["promo_price"], "749.00")
        self.assertEqual(len(detail.json()["items"][0]["prices"]), 6)
