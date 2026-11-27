import base64
import io
import logging
import secrets
import re
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from argon2 import PasswordHasher
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core import admin_auth
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
        self.enterContext(patch.dict(admin_auth._attempts, clear=True))
        self.enterContext(patch.dict(admin_auth._operations, clear=True))
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
            environment="production",
        ))
        self.crl_refresh = self.enterContext(
            patch.object(device_access, "refresh_device_crl")
        )
        self.engine = create_engine(f"sqlite:///{directory}/devices.db")
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
        self.password = "local-test-passphrase"
        self.credentials = {"operation_id": secrets.token_hex(16)}
        self.ca = ca
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

    def issue(self, csrf):
        response = self.client.post(self.path + "/issue-package", json={**self.details, "operation_id": secrets.token_hex(16)}, headers=csrf)
        return self.unpack(response)

    def unpack(self, response):
        self.assertEqual(response.status_code, 201, response.text if not response.is_success else "")
        payload = response.json()
        self.password = payload["password"]
        _, cert, _ = pkcs12.load_key_and_certificates(base64.b64decode(payload["pkcs12_base64"]), self.password.encode())
        return payload["device"]["id"], cert.public_bytes(serialization.Encoding.PEM).decode()

    def prepare(self, original_id, csrf):
        return self.client.post(f"{self.path}/{original_id}/replacements/prepare", json={"operation_id": secrets.token_hex(16)}, headers=csrf)

    def replacement_action(self, original_id, replacement_id, action, csrf):
        return self.client.post(f"{self.path}/{original_id}/replacements/{replacement_id}/{action}", headers=csrf)

    def test_issue_requires_admin_and_csrf_and_creates_encrypted_pkcs12(self):
        payload = {**self.details, **self.credentials}
        url = self.path + "/issue-package"
        self.assertEqual(self.client.get(self.path).status_code, 401)
        self.assertEqual(self.client.post(url, json=payload).status_code, 401)
        csrf = self.login()
        self.assertEqual(self.client.post(url, json=payload).status_code, 403)
        result = self.client.post(url, json=payload, headers=csrf)
        device_id, pem = self.unpack(result)
        self.assertEqual(result.headers["content-type"], "application/json")
        self.assertTrue(result.json()["filename"].endswith(".p12"))
        self.assertRegex(self.password, r"^[A-Za-z0-9]{32}$")
        self.assertNotIn(self.password, str(result.headers))
        self.assertIn("no-store", result.headers["cache-control"])
        self.assertEqual(result.headers["pragma"], "no-cache")
        self.assertEqual(result.headers["expires"], "0")
        self.assertEqual(result.headers["x-content-type-options"], "nosniff")
        with self.assertRaises(ValueError):
            pkcs12.load_key_and_certificates(base64.b64decode(result.json()["pkcs12_base64"]), b"incorrect-password")
        key, cert, issuers = pkcs12.load_key_and_certificates(base64.b64decode(result.json()["pkcs12_base64"]), self.password.encode())
        self.assertEqual(key.key_size, 3072)
        self.assertEqual(device_access.key_bytes(key.public_key()), device_access.key_bytes(cert.public_key()))
        self.assertEqual(issuers, [self.ca])
        cert.verify_directly_issued_by(self.ca)
        self.assertFalse(cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
        self.assertTrue(cert.extensions.get_extension_for_class(x509.KeyUsage).value.digital_signature)
        self.assertIn(ExtendedKeyUsageOID.CLIENT_AUTH, cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value)
        with Session(self.engine) as db:
            row = db.execute(select(DeviceCertificate.__table__)).mappings().one()
            self.assertEqual(row["id"], device_id)
            self.assertEqual(row["serial_number"], format(cert.serial_number, "x"))
            self.assertEqual(row["fingerprint"], device_access.fingerprint(cert))
            self.assertEqual(set(row), {
                "id", "name", "owner", "comment", "fingerprint", "public_key_fingerprint",
                "common_name", "serial_number", "expires_at", "revoked_at", "last_seen_at",
                "replaces_id", "activated_at", "crl_pending",
            })
            self.assertNotIn(self.password, str(row))
        self.assertEqual(self.verify(pem, **{"X-VR-Device-Secret": "forged"}).status_code, 403)
        self.assertEqual(self.verify(pem, **{"X-VR-Device-Verify": "NONE"}).status_code, 403)
        self.assertEqual(self.verify("").status_code, 403)
        self.assertEqual(self.verify(pem).status_code, 204)
        self.assertIsNotNone(self.client.get(self.path).json()[0]["last_seen_at"])

    def test_manual_password_and_csr_legacy_issue_return_no_secret(self):
        csrf = self.login()
        for credentials in (
            {"password": "too short", "password_confirmation": "too short"},
            {"password": self.password, "password_confirmation": "mismatched-password"},
            {"password": self.password + "\x00", "password_confirmation": self.password + "\x00"},
            {"password": self.password},
            {"password": "я" * 64, "password_confirmation": "я" * 64},
        ):
            response = self.client.post(self.path + "/issue-package", json={**self.details, **credentials}, headers=csrf)
            self.assertEqual(response.status_code, 422, response.text)
            self.assertNotIn(self.password, response.text)
        legacy = self.client.post(self.path + "/issue", json={**self.details, "pem": csr()}, headers=csrf)
        self.assertEqual(legacy.status_code, 422)
        self.assertEqual(self.client.get(self.path).json(), [])

    def test_existing_legacy_certificate_stays_active_and_expiry_is_enforced(self):
        csrf = self.login()
        cert = device_access.issue_certificate(csr())
        pem = cert.public_bytes(serialization.Encoding.PEM).decode()
        self.assertEqual(self.verify(pem).status_code, 403)
        result = self.client.post(self.path + "/register", json={**self.details, "pem": pem}, headers=csrf)
        self.assertEqual(result.status_code, 201, result.text)
        original_id = result.json()["id"]
        with Session(self.engine) as db:
            db.get(DeviceCertificate, original_id).serial_number = None
            db.commit()
        self.assertEqual(self.verify(pem).status_code, 204)
        edited = self.client.patch(f"{self.path}/{original_id}", json={**self.details, "name": "Мобильный"}, headers=csrf)
        self.assertEqual(edited.json()["name"], "Мобильный")
        with Session(self.engine) as db:
            db.get(DeviceCertificate, original_id).expires_at = device_access.utc_now() - timedelta(hours=1)
            db.commit()
        self.assertEqual(self.verify(pem).status_code, 403)

    def test_prepare_confirm_and_repeat(self):
        csrf = self.login()
        original_id, old_pem = self.issue(csrf)
        old_style = self.client.post(f"{self.path}/{original_id}/replace", json={"pem": csr()}, headers=csrf)
        self.assertEqual(old_style.status_code, 422)
        self.assertEqual(self.prepare(original_id, {}).status_code, 403)
        replacement_id, new_pem = self.unpack(self.prepare(original_id, csrf))
        self.assertEqual(self.prepare(original_id, csrf).status_code, 409)
        self.assertEqual(self.verify(old_pem).status_code, 204)
        self.assertEqual(self.verify(new_pem).status_code, 403)
        self.assertEqual(self.client.post(self.path + "/register", json={**self.details, "pem": new_pem}, headers=csrf).status_code, 409)
        self.crl_refresh.assert_not_called()
        self.assertEqual(self.replacement_action(original_id, replacement_id, "confirm", {}).status_code, 403)
        self.assertEqual(self.replacement_action(original_id, original_id, "confirm", csrf).status_code, 404)
        confirmed = self.replacement_action(original_id, replacement_id, "confirm", csrf)
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["status"], "active")
        self.assertEqual(self.verify(old_pem).status_code, 403)
        self.assertEqual(self.verify(new_pem).status_code, 204)
        self.assertEqual(self.replacement_action(original_id, replacement_id, "confirm", csrf).status_code, 200)
        self.assertEqual(self.replacement_action(original_id, replacement_id, "cancel", csrf).status_code, 409)
        self.crl_refresh.assert_called_once_with()

    def test_cancel_and_revoke_prevent_activation(self):
        csrf = self.login()
        original_id, old_pem = self.issue(csrf)
        replacement_id, cancelled_pem = self.unpack(self.prepare(original_id, csrf))
        for _ in range(2):
            self.assertEqual(self.replacement_action(original_id, replacement_id, "cancel", csrf).status_code, 200)
        self.assertEqual(self.replacement_action(original_id, replacement_id, "confirm", csrf).status_code, 409)
        self.assertEqual(self.verify(cancelled_pem).status_code, 403)
        self.assertEqual(self.verify(old_pem).status_code, 204)
        replacement_id, new_pem = self.unpack(self.prepare(original_id, csrf))
        self.assertEqual(self.client.post(f"{self.path}/{original_id}/revoke", headers=csrf).status_code, 200)
        self.assertEqual(self.replacement_action(original_id, replacement_id, "confirm", csrf).status_code, 409)
        self.assertEqual(self.prepare(original_id, csrf).status_code, 409)
        self.assertEqual(self.verify(new_pem).status_code, 403)
        self.crl_refresh.assert_called_once_with()

    def test_concurrent_preparation_creates_one_pending_certificate(self):
        csrf = self.login()
        original_id, old_pem = self.issue(csrf)
        barrier = Barrier(2, timeout=10)
        def prepare_simultaneously():
            barrier.wait()
            return self.prepare(original_id, csrf)
        with ThreadPoolExecutor(2) as executor:
            futures = [executor.submit(prepare_simultaneously) for _ in range(2)]
            self.assertCountEqual([future.result().status_code for future in futures], [201, 409])
        self.assertEqual(self.verify(old_pem).status_code, 204)
        with Session(self.engine) as db:
            replacement = db.scalars(select(DeviceCertificate).where(DeviceCertificate.replaces_id == original_id)).one()
            self.assertIsNone(replacement.activated_at)

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
        device_id, _ = self.issue(csrf)

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


    def test_confirm_when_crl_refresh_fails_retries_publication_only(self):
        csrf = self.login()
        original_id, old_pem = self.issue(csrf)
        replacement_id, new_pem = self.unpack(self.prepare(original_id, csrf))
        self.crl_refresh.side_effect = device_access.HTTPException(status_code=503, detail="CRL update failed")
        failed = self.replacement_action(original_id, replacement_id, "confirm", csrf)
        self.assertEqual(failed.status_code, 503)
        self.assertTrue(self.client.get(self.path).json()[0]["crl_pending"])
        self.assertEqual(self.verify(old_pem).status_code, 403)
        self.assertEqual(self.verify(new_pem).status_code, 204)
        self.crl_refresh.side_effect = None
        with patch.object(device_access, "encrypted_package", side_effect=AssertionError("Unexpected generation")):
            retried = self.replacement_action(original_id, replacement_id, "confirm", csrf)
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertFalse(retried.json()["crl_pending"])
        self.assertEqual(self.crl_refresh.call_count, 2)

    def test_secure_password_generation_is_unique_and_alphanumeric(self):
        passwords = {device_access.generate_package_password() for _ in range(100)}
        self.assertEqual(len(passwords), 100)
        self.assertTrue(all(re.fullmatch(r"[A-Za-z0-9]{32}", password) for password in passwords))

    def test_replay_returns_conflict_without_regeneration_or_secret(self):
        csrf = self.login()
        payload = {**self.details, **self.credentials}
        first = self.client.post(self.path + '/issue-package', json=payload, headers=csrf)
        self.unpack(first)
        with patch.object(device_access, 'encrypted_package', side_effect=AssertionError('Repeated issuance')):
            for endpoint in ('/issue-package', '/issue'):
                repeated = self.client.post(self.path + endpoint, json=payload, headers=csrf)
                self.assertEqual(repeated.status_code, 409)
                self.assertNotIn(self.password, repeated.text)
        listing = self.client.get(self.path).json()
        self.assertEqual(len(listing), 1)
        self.assertNotIn(self.password, str(listing))
        self.assertNotIn('pkcs12_base64', str(listing))

    def test_concurrent_replay_only_issues_one_package(self):
        csrf = self.login()
        payload = {**self.details, **self.credentials}
        barrier = Barrier(2, timeout=10)
        def issue_simultaneously():
            barrier.wait()
            return self.client.post(self.path + '/issue-package', json=payload, headers=csrf)
        with ThreadPoolExecutor(2) as executor:
            results = list(executor.map(lambda _: issue_simultaneously(), range(2)))
        self.assertCountEqual([result.status_code for result in results], [201, 409])
        self.assertEqual(len(self.client.get(self.path).json()), 1)

    def test_failures_do_not_register_device_or_log_secret_and_can_retry(self):
        csrf = self.login()
        payload = {**self.details, **self.credentials}
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        secret = 'A1' * 16
        for target in ('rsa.generate_private_key', 'pkcs12.serialize_key_and_certificates'):
            with patch.object(device_access, 'generate_package_password', return_value=secret), \
                 patch('app.api.device_access.' + target, side_effect=ValueError(secret)):
                response = self.client.post(self.path + '/issue-package', json=payload, headers=csrf)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn(secret, response.text)
            self.assertNotIn(secret, output.getvalue())
            self.assertEqual(self.client.get(self.path).json(), [])
        success = self.client.post(self.path + '/issue-package', json=payload, headers=csrf)
        self.unpack(success)
        self.assertNotIn(self.password, output.getvalue())

    def test_replacement_has_new_password_and_failed_preparation_keeps_old_access(self):
        csrf = self.login()
        original_id, pem = self.issue(csrf)
        old_password = self.password
        with patch.object(device_access.pkcs12, 'serialize_key_and_certificates', side_effect=ValueError('test failure')):
            self.assertEqual(self.prepare(original_id, csrf).status_code, 503)
        self.assertEqual(self.verify(pem).status_code, 204)
        self.assertEqual(len(self.client.get(self.path).json()), 1)
        result = self.prepare(original_id, csrf)
        self.unpack(result)
        self.assertNotEqual(old_password, self.password)
        with self.assertRaises(ValueError):
            pkcs12.load_key_and_certificates(base64.b64decode(result.json()['pkcs12_base64']), old_password.encode())
        self.assertEqual(self.verify(pem).status_code, 204)
        self.crl_refresh.assert_not_called()

    def test_empty_metadata_and_missing_operation_are_rejected_without_redirect(self):
        csrf = self.login()
        self.assertEqual(self.client.get(self.path, follow_redirects=False).status_code, 200)
        for values in ({}, {'name': '', 'owner': 'Owner'}, {'name': 'Name', 'owner': ' '}, self.details):
            response = self.client.post(self.path + '/issue-package', json=values, headers=csrf, follow_redirects=False)
            self.assertEqual(response.status_code, 422)
        with patch.object(device_access, 'encrypted_package', side_effect=AssertionError('Unexpected signing')):
            response = self.client.post(self.path + '/issue-package', content=b'x' * 9000, headers=csrf)
            self.assertEqual(response.status_code, 413)
