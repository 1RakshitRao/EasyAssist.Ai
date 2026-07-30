"""JWT access-token helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from jose import JWTError, jwt

from app.config import get_settings

ROLES = ("employee", "agent", "admin")


def create_access_token(
    *,
    user_id: str,
    email: str,
    role: str,
    name: str = "",
    expires_minutes: Optional[int] = None,
) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes
        if expires_minutes is not None
        else settings.jwt_expire_minutes
    )
    payload: Dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "role": role,
        "name": name,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise ValueError("Invalid or expired token") from exc
    sub = payload.get("sub")
    email = payload.get("email")
    role = payload.get("role")
    if not sub or not email or role not in ROLES:
        raise ValueError("Invalid token claims")
    return {
        "id": str(sub),
        "email": str(email).lower(),
        "role": str(role),
        "name": str(payload.get("name") or ""),
    }
