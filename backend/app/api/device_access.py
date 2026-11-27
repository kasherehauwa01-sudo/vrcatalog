"""Device registry and the authorization endpoint for the HTTPS reverse proxy."""
import base64
import string
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
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from sqlalchemy import or_, select, update, text
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


class PackageOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{32}$")]


class IssuePackage(DeviceDetails, PackageOperation):
    pass


async def package_payload(request: Request, model):
    # Avoid FastAPI's default validation response, which echoes invalid input.
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 8192:
            raise HTTPException(413, "Слишком большой запрос")
        body.extend(chunk)
    try:
        return model.model_validate_json(body)
    except ValidationError:
        raise HTTPException(422, "Проверьте данные устройства и обновите страницу") from None
    finally:
        body[:] = b"\x00" * len(body)


async def issue_payload(request: Request):
    return await package_payload(request, IssuePackage)


async def replace_payload(request: Request):
    return await package_payload(request, PackageOperation)


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
    return sign_certificate(key, ca_certificate())


def sign_certificate(key, ca, common_name=None):
    try:
        signer = serialization.load_pem_private_key(Path(settings.device_ca_key).read_bytes(), password=None)
        if not isinstance(signer, (rsa.RSAPrivateKey, ec.EllipticCurvePrivateKey)):
            raise ValueError("unsupported signing key")
        if key_bytes(signer.public_key()) != key_bytes(ca.public_key()):
            raise ValueError("signing key does not match CA")
        now = datetime.now(timezone.utc)
        if not ca.not_valid_before_utc <= now < ca.not_valid_after_utc:
            raise ValueError("inactive CA")
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, (common_name or f"device-{secrets.token_hex(8)}"))])
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


def package_operation(db, operation_id):
    """Persist replay detection in the certificate CN, never a password/key/cache.

    Transaction locks cover lookup + signing + registration across worker processes.
    A retry of a committed operation only gets a conflict, never the package again.
    """
    digest = hashlib.sha256(operation_id.encode("ascii")).hexdigest()
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int.from_bytes(bytes.fromhex(digest[:16]), "big", signed=True)})
    elif db.get_bind().dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
    else:
        raise HTTPException(503, "Выпуск сертификатов недоступен для этой базы данных")
    common_name = "device-" + digest[:56]  # X.509 common names must fit in 64 characters.
    if db.scalar(select(DeviceCertificate.id).where(DeviceCertificate.common_name == common_name)) is not None:
        raise HTTPException(409, "Операция уже выполнена. Проверьте список устройств. Повторная выдача файла и пароля невозможна.")
    return common_name


def generate_package_password():
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))


def encrypted_package(common_name):
    try:
        password = generate_package_password()
        ca = ca_certificate()
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        cert = sign_certificate(key.public_key(), ca, common_name)
        package = pkcs12.serialize_key_and_certificates(
            common_name.encode(), key, cert, [ca], serialization.BestAvailableEncryption(password.encode("ascii")),
        )
        return cert, package, common_name, password
    except HTTPException:
        raise
    except (OSError, ValueError, TypeError, UnsupportedAlgorithm):
        raise HTTPException(503, "Не удалось создать установочный файл сертификата") from None
    # Secrets are request-local only. Immutable Python/HTTP buffers cannot be reliably zeroized.


def package_response(device, package, name, password):
    return JSONResponse({
        "device": device, "filename": f"{name}.p12",
        "pkcs12_base64": base64.b64encode(package).decode("ascii"), "password": password,
    }, status_code=201, headers={
        "Cache-Control": "no-store, private, max-age=0",
        "Pragma": "no-cache", "Expires": "0", "X-Content-Type-Options": "nosniff",
        "X-Accel-Buffering": "no",
    })


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
        "replaces_id": row.replaces_id, "crl_pending": row.crl_pending,
        "status": ("revoked" if row.revoked_at else "expired" if row.expires_at <= now
                   else "pending" if is_pending(row) else "active"),
        "awaiting_activation": is_pending(row) and row.revoked_at is None,
    }


def is_pending(row):
    return row.replaces_id is not None and row.activated_at is None


def pending_replacement(db, device_id):
    return db.scalar(select(DeviceCertificate).where(
        DeviceCertificate.replaces_id == device_id,
        DeviceCertificate.activated_at.is_(None),
        DeviceCertificate.revoked_at.is_(None),
    ).with_for_update())


def add_device(db, details, cert, replaces_id=None):
    names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    row = DeviceCertificate(
        name=details.name, owner=details.owner, comment=details.comment,
        fingerprint=fingerprint(cert),
        public_key_fingerprint=hashlib.sha256(key_bytes(cert.public_key())).hexdigest(),
        common_name=names[0].value[:255] if names else "",
        serial_number=format(cert.serial_number, "x"),
        replaces_id=replaces_id,
        expires_at=cert.not_valid_after_utc.replace(tzinfo=None),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Сертификат или его ключ уже зарегистрирован, либо у устройства уже есть ожидающая замена.") from exc
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


@router.post("/issue", status_code=201, response_class=Response, include_in_schema=False)
@router.post("/issue-package", status_code=201, response_class=Response)
def issue(data: Annotated[IssuePackage, Depends(issue_payload)], db: Session = Depends(get_db)):
    name = package_operation(db, data.operation_id)
    cert, package, name, password = encrypted_package(name)
    return package_response(add_device(db, data, cert), package, name, password)


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
    if is_pending(row):
        raise HTTPException(409, "Ожидающий сертификат отменяется через исходное устройство")
    if row.revoked_at is None:
        row.revoked_at = utc_now()
        if pending := pending_replacement(db, device_id):
            pending.revoked_at = row.revoked_at
    db.commit()
    refresh_device_crl()
    return public_device(row)


@router.post("/{device_id}/replace", status_code=201, response_class=Response, include_in_schema=False)
@router.post("/{device_id}/replacements/prepare", status_code=201, response_class=Response)
def replace(device_id: int, data: Annotated[PackageOperation, Depends(replace_payload)], db: Session = Depends(get_db)):
    name = package_operation(db, data.operation_id)
    row = find_device(db, device_id)
    if row.revoked_at is not None or is_pending(row):
        raise HTTPException(409, "Этот сертификат нельзя использовать как исходный для замены")
    if pending_replacement(db, device_id) is not None:
        raise HTTPException(409, "У устройства уже есть ожидающая замена")
    cert, package, name, password = encrypted_package(name)
    return package_response(add_device(db, row, cert, replaces_id=row.id), package, name, password)


def replacement_pair(db, device_id, replacement_id):
    original = find_device(db, device_id)
    # Check the relationship before locking a potentially unrelated device.
    replacement = db.scalar(select(DeviceCertificate).where(
        DeviceCertificate.id == replacement_id, DeviceCertificate.replaces_id == device_id,
    ).with_for_update())
    if replacement is None:
        raise HTTPException(404, "Замена для указанного устройства не найдена")
    return original, replacement


@router.post("/{device_id}/replacements/{replacement_id}/confirm")
def confirm(device_id: int, replacement_id: int, db: Session = Depends(get_db)):
    original, replacement = replacement_pair(db, device_id, replacement_id)
    if replacement.activated_at is None:
        now = utc_now()
        if original.revoked_at or replacement.revoked_at or replacement.expires_at <= now:
            raise HTTPException(409, "Замена отменена, истекла или исходный сертификат заблокирован")
        replacement.name, replacement.owner, replacement.comment = original.name, original.owner, original.comment
        replacement.activated_at = original.revoked_at = now
        replacement.crl_pending = True
    publish = replacement.crl_pending
    # Commit the access change before the CRL service reads the revocations.
    db.commit()
    if publish:
        refresh_device_crl()
        db.execute(update(DeviceCertificate).where(
            DeviceCertificate.id == replacement_id,
        ).values(crl_pending=False))
        db.commit()
    return public_device(replacement)


@router.post("/{device_id}/replacements/{replacement_id}/cancel")
def cancel(device_id: int, replacement_id: int, db: Session = Depends(get_db)):
    _, replacement = replacement_pair(db, device_id, replacement_id)
    if replacement.activated_at is not None:
        raise HTTPException(409, "Замена уже подтверждена")
    if replacement.revoked_at is None:
        replacement.revoked_at = utc_now()
    db.commit()
    return public_device(replacement)


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
        or_(DeviceCertificate.replaces_id.is_(None), DeviceCertificate.activated_at.is_not(None)),
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
