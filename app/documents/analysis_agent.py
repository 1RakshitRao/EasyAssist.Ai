"""LLM analysis operations over an uploaded document."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict

from app.config import get_settings
from app.llm.client import complete, resolve_answer_model

logger = logging.getLogger(__name__)

# Cap document context sent to the model (~chars; rough token proxy)
_MAX_DOC_CHARS = 48_000

_PROMPTS: Dict[str, str] = {
    "summarize": (
        "Summarize the document in 150–200 words. Cover the main point, "
        "key decisions, and any actions mentioned. Use clear prose."
    ),
    "takeaways": (
        "List 3–7 key takeaways as bullet points. Each must be a standalone, "
        "actionable insight. Do not narrate — only bullets."
    ),
    "actions": (
        "Extract action items as a numbered list. Include owner and deadline "
        "when the document mentions them. If none are present, say so briefly."
    ),
    "explain": (
        "Rewrite the document's core message in plain English for a non-expert. "
        "Avoid jargon. Keep it concise (under 250 words)."
    ),
    "risks": (
        "Highlight risks, obligations, ambiguities, or red flags. "
        "Use short bullets. If nothing concerning stands out, say so."
    ),
    "ask": (
        "Answer the user's question using only the document. "
        "If the answer is not in the document, say you cannot find it there."
    ),
}


@dataclass
class AnalysisResult:
    operation: str
    result: str
    model_used: str = ""
    token_usage: Dict[str, int] = field(default_factory=dict)


def _truncate(text: str) -> str:
    t = text or ""
    if len(t) <= _MAX_DOC_CHARS:
        return t
    return t[:_MAX_DOC_CHARS] + "\n\n[Document truncated for analysis.]"


def analyze_document(
    *,
    text: str,
    operation: str,
    question: str | None = None,
    filename: str = "",
) -> AnalysisResult:
    op = (operation or "").strip().lower()
    if op not in _PROMPTS:
        raise ValueError(f"Unknown operation: {op}")
    if op == "ask" and not (question or "").strip():
        raise ValueError("question is required for ask operation")

    settings = get_settings()
    doc = _truncate(text)
    instruction = _PROMPTS[op]
    system = (
        "You are Ampcus Helpdesk document assistant. "
        "Use only the provided document text. Do not invent clauses or facts. "
        "Do not mention that you are an AI unless asked."
    )
    user_parts = [
        f"Filename: {filename or 'document'}",
        f"Operation: {op}",
        f"Instructions: {instruction}",
    ]
    if op == "ask":
        user_parts.append(f"User question: {(question or '').strip()}")
    user_parts.append("Document:\n" + doc)
    user_msg = "\n\n".join(user_parts)

    # Offline fallback when Anthropic selected but no key
    if settings.llm_provider.lower() == "anthropic" and not settings.anthropic_api_key:
        preview = doc[:800].strip()
        return AnalysisResult(
            operation=op,
            result=f"(Offline) Document preview for {op}:\n{preview}",
            model_used="offline",
            token_usage={},
        )

    model = resolve_answer_model("routine", preference="routine")
    try:
        result = complete(
            model=model,
            system=system,
            user_content=user_msg,
            max_tokens=700,
        )
        answer = (result.text or "").strip() or "No result produced."
        return AnalysisResult(
            operation=op,
            result=answer,
            model_used=result.model or model,
            token_usage=dict(result.token_usage or {}),
        )
    except Exception:
        logger.exception("document analysis failed op=%s", op)
        raise
