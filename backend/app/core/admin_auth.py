from __future__ import annotations

import hashlib
import secrets
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.catalog import AdminSession


COOKIE_NAME = "vrcatalog_admin"
_password_hasher = PasswordHasher()
_attempts: dict[str, deque[datetime]] = defaultdict(deque)
_attempts_lock = threading.Lock()
_operations: dict[str, deque[datetime]] = defaultdict(deque)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def check_login_rate_limit(client: str) -> None:
    now = datetime.utcnow()
    with _attempts_lock:
        attempts = _attempts[client]
        while attempts and attempts[0] < now - timedelta(minutes=15):
            attempts.popleft()
        if len(attempts) >= 10:
            raise HTTPException(429, "Слишком много попыток входа. Повторите позже.")
        attempts.append(now)


def verify_admin_password(password: str) -> bool:
    if not settings.admin_password_hash:
        return False
    try:
        return _password_hasher.verify(settings.admin_password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_admin_session(db: Session) -> tuple[str, str, AdminSession]:
    db.query(AdminSession).filter(AdminSession.expires_at <= datetime.utcnow()).delete(synchronize_session=False)
    session_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    item = AdminSession(
        session_hash=_hash(session_token),
        csrf_hash=_hash(csrf_token),
        expires_at=datetime.utcnow() + timedelta(hours=settings.admin_session_hours),
    )
    db.add(item)
    db.commit()
    return session_token, csrf_token, item


def require_admin(
    request: Request,
    x_csrf_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AdminSession:
    token = request.cookies.get(COOKIE_NAME)
    item = db.query(AdminSession).filter_by(session_hash=_hash(token or "")).first()
    if item is None or item.expires_at <= datetime.utcnow():
        raise HTTPException(401, "Требуется вход администратора")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not x_csrf_token or not secrets.compare_digest(item.csrf_hash, _hash(x_csrf_token)):
            raise HTTPException(403, "Недействительный CSRF token")
    return item


def require_heavy_admin(
    request: Request,
    session: AdminSession = Depends(require_admin),
) -> AdminSession:
    now = datetime.utcnow()
    client = request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")
    key = f"{client}:{request.url.path}"
    limit = 3 if request.url.path.endswith(("/import", "/download", "/test", "/run")) else 10
    with _attempts_lock:
        attempts = _operations[key]
        while attempts and attempts[0] < now - timedelta(minutes=1):
            attempts.popleft()
        if len(attempts) >= limit:
            raise HTTPException(429, "Слишком много ресурсоемких запросов. Повторите позже.")
        attempts.append(now)
    return session


def rotate_csrf(db: Session, item: AdminSession) -> str:
    csrf_token = secrets.token_urlsafe(32)
    item.csrf_hash = _hash(csrf_token)
    db.commit()
    return csrf_token
