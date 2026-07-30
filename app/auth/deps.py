"""FastAPI auth dependencies."""

from __future__ import annotations

from typing import Annotated, Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.jwt import decode_access_token
from app.auth.users import get_user_by_id, public_user

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> dict:
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_access_token(creds.credentials)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    user = get_user_by_id(claims["id"])
    if not user or not user.get("active", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User inactive or not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return public_user(user)


def require_roles(*roles: str) -> Callable:
    allowed = {r.lower() for r in roles}

    def _dep(user: Annotated[dict, Depends(get_current_user)]) -> dict:
        if user.get("role") not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user

    return _dep


CurrentUser = Annotated[dict, Depends(get_current_user)]
AgentUser = Annotated[dict, Depends(require_roles("agent", "admin"))]
AdminUser = Annotated[dict, Depends(require_roles("admin"))]
