"""Unified LLM client — Anthropic or local Ollama (Haiku/Sonnet/Opus roles)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
from anthropic import Anthropic

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class LLMResult:
    text: str
    model: str
    token_usage: Dict[str, int]
    provider: str


def cached_system(text: str) -> List[Dict[str, Any]]:
    """Anthropic prompt-cache system block (ignored by Ollama, still fine to pass)."""
    return [
        {
            "type": "text",
            "text": text,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def extract_token_usage(response: Any) -> Dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    result: Dict[str, int] = {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
    }
    cache_read = getattr(usage, "cache_read_input_tokens", None)
    cache_create = getattr(usage, "cache_creation_input_tokens", None)
    if cache_read is not None:
        result["cache_read_input_tokens"] = int(cache_read or 0)
    if cache_create is not None:
        result["cache_creation_input_tokens"] = int(cache_create or 0)
    return result


def merge_token_usage(existing: Optional[Dict[str, int]], new: Dict[str, int]) -> Dict[str, int]:
    merged = dict(existing or {})
    for key, value in new.items():
        merged[key] = merged.get(key, 0) + value
    return merged


def _system_text(system: Any) -> str:
    if system is None:
        return ""
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        parts = []
        for block in system:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or ""))
            else:
                parts.append(str(block))
        return "\n".join(p for p in parts if p)
    return str(system)


def _complete_anthropic(
    *,
    model: str,
    system: Any,
    user_content: str,
    max_tokens: int,
) -> LLMResult:
    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key or None)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system if not isinstance(system, str) else cached_system(system),
        messages=[{"role": "user", "content": user_content}],
    )
    text = ""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            text += block.text
    return LLMResult(
        text=text.strip(),
        model=model,
        token_usage=extract_token_usage(response),
        provider="anthropic",
    )


def _complete_ollama(
    *,
    model: str,
    system: Any,
    user_content: str,
    max_tokens: int,
) -> LLMResult:
    settings = get_settings()
    url = settings.ollama_base_url.rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "stream": False,
        "options": {"num_predict": max_tokens},
        "messages": [
            {"role": "system", "content": _system_text(system)},
            {"role": "user", "content": user_content},
        ],
    }
    with httpx.Client(timeout=settings.ollama_timeout_seconds) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    message = data.get("message") or {}
    text = (message.get("content") or "").strip()
    usage = {
        "input_tokens": int(data.get("prompt_eval_count") or 0),
        "output_tokens": int(data.get("eval_count") or 0),
    }
    return LLMResult(
        text=text,
        model=model,
        token_usage=usage,
        provider="ollama",
    )


def complete(
    *,
    model: str,
    system: Any,
    user_content: str,
    max_tokens: int = 1024,
) -> LLMResult:
    """Route to Anthropic or Ollama based on LLM_PROVIDER."""
    settings = get_settings()
    provider = (settings.llm_provider or "ollama").lower().strip()
    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is empty")
        return _complete_anthropic(
            model=model,
            system=system,
            user_content=user_content,
            max_tokens=max_tokens,
        )
    if provider == "ollama":
        return _complete_ollama(
            model=model,
            system=system,
            user_content=user_content,
            max_tokens=max_tokens,
        )
    raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")


def resolve_answer_model(
    severity: str,
    escalated: bool = False,
    preference: str | None = None,
) -> str:
    """
    Role mapping (local sims of Anthropic tiers):
    - routine  → Haiku  (fast/cheap)
    - high     → Sonnet (balanced)
    - high + escalated (legal/HR HITL path) → Opus (strongest)

    Optional preference override: auto|routine|high|opus
    """
    settings = get_settings()
    pref = (preference or "auto").lower().strip()
    if pref in {"routine", "haiku", "fast"}:
        return settings.answer_model_routine
    if pref in {"high", "sonnet", "balanced"}:
        return settings.answer_model_high
    if pref in {"opus", "strong"}:
        return settings.answer_model_opus
    # auto
    if escalated and severity == "high":
        return settings.answer_model_opus
    if severity == "high":
        return settings.answer_model_high
    return settings.answer_model_routine


# Back-compat exports used by older imports
def get_client() -> Anthropic:
    settings = get_settings()
    return Anthropic(api_key=settings.anthropic_api_key or None)
