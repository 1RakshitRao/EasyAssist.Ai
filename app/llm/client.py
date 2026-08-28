"""Unified LLM client — Groq (default), Grok, or Anthropic (Haiku/Sonnet/Opus roles)."""



from __future__ import annotations



import logging

from dataclasses import dataclass

from typing import Any, Dict, List, Optional



from anthropic import Anthropic

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage



from app.config import get_settings

from app.llm_provider import get_llm, resolve_tier_model, tier_for_severity, tier_for_task



__all__ = [

    "LLMResult",

    "cached_system",

    "complete",

    "complete_task",

    "complete_tier",

    "extract_token_usage",

    "get_client",

    "is_llm_configured",

    "merge_token_usage",

    "resolve_answer_model",

    "resolve_classifier_model",

    "resolve_tier_model",

    "tier_for_severity",

    "tier_for_task",

]



logger = logging.getLogger(__name__)



_LANGCHAIN_PROVIDERS = frozenset({"groq", "grok"})





@dataclass

class LLMResult:

    text: str

    model: str

    token_usage: Dict[str, int]

    provider: str





def cached_system(text: str) -> List[Dict[str, Any]]:

    """Anthropic prompt-cache system block (flattened for Groq/Grok)."""

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





def _extract_langchain_token_usage(response: Any) -> Dict[str, int]:

    meta = getattr(response, "usage_metadata", None) or {}

    if isinstance(meta, dict):

        return {

            "input_tokens": int(meta.get("input_tokens") or 0),

            "output_tokens": int(meta.get("output_tokens") or 0),

        }

    return {

        "input_tokens": int(getattr(meta, "input_tokens", 0) or 0),

        "output_tokens": int(getattr(meta, "output_tokens", 0) or 0),

    }





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





def _normalize_messages(

    messages: Optional[List[Dict[str, str]]] = None,

    user_content: Optional[str] = None,

) -> List[Dict[str, str]]:

    if messages is not None:

        out: List[Dict[str, str]] = []

        for m in messages:

            role = str((m or {}).get("role") or "").strip().lower()

            content = str((m or {}).get("content") or "")

            if role in {"user", "assistant"} and content:

                out.append({"role": role, "content": content})

        if out:

            return out

    if user_content is None:

        raise ValueError("complete() requires messages or user_content")

    return [{"role": "user", "content": user_content}]





def _to_langchain_messages(

    *,

    system: Any,

    messages: Optional[List[Dict[str, str]]] = None,

    user_content: Optional[str] = None,

) -> List[Any]:

    lc: List[Any] = []

    sys_text = _system_text(system)

    if sys_text:

        lc.append(SystemMessage(content=sys_text))

    for m in _normalize_messages(messages, user_content):

        if m["role"] == "user":

            lc.append(HumanMessage(content=m["content"]))

        else:

            lc.append(AIMessage(content=m["content"]))

    return lc





def _complete_anthropic(

    *,

    model: str,

    system: Any,

    user_content: Optional[str] = None,

    messages: Optional[List[Dict[str, str]]] = None,

    max_tokens: int,

) -> LLMResult:

    settings = get_settings()

    client = Anthropic(api_key=settings.anthropic_api_key or None)

    response = client.messages.create(

        model=model,

        max_tokens=max_tokens,

        system=system if not isinstance(system, str) else cached_system(system),

        messages=_normalize_messages(messages, user_content),

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





def _complete_langchain(

    *,

    provider: str,

    model: str,

    tier: str,

    system: Any,

    user_content: Optional[str] = None,

    messages: Optional[List[Dict[str, str]]] = None,

    max_tokens: int,

) -> LLMResult:

    llm = get_llm(tier).bind(max_tokens=max_tokens)

    lc_messages = _to_langchain_messages(

        system=system,

        messages=messages,

        user_content=user_content,

    )

    response = llm.invoke(lc_messages)

    text = getattr(response, "content", None) or ""

    if not isinstance(text, str):

        text = str(text)

    return LLMResult(

        text=text.strip(),

        model=model,

        token_usage=_extract_langchain_token_usage(response),

        provider=provider,

    )





def _tier_for_model(model: str) -> str:

    """Infer tier from model id when complete() receives an explicit model."""

    settings = get_settings()

    provider = (settings.llm_provider or "groq").lower().strip()

    m = (model or "").lower()



    if provider == "groq":

        if m == settings.groq_model_guardrails.lower() or "prompt-guard" in m:

            return "guardrails"

        if m == settings.groq_model_powerful.lower() or "gpt-oss-120b" in m:

            return "powerful"

        if m == settings.groq_model_balanced.lower():

            return "balanced"

        return "fast"



    if m == settings.grok_model_powerful.lower() or m == settings.answer_model_opus.lower():

        return "powerful"

    if m == settings.grok_model_balanced.lower() or m == settings.answer_model_high.lower():

        return "balanced"

    return "fast"





def complete(

    *,

    model: str,

    system: Any,

    user_content: Optional[str] = None,

    messages: Optional[List[Dict[str, str]]] = None,

    max_tokens: int = 1024,

) -> LLMResult:

    """Route to Groq, Grok, or Anthropic based on LLM_PROVIDER.



    Pass either ``user_content`` (single turn) or ``messages`` (multi-turn

    list of {role, content}). When both are set, ``messages`` wins.

    """

    settings = get_settings()

    provider = (settings.llm_provider or "groq").lower().strip()



    if provider in _LANGCHAIN_PROVIDERS:

        if provider == "groq" and not settings.groq_api_key:

            raise RuntimeError("LLM_PROVIDER=groq but GROQ_API_KEY is empty")

        if provider == "grok" and not settings.xai_api_key:

            raise RuntimeError("LLM_PROVIDER=grok but XAI_API_KEY is empty")

        return _complete_langchain(

            provider=provider,

            model=model,

            tier=_tier_for_model(model),

            system=system,

            user_content=user_content,

            messages=messages,

            max_tokens=max_tokens,

        )



    if provider == "anthropic":

        if not settings.anthropic_api_key:

            raise RuntimeError("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is empty")

        return _complete_anthropic(

            model=model,

            system=system,

            user_content=user_content,

            messages=messages,

            max_tokens=max_tokens,

        )



    if provider == "ollama":

        raise ValueError(

            "LLM_PROVIDER=ollama is no longer supported. Use groq, grok, or anthropic."

        )

    raise ValueError(

        f"Unsupported LLM_PROVIDER: {provider!r}. Use groq, grok, or anthropic."

    )





def complete_tier(

    *,

    tier: str = "fast",

    system: Any,

    user_content: Optional[str] = None,

    messages: Optional[List[Dict[str, str]]] = None,

    max_tokens: int = 1024,

) -> LLMResult:

    """Complete using a named tier (fast|balanced|powerful|guardrails)."""

    model = resolve_tier_model(tier)

    return complete(

        model=model,

        system=system,

        user_content=user_content,

        messages=messages,

        max_tokens=max_tokens,

    )





def complete_task(

    *,

    task: str,

    system: Any,

    user_content: Optional[str] = None,

    messages: Optional[List[Dict[str, str]]] = None,

    max_tokens: int = 1024,

) -> LLMResult:

    """Complete using the tier appropriate for a named task."""

    tier = tier_for_task(task)

    return complete_tier(

        tier=tier,

        system=system,

        user_content=user_content,

        messages=messages,

        max_tokens=max_tokens,

    )





def resolve_answer_model(

    severity: str,

    escalated: bool = False,

    preference: str | None = None,

) -> str:

    """

    Role mapping:

    - routine  → fast / Haiku / gpt-oss-20b (Groq answers use 120B)

    - high     → balanced / Sonnet / gpt-oss-120b

    - high + escalated (legal/HR HITL path) → powerful / Opus



    Optional preference override: auto|routine|high|opus|fast|balanced|powerful

    """

    settings = get_settings()

    provider = (settings.llm_provider or "groq").lower().strip()

    pref = (preference or "auto").lower().strip()



    if pref in {"routine", "haiku", "fast"}:

        return resolve_tier_model("fast")

    if pref in {"high", "sonnet", "balanced"}:

        return resolve_tier_model("balanced")

    if pref in {"opus", "strong", "powerful"}:

        return resolve_tier_model("powerful")



    if provider in {"groq", "grok"}:

        return resolve_tier_model(tier_for_severity(severity, escalated=escalated))



    # Anthropic: legacy settings fields

    if escalated and severity == "high":

        return settings.answer_model_opus

    if severity == "high":

        return settings.answer_model_high

    return settings.answer_model_routine





def resolve_classifier_model() -> str:

    """Model for classifier, scorer, supervisor, and similar fast tasks."""

    return resolve_tier_model("fast")





def is_llm_configured() -> bool:

    """True when the active LLM provider has an API key set."""

    settings = get_settings()

    provider = (settings.llm_provider or "groq").lower().strip()

    if provider == "groq":

        return bool(settings.groq_api_key)

    if provider == "grok":

        return bool(settings.xai_api_key)

    if provider == "anthropic":

        return bool(settings.anthropic_api_key)

    raise ValueError(

        f"Unsupported LLM_PROVIDER: {provider!r}. Use groq, grok, or anthropic."

    )





# Back-compat exports used by older imports

def get_client() -> Anthropic:

    settings = get_settings()

    return Anthropic(api_key=settings.anthropic_api_key or None)


