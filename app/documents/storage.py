"""Local disk storage for uploaded chat document bytes."""

from __future__ import annotations

import logging
import re
import shutil
import time
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-]+")


def documents_root() -> Path:
    settings = get_settings()
    root = Path(settings.document_storage_dir or "./data/documents").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_filename(filename: str) -> str:
    name = (filename or "document").strip().replace("\\", "/").split("/")[-1]
    name = _SAFE_NAME.sub("_", name).strip("._") or "document"
    return name[:180]


def session_dir(session_id: str) -> Path:
    sid = _SAFE_NAME.sub("_", (session_id or "").strip()) or "session"
    path = documents_root() / sid
    path.mkdir(parents=True, exist_ok=True)
    return path


def file_relative_path(session_id: str, doc_id: str, filename: str) -> str:
    return f"{_SAFE_NAME.sub('_', (session_id or '').strip())}/{doc_id}_{safe_filename(filename)}"


def absolute_path(relative: str) -> Path:
    rel = (relative or "").replace("\\", "/").lstrip("/")
    root = documents_root()
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("path escapes document storage root") from exc
    return path


def save_file(session_id: str, doc_id: str, filename: str, file_bytes: bytes) -> Path:
    """Write bytes to disk; return absolute path. Relative path via file_relative_path."""
    delete_session_files(session_id)
    rel = file_relative_path(session_id, doc_id, filename)
    path = absolute_path(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(file_bytes or b"")
    logger.info("document file saved path=%s bytes=%s", path, len(file_bytes or b""))
    return path


def get_file_path(session_id: str, doc_id: str, filename: str) -> Path:
    return absolute_path(file_relative_path(session_id, doc_id, filename))


def delete_session_files(session_id: str) -> None:
    sid = _SAFE_NAME.sub("_", (session_id or "").strip())
    if not sid:
        return
    path = documents_root() / sid
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        logger.info("document session files removed session=%s", sid)


def delete_file(relative_or_abs: str | Path) -> None:
    path = Path(relative_or_abs)
    if not path.is_absolute():
        path = absolute_path(str(relative_or_abs))
    try:
        if path.is_file():
            path.unlink(missing_ok=True)
    except Exception:
        logger.warning("failed to delete document file %s", path, exc_info=True)


def cleanup_old_document_files(max_age_days: int | None = None) -> int:
    """Delete session directories older than max_age_days. Returns number of dirs removed."""
    settings = get_settings()
    days = int(max_age_days if max_age_days is not None else settings.document_file_ttl_days or 7)
    cutoff = time.time() - (days * 86400)
    root = documents_root()
    removed = 0
    if not root.exists():
        return 0
    for session_path in root.iterdir():
        if not session_path.is_dir():
            continue
        try:
            mtime = session_path.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            shutil.rmtree(session_path, ignore_errors=True)
            removed += 1
            logger.info("purged old document dir %s", session_path.name)
    return removed
