"""Tier-based LLM provider — Groq (default), Grok, or Anthropic via LangChain."""



from __future__ import annotations



from typing import Literal, Union



from langchain_groq import ChatGroq

from langchain_xai import ChatXAI



from app.config import get_settings



Tier = Literal["fast", "balanced", "powerful", "guardrails"]



_VALID_TIERS = frozenset({"fast", "balanced", "powerful", "guardrails"})





def _normalize_tier(tier: str) -> Tier:

    t = (tier or "fast").lower().strip()

    if t not in _VALID_TIERS:

        raise ValueError(

            f"Unknown tier: {tier!r} (expected fast|balanced|powerful|guardrails)"

        )

    return t  # type: ignore[return-value]





def resolve_tier_model(tier: str) -> str:

    """Return the model id for a tier given the active LLM_PROVIDER."""

    settings = get_settings()

    t = _normalize_tier(tier)

    provider = (settings.llm_provider or "groq").lower().strip()



    if provider == "groq":

        return {

            "fast": settings.groq_model_fast,

            "balanced": settings.groq_model_balanced,

            "powerful": settings.groq_model_powerful,

            "guardrails": settings.groq_model_guardrails,

        }[t]



    if provider == "grok":

        if t == "guardrails":

            raise ValueError("guardrails tier is only supported for LLM_PROVIDER=groq")

        return {

            "fast": settings.grok_model_fast,

            "balanced": settings.grok_model_balanced,

            "powerful": settings.grok_model_powerful,

        }[t]



    if provider == "anthropic":

        if t == "guardrails":

            raise ValueError("guardrails tier is only supported for LLM_PROVIDER=groq")

        return {

            "fast": settings.classifier_model,

            "balanced": settings.answer_model_high,

            "powerful": settings.answer_model_opus,

        }[t]



    raise ValueError(f"resolve_tier_model unsupported for LLM_PROVIDER={provider}")





def get_llm(tier: str = "fast") -> Union[ChatGroq, ChatXAI]:

    """

    Return a LangChain chat model for the given tier.



    Groq tier options (default):

      fast       → gpt-oss-20b  (classifier, severity, NLP)

      balanced   → gpt-oss-120b (answers, doc summarization)

      powerful   → gpt-oss-120b (high + escalated answers)

      guardrails → prompt-guard  (Phase 9 safety checks)



    Grok tier options:

      fast / balanced / powerful → grok-4.x models

    """

    settings = get_settings()

    provider = (settings.llm_provider or "groq").lower().strip()

    t = _normalize_tier(tier)

    model = resolve_tier_model(t)



    if provider == "groq":

        if not settings.groq_api_key:

            raise RuntimeError("LLM_PROVIDER=groq but GROQ_API_KEY is empty")

        return ChatGroq(

            model=model,

            api_key=settings.groq_api_key,

            temperature=0.1,

            max_retries=2,

        )



    if provider == "grok":

        if not settings.xai_api_key:

            raise RuntimeError("LLM_PROVIDER=grok but XAI_API_KEY is empty")

        return ChatXAI(

            model=model,

            xai_api_key=settings.xai_api_key,

            temperature=0.1,

            max_retries=2,

        )



    raise ValueError(

        f"get_llm() supports groq/grok only; use app.llm.client.complete() for provider={provider}"

    )





def tier_for_severity(severity: str, *, escalated: bool = False) -> Tier:

    """Map answer severity to a model tier."""

    settings = get_settings()

    provider = (settings.llm_provider or "groq").lower().strip()



    # Groq: all answers use 120B; fast tier is for classify/score/NLP only

    if provider == "groq":

        return "balanced"



    if escalated and (severity or "").lower() == "high":

        return "powerful"

    if (severity or "").lower() == "high":

        return "balanced"

    return "fast"





def tier_for_task(task: str) -> Tier:

    """Map a named task to a model tier."""

    t = (task or "").lower().strip()

    if t in {"document", "document_analysis", "kb_pusher"}:

        return "balanced"

    return "fast"





def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:

    """Returns cost in USD for audit logging (Groq models)."""

    from app.analytics.costing import cost_usd, infer_role



    role = infer_role(model)

    return round(cost_usd(role, input_tokens, output_tokens), 6)


