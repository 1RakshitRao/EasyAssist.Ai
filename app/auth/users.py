"""JSON user store — local email/password accounts."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.auth.jwt import ROLES
from app.auth.passwords import hash_password, verify_password
from app.config import get_settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _users_path() -> Path:
    settings = get_settings()
    if settings.users_path:
        path = Path(settings.users_path).resolve()
    else:
        base = Path(settings.chroma_persist_dir).resolve().parent
        path = base / "users.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_all() -> List[Dict[str, Any]]:
    path = _users_path()
    if not path.exists():
        return []
    try:
        users = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Corrupt users file — starting empty")
        return []
    if not isinstance(users, list):
        return []
    for u in users:
        u.setdefault("active", True)
        u.setdefault("name", "")
        u.setdefault("role", "employee")
        u.setdefault("access_restricted", False)
    return users


def _write_all(users: List[Dict[str, Any]]) -> None:
    path = _users_path()
    path.write_text(json.dumps(users, indent=2), encoding="utf-8")


def list_users() -> List[Dict[str, Any]]:
    with _lock:
        return list(_read_all())


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    key = (email or "").strip().lower()
    with _lock:
        for user in _read_all():
            if str(user.get("email") or "").lower() == key:
                return dict(user)
    return None


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        for user in _read_all():
            if user.get("id") == user_id:
                return dict(user)
    return None


def create_user(
    *,
    email: str,
    password: str,
    role: str,
    name: str = "",
    active: bool = True,
) -> Dict[str, Any]:
    email_key = (email or "").strip().lower()
    role_key = (role or "").strip().lower()
    if not email_key or "@" not in email_key:
        raise ValueError("Valid email is required")
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    if role_key not in ROLES:
        raise ValueError(f"role must be one of: {', '.join(ROLES)}")

    with _lock:
        users = _read_all()
        if any(str(u.get("email") or "").lower() == email_key for u in users):
            raise ValueError("Email already registered")
        user = {
            "id": str(uuid.uuid4()),
            "email": email_key,
            "name": (name or "").strip() or email_key.split("@")[0],
            "role": role_key,
            "password_hash": hash_password(password),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "active": bool(active),
            "access_restricted": False,
        }
        users.append(user)
        _write_all(users)
    logger.info("Created user email=%s role=%s", email_key, role_key)
    try:
        from app.nlp_query.sync import sync_app_users

        sync_app_users()
    except Exception:
        logger.warning("app_users sync after create_user failed", exc_info=True)
    return dict(user)


def set_user_password(email: str, password: str) -> Optional[Dict[str, Any]]:
    """Reset password for an existing user."""
    email_key = (email or "").strip().lower()
    if not email_key or "@" not in email_key:
        raise ValueError("Valid email is required")
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    with _lock:
        users = _read_all()
        for user in users:
            if str(user.get("email") or "").lower() == email_key:
                user["password_hash"] = hash_password(password)
                _write_all(users)
                logger.info("Reset password for email=%s", email_key)
                return dict(user)
    return None


def authenticate(email: str, password: str) -> Optional[Dict[str, Any]]:
    user = get_user_by_email(email)
    if not user:
        return None
    if not user.get("active", True):
        return None
    if not verify_password(password, str(user.get("password_hash") or "")):
        return None
    return user


def public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": user.get("id"),
        "email": user.get("email"),
        "name": user.get("name") or "",
        "role": user.get("role"),
        "active": bool(user.get("active", True)),
        "access_restricted": bool(user.get("access_restricted", False)),
        "created_at": user.get("created_at") or "",
    }


def is_admin_role(role: str | None) -> bool:
    return (role or "").lower().strip() == "admin"


def set_access_restricted(email: str, restricted: bool) -> Optional[Dict[str, Any]]:
    """Mirror training restriction onto the JSON user record for fast /query checks."""
    key = (email or "").strip().lower()
    with _lock:
        users = _read_all()
        for user in users:
            if str(user.get("email") or "").lower() == key:
                user["access_restricted"] = bool(restricted)
                _write_all(users)
                return dict(user)
    return None


def bootstrap_admin_if_empty() -> Optional[Dict[str, Any]]:
    """Create bootstrap admin from env when the user store is empty."""
    settings = get_settings()
    with _lock:
        users = _read_all()
        if users:
            return None
    email = (settings.admin_email or "").strip()
    password = settings.admin_password or ""
    if not email or not password:
        logger.warning(
            "No users and ADMIN_EMAIL/ADMIN_PASSWORD not set — login will fail until a user is created"
        )
        return None
    try:
        user = create_user(
            email=email,
            password=password,
            role="admin",
            name="Admin",
        )
        logger.info("Bootstrapped admin user email=%s", email.lower())
        return user
    except ValueError as exc:
        logger.error("Failed to bootstrap admin: %s", exc)
        return None
