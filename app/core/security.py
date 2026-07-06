import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

import bcrypt
import jwt
from jwt.exceptions import InvalidTokenError

from app.db.config import settings
from app.schemas.common import now_local


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode()[:72], hashed.encode())


def create_access_token(subject: uuid.UUID | str, extra: dict[str, Any] | None = None) -> str:
    expire = now_local() + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {"sub": str(subject), "exp": expire}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except InvalidTokenError as e:
        raise ValueError("Invalid token") from e


DOCUMENT_DOWNLOAD_SCOPE = "document_download"
DOCUMENT_DOWNLOAD_TOKEN_EXPIRE_MINUTES = 15


def create_document_download_token(document_id: uuid.UUID) -> str:
    """Короткоживущий токен на скачивание одного конкретного документа.

    В отличие от access_token, его можно передавать прямо в query-строке
    ссылки: браузер не может приложить Authorization-заголовок при переходе
    по ссылке, а этот токен скоупнут только на один документ и живёт
    считанные минуты, так что риск утечки в логах/истории минимален.
    """
    expire = now_local() + timedelta(minutes=DOCUMENT_DOWNLOAD_TOKEN_EXPIRE_MINUTES)
    payload = {"doc": str(document_id), "scope": DOCUMENT_DOWNLOAD_SCOPE, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_document_download_token(token: str) -> uuid.UUID:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except InvalidTokenError as e:
        raise ValueError("Invalid token") from e
    if payload.get("scope") != DOCUMENT_DOWNLOAD_SCOPE:
        raise ValueError("Invalid token")
    return uuid.UUID(payload["doc"])


def generate_refresh_token() -> tuple[str, str]:
    """Возвращает (raw_token, sha256_hex_hash). Клиенту отдаём raw, в БД храним hash."""
    raw = secrets.token_urlsafe(32)
    return raw, _sha256(raw)


def hash_token(raw: str) -> str:
    return _sha256(raw)


def generate_reset_code() -> tuple[str, str]:
    """Возвращает (6-значный код, его sha256 хеш)."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    return code, _sha256(code)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def refresh_token_expires_at() -> datetime:
    return now_local() + timedelta(days=settings.refresh_token_expire_days)
