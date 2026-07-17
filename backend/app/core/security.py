from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def _create_token(
    subject: str, expires_delta: timedelta, extra: dict[str, Any] | None = None
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {"sub": subject, "iat": now, "exp": now + expires_delta}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(user_id: str, role: str) -> str:
    return _create_token(
        subject=user_id,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        extra={"role": role, "type": "access"},
    )


def create_refresh_token(user_id: str) -> str:
    return _create_token(
        subject=user_id,
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        extra={"type": "refresh"},
    )


def create_password_reset_token(user_id: str) -> str:
    """Token de curta duração enviado por e-mail para autorizar a troca de
    senha via POST /auth/reset-password."""
    return _create_token(
        subject=user_id,
        expires_delta=timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
        extra={"type": "password_reset"},
    )


def create_download_token(job_id: str, expires_in_seconds: int) -> str:
    """Token de curta duração para autorizar GET /jobs/{id}/output-file via
    URL (ex. window.open), que não envia o header Authorization normal."""
    return _create_token(
        subject=job_id,
        expires_delta=timedelta(seconds=expires_in_seconds),
        extra={"type": "download"},
    )


def decode_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError as e:
        raise ValueError(f"Token inválido: {e}") from e
