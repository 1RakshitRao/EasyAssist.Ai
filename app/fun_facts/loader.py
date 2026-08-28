"""Load fun facts from disk for chat loading state."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

_cache: list[str] | None = None


def _facts_path() -> Path:
    settings = get_settings()
    raw = (settings.fun_facts_path or "data/fun-facts.json").strip()
    path = Path(raw)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    return path


def _parse_facts_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".txt":
        return [line.strip() for line in text.splitlines() if line.strip()]

    data = json.loads(text)
    if isinstance(data, list):
        out = []
        for item in data:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict):
                fact = (item.get("text") or item.get("fact") or "").strip()
                if fact:
                    out.append(fact)
        return out
    if isinstance(data, dict):
        items = data.get("facts") or data.get("items") or []
        return _parse_facts_file_from_list(items)
    return []


def _parse_facts_file_from_list(items: list) -> list[str]:
    out = []
    for item in items:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            fact = (item.get("text") or item.get("fact") or "").strip()
            if fact:
                out.append(fact)
    return out


def load_fun_facts() -> list[str]:
    """Return all fun facts; cached for process lifetime."""
    global _cache
    if _cache is not None:
        return _cache

    path = _facts_path()
    if not path.is_file():
        logger.info("Fun facts file not found at %s", path)
        _cache = []
        return _cache

    try:
        facts = _parse_facts_file(path)
        _cache = facts
        logger.info("Loaded %d fun facts from %s", len(facts), path)
        return facts
    except Exception as exc:
        logger.error("Failed to load fun facts from %s: %s", path, exc)
        _cache = []
        return _cache


def reset_fun_facts_cache() -> None:
    """Clear cache — useful in tests."""
    global _cache
    _cache = None
