import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.catalog import MailSetting, NotificationEmailHistory, NotificationScenarioSetting, Product, ProductTypeChange
from app.services.monthly_promotion import PROMOTION_VALUE, build_preview, encrypt_password, run_scenario


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
        for model in (NotificationEmailHistory, ProductTypeChange, Product, MailSetting, NotificationScenarioSetting):
            self.db.query(model).delete()
        self.product = Product(code="P-1", article="ARTICLE-1", name="Семена тестовые", product_type="Обычный", search_text="")
        self.db.add(self.product)
        self.db.commit()

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


if __name__ == "__main__":
    unittest.main()
