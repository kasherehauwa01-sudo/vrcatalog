import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.importer.xml_importer import XMLCatalogImporter
from app.models.catalog import MailSetting, NotificationEmailHistory, NotificationScenarioSetting, Product, ProductPromotionState, ProductTypeChange
from app.services.monthly_promotion import PROMOTION_VALUE, build_preview, consolidate_changes, encrypt_password, initialize_promotion_snapshot, normalize_month_promo, run_scenario


class FakeSmtp:
    sent = []

    def __enter__(self): return self
    def __exit__(self, *_args): return None
    def send_message(self, message): self.sent.append(message)


class MonthlyPromotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", future=True)
        Base.metadata.create_all(cls.engine)

    def setUp(self):
        FakeSmtp.sent = []
        self.db = Session(self.engine)
        for model in (NotificationEmailHistory, ProductTypeChange, ProductPromotionState, Product, MailSetting, NotificationScenarioSetting):
            self.db.query(model).delete()
        self.product = Product(code="P-1", article="ARTICLE-1", name="Семена тестовые", product_type="Обычный", search_text="")
        self.db.add(self.product)
        self.db.commit()
        initialize_promotion_snapshot(self.db)

    def tearDown(self):
        self.db.close()

    def configure(self):
        self.db.add(MailSetting(smtp_host="smtp.test", smtp_port=587, username="user", encrypted_password=encrypt_password("secret"), sender_email="catalog@test.local"))
        self.db.add(NotificationScenarioSetting(code="monthly_promotion", enabled=True, send_time="22:00", recipients_json=json.dumps(["one@test.local", "two@test.local"])))
        self.db.commit()

    def test_tracks_only_transitions_to_and_from_monthly_promotion(self):
        self.db.info["change_source"] = "manual"
        self.product.product_type = PROMOTION_VALUE
        self.db.commit()
        self.product.product_type = "Обычный"
        self.db.commit()
        self.product.product_type = "Другой"
        self.db.commit()

        changes = self.db.query(ProductTypeChange).order_by(ProductTypeChange.id).all()
        self.assertEqual([(item.old_value, item.new_value) for item in changes], [("Обычный", PROMOTION_VALUE), (PROMOTION_VALUE, "Обычный")])
        self.assertTrue(all(item.source == "manual" for item in changes))

    def test_success_marks_changes_processed_and_does_not_resend(self):
        self.configure()
        self.product.product_type = PROMOTION_VALUE
        self.db.commit()
        with patch("app.services.monthly_promotion._smtp", return_value=FakeSmtp()):
            first = run_scenario(self.db)
            second = run_scenario(self.db)

        self.assertEqual(first["status"], "sent")
        self.assertEqual(second["status"], "empty")
        self.assertEqual(len(FakeSmtp.sent), 1)
        self.assertTrue(self.db.query(ProductTypeChange).one().processed)
        self.assertIsNone(self.db.query(ProductTypeChange).one().claim_token)
        history = self.db.query(NotificationEmailHistory).one()
        self.assertEqual(history.status, "sent")
        self.assertIn("Добавлены в Акцию месяца", history.body_html)
        self.assertEqual(json.loads(history.recipients_json), ["one@test.local", "two@test.local"])

    def test_smtp_error_keeps_change_unprocessed_for_retry(self):
        self.configure()
        self.product.product_type = PROMOTION_VALUE
        self.db.commit()
        with patch("app.services.monthly_promotion.send_email", side_effect=RuntimeError("SMTP unavailable")):
            result = run_scenario(self.db)

        self.assertEqual(result["status"], "error")
        self.assertFalse(self.db.query(ProductTypeChange).one().processed)
        self.assertIsNone(self.db.query(ProductTypeChange).one().claim_token)
        history = self.db.query(NotificationEmailHistory).one()
        self.assertEqual(history.status, "error")
        self.assertEqual(history.error_message, "SMTP unavailable")

    def test_preview_contains_added_and_removed_sections(self):
        self.db.add_all([
            ProductTypeChange(product_id=self.product.id, article="A", product_name="Добавлен", old_value="Обычный", new_value=PROMOTION_VALUE, source="api"),
            ProductTypeChange(product_id=self.product.id, article="B", product_name="Исключён", old_value=PROMOTION_VALUE, new_value="Обычный", source="xml"),
        ])
        self.db.commit()
        html = build_preview(self.db.query(ProductTypeChange).all())
        self.assertIn("Добавлены в Акцию месяца", html)
        self.assertIn("Исключены из Акции месяца", html)

    def test_same_promotion_state_is_idempotent_across_many_flushes(self):
        self.product.product_type = PROMOTION_VALUE
        self.db.commit()
        for _ in range(100):
            self.product.name = f"Имя {_}"
            self.db.commit()
        self.assertEqual(self.db.query(ProductTypeChange).count(), 1)

    def test_real_return_to_promotion_creates_three_transitions(self):
        for value in (PROMOTION_VALUE, "Обычный", PROMOTION_VALUE):
            self.product.product_type = value
            self.db.commit()
        self.assertEqual(
            [(normalize_month_promo(item.old_value), normalize_month_promo(item.new_value)) for item in self.db.query(ProductTypeChange).order_by(ProductTypeChange.id)],
            [(False, True), (True, False), (False, True)],
        )

    def test_initial_snapshot_does_not_generate_notifications(self):
        self.db.query(ProductPromotionState).delete()
        self.db.query(ProductTypeChange).delete()
        self.db.add_all([
            Product(code=f"INIT-{index}", article=f"INIT-{index}", name=f"Товар {index}", product_type=PROMOTION_VALUE if index < 20 else "Обычный", search_text="")
            for index in range(99)
        ])
        self.db.commit()
        self.assertEqual(initialize_promotion_snapshot(self.db), 100)
        self.assertEqual(self.db.query(ProductPromotionState).count(), 100)
        self.assertEqual(self.db.query(ProductTypeChange).count(), 0)

    def test_duplicate_rows_with_same_timestamp_are_consolidated(self):
        changed_at = self.product.updated_at
        duplicates = [
            ProductTypeChange(product_id=self.product.id, article="202013", product_name="Скор от болезней", old_value="Обычный", new_value=PROMOTION_VALUE, source="xml", changed_at=changed_at)
            for _ in range(4)
        ]
        self.assertEqual(len(consolidate_changes(duplicates)), 1)

    def test_duplicate_article_in_one_source_batch_creates_one_event(self):
        duplicate = Product(code="P-2", article="ARTICLE-1", name="Другая карточка", product_type="Обычный", search_text="")
        self.db.add(duplicate)
        self.db.commit()
        self.db.info["promotion_article_owner"] = {"ARTICLE-1": "P-1"}
        self.product.product_type = PROMOTION_VALUE
        duplicate.product_type = PROMOTION_VALUE
        self.db.commit()
        self.assertEqual(self.db.query(ProductTypeChange).count(), 1)

    def test_conflicting_chain_is_reduced_to_final_real_state(self):
        events = [
            ProductTypeChange(id=1, product_id=self.product.id, article="1", product_name="Товар", old_value="Обычный", new_value=PROMOTION_VALUE, source="xml"),
            ProductTypeChange(id=2, product_id=self.product.id, article="1", product_name="Товар", old_value=PROMOTION_VALUE, new_value="Обычный", source="xml"),
            ProductTypeChange(id=3, product_id=self.product.id, article="1", product_name="Товар", old_value="Обычный", new_value=PROMOTION_VALUE, source="xml"),
        ]
        self.assertEqual([item.id for item in consolidate_changes(events)], [3])

    def test_promo_normalization(self):
        for value in (PROMOTION_VALUE, " акция   месяца ", "АКЦИЯ МЕСЯЦА", True, 1, "1", "Да"):
            self.assertTrue(normalize_month_promo(value))
        for value in (None, "", "Обычный", False, 0):
            self.assertFalse(normalize_month_promo(value))

    def test_missing_xml_product_type_does_not_clear_confirmed_state(self):
        self.product.product_type = PROMOTION_VALUE
        self.db.commit()
        parsed = Product(code=self.product.code, article=self.product.article, name=self.product.name, product_type=None, search_text="")
        XMLCatalogImporter()._sync_product_scalars(self.product, parsed)
        self.db.commit()
        self.assertEqual(self.product.product_type, PROMOTION_VALUE)
        self.assertEqual(self.db.query(ProductTypeChange).count(), 1)


if __name__ == "__main__":
    unittest.main()
