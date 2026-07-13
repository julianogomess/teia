"""Senhas (argon2), tokens de acesso (JWT) e refresh tokens."""

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

from .config import settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: Optional[str]) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, ValueError):
        return False


def create_access_token(user_id: int, role: str, organization_id: int) -> str:
    now = datetime.utcnow()
    payload = {
        "sub": str(user_id),
        "role": role,
        "org": organization_id,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "access":
        return None
    return payload


def new_refresh_token() -> Tuple[str, str]:
    """Gera (token_em_claro, hash). Só o hash vai ao banco."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def refresh_expiry() -> datetime:
    return datetime.utcnow() + timedelta(days=settings.refresh_token_days)
