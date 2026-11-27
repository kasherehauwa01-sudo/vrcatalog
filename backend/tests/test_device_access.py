import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from argon2 import PasswordHasher
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import device_access
from app.api.routes import router
from app.db.session import Base, get_db
from app.models.catalog import DeviceCertificate


def csr():
    key = ec.generate_private_key(ec.SECP256R1())
    return x509.CertificateSigningRequestBuilder().subject_name(
        x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "local-device")])
    ).sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM).decode()


class DeviceAccessTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        ca_key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test issuing CA")])
        now = datetime.now(timezone.utc)
        ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
              .not_valid_after(now + timedelta(days=400))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .sign(ca_key, hashes.SHA256()))
        cert_path, key_path = Path(directory) / "issuer.crt", Path(directory) / "issuer.key"
        cert_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(ca_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        self.proxy_secret = "test-proxy-secret-used-with-local-tests"
        self.enterContext(patch.multiple(
            device_access.settings, device_ca_cert=str(cert_path), device_ca_key=str(key_path),
            device_proxy_secret=self.proxy_secret, admin_password_hash=PasswordHasher().hash("test-password"),
        ))
        self.crl_refresh = self.enterContext(
            patch.object(device_access, "refresh_device_crl")
        )
        self.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        app = FastAPI()
        for item in (router, device_access.router, device_access.proxy_router):
            app.include_router(item, prefix="/api")

        def get_test_db():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_db] = get_test_db
        self.client = self.enterContext(TestClient(app, base_url="https://testserver"))
        self.path = "/api/access/devices"
        self.details = {"name": "Ноутбук", "owner": "Администратор", "comment": "Тест"}

    def login(self):
        response = self.client.post("/api/admin/login", json={"password": "test-password"})
        self.assertEqual(response.status_code, 200, response.text)
        return {"X-CSRF-Token": response.json()["csrf_token"]}

    def verify(self, pem, **headers):
        return self.client.get("/api/access/verify", headers={
            "X-VR-Device-Secret": self.proxy_secret, "X-VR-Device-Verify": "SUCCESS",
            "X-VR-Device-Certificate": quote(pem, safe=""), **headers,
        })

    def assert_serial_stored(self, pem):
        cert = x509.load_pem_x509_certificate(pem.encode())
        with Session(self.engine) as db:
            row = db.query(DeviceCertificate).filter_by(
                fingerprint=device_access.fingerprint(cert)
            ).one()
            self.assertEqual(row.serial_number, format(cert.serial_number, "x"))

    def test_issue_requires_admin_and_csrf_and_proxy_rejects_forged_proof(self):
        payload = {**self.details, "pem": csr()}
        self.assertEqual(self.client.get(self.path).status_code, 401)
        self.assertEqual(self.client.post(self.path + "/issue", json=payload).status_code, 401)
        csrf = self.login()
        self.assertEqual(self.client.post(self.path + "/issue", json=payload).status_code, 403)
        result = self.client.post(self.path + "/issue", json=payload, headers=csrf)
        self.assertEqual(result.status_code, 201, result.text)
        pem = result.json()["certificate"]
        self.assert_serial_stored(pem)
        self.assertEqual(self.verify(pem, **{"X-VR-Device-Secret": "forged"}).status_code, 403)
        self.assertEqual(self.verify(pem, **{"X-VR-Device-Verify": "NONE"}).status_code, 403)
        self.assertEqual(self.verify("").status_code, 403)
        self.assertEqual(self.verify(pem).status_code, 204)
        self.assertIsNotNone(self.client.get(self.path).json()[0]["last_seen_at"])
        self.assertEqual(self.client.post(self.path + "/issue", json=payload, headers=csrf).status_code, 409)

    def test_register_replace_revoke_and_expire(self):
        csrf = self.login()
        original_csr = csr()
        pem = device_access.issue_certificate(original_csr).public_bytes(serialization.Encoding.PEM).decode()
        self.assertEqual(self.verify(pem).status_code, 403)
        self.assertEqual(self.client.post(self.path + "/register", json={**self.details, "pem": "invalid"}, headers=csrf).status_code, 422)
        registered = self.client.post(self.path + "/register", json={**self.details, "pem": pem}, headers=csrf)
        self.assertEqual(registered.status_code, 201, registered.text)
        device_id = registered.json()["id"]
        self.assert_serial_stored(pem)
        self.assertEqual(self.verify(pem).status_code, 204)
        edited = self.client.patch(f"{self.path}/{device_id}", json={**self.details, "name": "Мобильный"}, headers=csrf)
        self.assertEqual(edited.json()["name"], "Мобильный")
        duplicate_key = self.client.post(f"{self.path}/{device_id}/replace", json={"pem": original_csr}, headers=csrf)
        self.assertEqual(duplicate_key.status_code, 409)
        self.assertEqual(self.verify(pem).status_code, 204)
        replacement = self.client.post(f"{self.path}/{device_id}/replace", json={"pem": csr()}, headers=csrf)
        self.assertEqual(replacement.status_code, 201, replacement.text)
        self.assertTrue(replacement.json()["crl_updated"])
        self.crl_refresh.assert_called_once_with()
        self.assertEqual(self.verify(pem).status_code, 403)
        new = replacement.json()
        new_pem, new_id = new["certificate"], new["device"]["id"]
        self.assert_serial_stored(new_pem)
        self.assertEqual(self.verify(new_pem).status_code, 204)
        with Session(self.engine) as db:
            db.get(DeviceCertificate, new_id).expires_at = device_access.utc_now() - timedelta(hours=1)
            db.commit()
        self.assertEqual(self.verify(new_pem).status_code, 403)
        revoked = self.client.post(f"{self.path}/{new_id}/revoke", headers=csrf)
        self.assertEqual(revoked.json()["status"], "revoked")
        self.assertEqual(self.crl_refresh.call_count, 2)
        self.assertEqual(self.client.post(self.path + "/register", json={**self.details, "pem": pem}, headers=csrf).status_code, 409)


    def test_refresh_crl_requires_admin_and_csrf(self):
        url = self.path + "/refresh-crl"

        unauthenticated = self.client.post(url)
        self.assertIn(unauthenticated.status_code, (401, 403))
        self.crl_refresh.assert_not_called()

        csrf = self.login()
        without_csrf = self.client.post(url)
        self.assertIn(without_csrf.status_code, (401, 403))
        self.crl_refresh.assert_not_called()

        refreshed = self.client.post(url, headers=csrf)
        self.assertEqual(refreshed.status_code, 200)
        self.assertTrue(refreshed.json()["success"])
        self.crl_refresh.assert_called_once_with()

        self.crl_refresh.side_effect = device_access.HTTPException(
            status_code=503,
            detail="Обновление CRL не подтверждено",
        )
        failed = self.client.post(url, headers=csrf)
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(self.crl_refresh.call_count, 2)

    def test_revoke_when_crl_refresh_fails(self):
        csrf = self.login()
        issued = self.client.post(
            self.path + "/issue",
            json={**self.details, "pem": csr()},
            headers=csrf,
        )
        self.assertEqual(issued.status_code, 201, issued.text)
        device_id = issued.json()["device"]["id"]

        self.crl_refresh.side_effect = device_access.HTTPException(
            status_code=503,
            detail="CRL update failed",
        )

        url = f"{self.path}/{device_id}/revoke"
        failed = self.client.post(url, headers=csrf)
        self.assertEqual(failed.status_code, 503)

        with Session(self.engine) as db:
            self.assertIsNotNone(
                db.get(DeviceCertificate, device_id).revoked_at
            )

        self.crl_refresh.side_effect = None
        retried = self.client.post(url, headers=csrf)
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(retried.json()["status"], "revoked")
        self.assertEqual(self.crl_refresh.call_count, 2)


    def test_replace_when_crl_refresh_fails(self):
        csrf = self.login()
        issued = self.client.post(
            self.path + "/issue",
            json={**self.details, "pem": csr()},
            headers=csrf,
        )
        self.assertEqual(issued.status_code, 201, issued.text)
        old_id = issued.json()["device"]["id"]
        old_pem = issued.json()["certificate"]

        self.crl_refresh.side_effect = device_access.HTTPException(
            status_code=503,
            detail="CRL update failed",
        )

        replaced = self.client.post(
            f"{self.path}/{old_id}/replace",
            json={"pem": csr()},
            headers=csrf,
        )
        self.assertEqual(replaced.status_code, 201, replaced.text)

        result = replaced.json()
        self.assertFalse(result["crl_updated"])
        self.assertTrue(result["warning"])
        self.assertTrue(result["certificate"])
        self.assertNotEqual(result["device"]["id"], old_id)
        self.assertEqual(self.verify(old_pem).status_code, 403)
        self.assertEqual(self.verify(result["certificate"]).status_code, 204)
        self.crl_refresh.assert_called_once_with()
