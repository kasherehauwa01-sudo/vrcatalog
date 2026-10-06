import socket
import unittest
from unittest.mock import patch

from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.admin_auth import _attempts
from app.core.config import Settings, settings
from app.db.session import Base, get_db
from app.main import app
from app.models.catalog import AdminSession, XmlServerSetting
from app.services.photo_report import _NoRedirect, _validate_public_host


class SecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(cls.engine)

        def override_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        cls.original_hash = settings.admin_password_hash
        settings.admin_password_hash = PasswordHasher().hash("correct-test-password")

    @classmethod
    def tearDownClass(cls):
        settings.admin_password_hash = cls.original_hash
        app.dependency_overrides.clear()
        cls.engine.dispose()

    def setUp(self):
        _attempts.clear()
        with Session(self.engine) as db:
            db.query(AdminSession).delete()
            db.query(XmlServerSetting).delete()
            db.add(XmlServerSetting(host="ftp.test", username="user", encrypted_password="encrypted-value"))
            db.commit()
        self.client = TestClient(app)

    def login(self):
        response = self.client.post("/api/admin/login", json={"password": "correct-test-password"})
        self.assertEqual(response.status_code, 200)
        return response.json()["csrf_token"]

    def test_admin_session_and_csrf(self):
        self.assertEqual(self.client.get("/api/xml-server-settings").status_code, 401)
        csrf = self.login()
        self.assertEqual(self.client.get("/api/xml-server-settings").status_code, 200)
        rejected = self.client.put("/api/history/monthly-promotion/settings", json={"save_for_next_month": True})
        accepted = self.client.put(
            "/api/history/monthly-promotion/settings",
            json={"save_for_next_month": True},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(accepted.status_code, 200)

    def test_wrong_password_and_login_rate_limit(self):
        for _ in range(10):
            self.assertEqual(self.client.post("/api/admin/login", json={"password": "wrong"}).status_code, 401)
        self.assertEqual(self.client.post("/api/admin/login", json={"password": "wrong"}).status_code, 429)

    def test_ftp_password_is_not_returned_and_empty_update_preserves_it(self):
        csrf = self.login()
        before = self.client.get("/api/xml-server-settings").json()
        self.assertNotIn("password", before)
        self.assertTrue(before["password_configured"])
        response = self.client.put(
            "/api/xml-server-settings",
            headers={"X-CSRF-Token": csrf},
            json={**{key: before[key] for key in ("protocol", "host", "port", "username", "xml_dir", "connection_attempts", "retry_delay_seconds")}, "password": ""},
        )
        self.assertEqual(response.status_code, 200)
        with Session(self.engine) as db:
            self.assertEqual(db.query(XmlServerSetting).one().encrypted_password, "encrypted-value")

    def test_private_and_local_image_hosts_are_rejected(self):
        cases = ["127.0.0.1", "::1", "10.0.0.1", "172.16.0.1", "192.168.0.1", "169.254.1.1", "fc00::1", "fe80::1"]
        for address in cases:
            with self.subTest(address=address), patch("socket.getaddrinfo", return_value=[(socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]):
                with self.assertRaises(ValueError):
                    _validate_public_host("https://example.test/image.jpg")
        with self.assertRaises(ValueError):
            _validate_public_host("https://localhost/image.jpg")

    def test_http_redirect_is_never_followed_implicitly(self):
        handler = _NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, "Found", {}, "http://127.0.0.1/private"))

    def test_production_rejects_placeholder_secrets(self):
        with self.assertRaises(ValueError):
            Settings(
                _env_file=None,
                environment="production",
                secret_key="change-me",
                internal_api_token="short",
                admin_password_hash="invalid",
                enable_api_docs=False,
                cors_origins="https://kvasmix.ru",
            )

    def test_oversized_xml_is_rejected_and_catalog_remains_public(self):
        self.assertEqual(self.client.get("/api/products/search").status_code, 200)
        csrf = self.login()
        original_limit = settings.max_xml_upload_mb
        settings.max_xml_upload_mb = 0
        try:
            response = self.client.post(
                "/api/import",
                headers={"X-CSRF-Token": csrf},
                files={"file": ("catalog.xml", b"<catalog/>", "application/xml")},
            )
        finally:
            settings.max_xml_upload_mb = original_limit
        self.assertEqual(response.status_code, 413)
