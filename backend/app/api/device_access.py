"""Device registry and the authorization endpoint for the HTTPS reverse proxy."""
import hashlib
import json
import socket
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import unquote

from cryptography import x509
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin
from app.core.config import settings
from app.db.session import get_db
from app.models.catalog import DeviceCertificate

router = APIRouter(prefix="/access/devices", dependencies=[Depends(require_admin)])
proxy_router = APIRouter(prefix="/access", include_in_schema=False)
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]


class DeviceDetails(BaseModel):
    name: Label
    owner: Label
    comment: str = Field(default="", max_length=500)


class IssueDevice(DeviceDetails):
    pem: str = Field(min_length=1, max_length=16384)


class DevicePem(BaseModel):
    pem: str = Field(min_length=1, max_length=16384)



def refresh_device_crl():
    """Synchronously publish the device revocation list."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(120)
            client.connect("/run/vrcatalog-crl/refresh.sock")
            client.sendall(b'{"action":"refresh"}\n')
            with client.makefile("rb") as stream:
                raw = stream.readline(8193)

        if not raw or len(raw) > 8192:
            raise ValueError("Invalid CRL service response")

        result = json.loads(raw)
        if not isinstance(result, dict) or result.get("success") is not True:
            raise RuntimeError("CRL service did not confirm publication")

    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Сертификат отозван в базе, но обновление CRL не подтверждено. Повторите операцию.",
        ) from exc



def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ca_certificate():
    try:
        ca = x509.load_pem_x509_certificate(Path(settings.device_ca_cert).read_bytes())
        if not ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            raise ValueError("not a CA")
        return ca
    except (OSError, ValueError, x509.ExtensionNotFound, UnsupportedAlgorithm) as exc:
        raise HTTPException(503, "Центр сертификации устройств не настроен") from exc


def key_bytes(key):
    return key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def issue_certificate(pem: str):
    try:
        csr = x509.load_pem_x509_csr(pem.encode())
        key = csr.public_key()
        if not csr.is_signature_valid or not (
            isinstance(key, rsa.RSAPublicKey) and key.key_size >= 2048
            or isinstance(key, ec.EllipticCurvePublicKey) and key.curve.name in {"secp256r1", "secp384r1", "secp521r1"}
        ):
            raise ValueError("unsupported key or CSR signature")
    except (ValueError, UnsupportedAlgorithm) as exc:
        raise HTTPException(422, "Требуется подписанный CSR с ключом RSA от 2048 бит или EC P-256/P-384/P-521") from exc
    ca = ca_certificate()
    try:
        signer = serialization.load_pem_private_key(Path(settings.device_ca_key).read_bytes(), password=None)
        if not isinstance(signer, (rsa.RSAPrivateKey, ec.EllipticCurvePrivateKey)):
            raise ValueError("unsupported signing key")
        if key_bytes(signer.public_key()) != key_bytes(ca.public_key()):
            raise ValueError("signing key does not match CA")
        now = datetime.now(timezone.utc)
        if not ca.not_valid_before_utc <= now < ca.not_valid_after_utc:
            raise ValueError("inactive CA")
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"device-{secrets.token_hex(8)}")])
        return (
            x509.CertificateBuilder()
            .subject_name(subject).issuer_name(ca.subject).public_key(key)
            .serial_number(x509.random_serial_number())
            .not_valid_before(max(now - timedelta(minutes=5), ca.not_valid_before_utc))
            .not_valid_after(min(now + timedelta(days=365), ca.not_valid_after_utc))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, False, False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=True)
            .sign(signer, hashes.SHA256())
        )
    except (OSError, ValueError, TypeError, UnsupportedAlgorithm) as exc:
        raise HTTPException(503, "Выпуск сертификатов устройств недоступен") from exc


def registered_certificate(pem: str):
    ca = ca_certificate()
    try:
        cert = x509.load_pem_x509_certificate(pem.encode())
        cert.verify_directly_issued_by(ca)
        extensions = cert.extensions
        if (
            extensions.get_extension_for_class(x509.BasicConstraints).value.ca
            or ExtendedKeyUsageOID.CLIENT_AUTH not in extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
            or not cert.not_valid_before_utc <= datetime.now(timezone.utc) < cert.not_valid_after_utc
        ):
            raise ValueError("not an active client certificate")
        return cert
    except (ValueError, TypeError, InvalidSignature, UnsupportedAlgorithm, x509.ExtensionNotFound, x509.DuplicateExtension) as exc:
        raise HTTPException(422, "Требуется действующий клиентский сертификат центра VR Catalog") from exc


def fingerprint(cert):
    return cert.fingerprint(hashes.SHA256()).hex()


def public_device(row):
    now = utc_now()
    return {
        "id": row.id, "name": row.name, "owner": row.owner, "comment": row.comment,
        "fingerprint": row.fingerprint, "common_name": row.common_name,
        "expires_at": row.expires_at.isoformat() + "Z",
        "last_seen_at": row.last_seen_at.isoformat() + "Z" if row.last_seen_at else None,
        "status": "revoked" if row.revoked_at else "expired" if row.expires_at <= now else "active",
    }


def add_device(db, details, cert, replaced=None):
    names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    row = DeviceCertificate(
        name=details.name, owner=details.owner, comment=details.comment,
        fingerprint=fingerprint(cert),
        public_key_fingerprint=hashlib.sha256(key_bytes(cert.public_key())).hexdigest(),
        common_name=names[0].value[:255] if names else "",
        serial_number=format(cert.serial_number, "x"),
        expires_at=cert.not_valid_after_utc.replace(tzinfo=None),
    )
    db.add(row)
    if replaced is not None and replaced.revoked_at is None:
        replaced.revoked_at = utc_now()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Этот сертификат или его ключ уже зарегистрирован. Для перевыпуска создайте новый ключ.") from exc
    return public_device(row)


def find_device(db, device_id):
    row = db.scalar(select(DeviceCertificate).where(DeviceCertificate.id == device_id).with_for_update())
    if row is None:
        raise HTTPException(404, "Устройство не найдено")
    return row


@router.get("")
def devices(db: Session = Depends(get_db)):
    return [public_device(row) for row in db.scalars(select(DeviceCertificate).order_by(DeviceCertificate.id.desc()))]


@router.post("/refresh-crl")
def refresh_crl():
    refresh_device_crl()
    return {"success": True, "message": "Список отозванных сертификатов обновлён"}


@router.post("/issue", status_code=201)
def issue(data: IssueDevice, response: Response, db: Session = Depends(get_db)):
    cert = issue_certificate(data.pem)
    response.headers["Cache-Control"] = "no-store"
    return {"device": add_device(db, data, cert), "certificate": cert.public_bytes(serialization.Encoding.PEM).decode()}


@router.post("/register", status_code=201)
def register(data: IssueDevice, db: Session = Depends(get_db)):
    return add_device(db, data, registered_certificate(data.pem))


@router.patch("/{device_id}")
def edit(device_id: int, data: DeviceDetails, db: Session = Depends(get_db)):
    row = find_device(db, device_id)
    row.name, row.owner, row.comment = data.name, data.owner, data.comment
    db.commit()
    return public_device(row)


@router.post("/{device_id}/revoke")
def revoke(device_id: int, db: Session = Depends(get_db)):
    row = find_device(db, device_id)
    if row.revoked_at is None:
        row.revoked_at = utc_now()
        db.commit()
    refresh_device_crl()
    return public_device(row)


@router.post("/{device_id}/replace", status_code=201)
def replace(device_id: int, data: DevicePem, response: Response, db: Session = Depends(get_db)):
    row = find_device(db, device_id)
    cert = issue_certificate(data.pem)
    response.headers["Cache-Control"] = "no-store"
    device = add_device(db, row, cert, replaced=row)
    certificate = cert.public_bytes(serialization.Encoding.PEM).decode()
    try:
        refresh_device_crl()
    except HTTPException:
        return {
            "device": device,
            "certificate": certificate,
            "crl_updated": False,
            "warning": "Новый сертификат выдан, но обновление списка отзыва не подтверждено. Обратитесь к администратору.",
        }
    return {"device": device, "certificate": certificate, "crl_updated": True}


@proxy_router.get("/verify", status_code=204)
def verify(request: Request, db: Session = Depends(get_db)):
    secret = settings.device_proxy_secret
    provided = request.headers.get("x-vr-device-secret", "")
    if not secret or not secrets.compare_digest(provided.encode(), secret.encode()):
        raise HTTPException(403)
    if request.headers.get("x-vr-device-verify") != "SUCCESS":
        raise HTTPException(403)
    pem = request.headers.get("x-vr-device-certificate", "")
    if not pem or len(pem) > 32768:
        raise HTTPException(403)
    try:
        digest = fingerprint(x509.load_pem_x509_certificate(unquote(pem).encode()))
    except (ValueError, UnsupportedAlgorithm) as exc:
        raise HTTPException(403) from exc
    now = utc_now()
    row = db.scalar(select(DeviceCertificate).where(
        DeviceCertificate.fingerprint == digest,
        DeviceCertificate.revoked_at.is_(None),
        DeviceCertificate.expires_at > now,
    ))
    if row is None:
        raise HTTPException(403)
    cutoff = now - timedelta(minutes=5)
    if row.last_seen_at is None or row.last_seen_at < cutoff:
        db.execute(update(DeviceCertificate).where(
            DeviceCertificate.id == row.id, DeviceCertificate.revoked_at.is_(None),
            or_(DeviceCertificate.last_seen_at.is_(None), DeviceCertificate.last_seen_at < cutoff),
        ).values(last_seen_at=now))
        db.commit()
    return Response(status_code=204)
