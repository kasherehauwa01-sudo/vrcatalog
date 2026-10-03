import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet(secret: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return _fernet(settings.secret_key).encrypt(value.encode()).decode() if value else ""


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet(settings.secret_key).decrypt(value.encode()).decode()
    except InvalidToken:
        if settings.previous_secret_key:
            return _fernet(settings.previous_secret_key).decrypt(value.encode()).decode()
        raise
