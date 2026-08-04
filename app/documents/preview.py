"""Build preview payloads for uploaded documents."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def preview_kind(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext == ".docx":
        return "html"
    if ext == ".txt":
        return "text"
    return "text"


def docx_to_html(file_bytes: bytes) -> str:
    try:
        import mammoth
    except ImportError as exc:
        raise RuntimeError("mammoth is required for DOCX preview") from exc

    from io import BytesIO

    result = mammoth.convert_to_html(BytesIO(file_bytes or b""))
    body = (result.value or "").strip() or "<p>(empty document)</p>"
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>body{font-family:system-ui,sans-serif;padding:16px;line-height:1.5;"
        "color:#1a1a1a;background:#fff} img{max-width:100%}</style>"
        f"</head><body>{body}</body></html>"
    )


def html_preview_path(stored_abs: Path) -> Path:
    return stored_abs.with_suffix(stored_abs.suffix + ".preview.html")


def ensure_docx_preview_html(stored_abs: Path) -> Path:
    """Convert DOCX on disk to a sibling .preview.html (cached)."""
    out = html_preview_path(stored_abs)
    if out.is_file() and out.stat().st_mtime >= stored_abs.stat().st_mtime:
        return out
    html = docx_to_html(stored_abs.read_bytes())
    out.write_text(html, encoding="utf-8")
    return out
