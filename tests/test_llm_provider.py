"""Tests for tier-based LLM provider."""



from __future__ import annotations



import pytest



from app.config import get_settings





@pytest.fixture(autouse=True)

def clear_settings_cache():

    get_settings.cache_clear()

    yield

    get_settings.cache_clear()





def test_resolve_tier_model_groq(monkeypatch):

    monkeypatch.setenv("LLM_PROVIDER", "groq")

    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")

    monkeypatch.setenv("GROQ_MODEL_FAST", "openai/gpt-oss-20b")

    monkeypatch.setenv("GROQ_MODEL_BALANCED", "openai/gpt-oss-120b")

    monkeypatch.setenv("GROQ_MODEL_POWERFUL", "openai/gpt-oss-120b")

    monkeypatch.setenv("GROQ_MODEL_GUARDRAILS", "llama-prompt-guard-2-86m")



    from app.llm_provider import resolve_tier_model, tier_for_severity, tier_for_task



    assert resolve_tier_model("fast") == "openai/gpt-oss-20b"

    assert resolve_tier_model("balanced") == "openai/gpt-oss-120b"

    assert resolve_tier_model("powerful") == "openai/gpt-oss-120b"

    assert resolve_tier_model("guardrails") == "llama-prompt-guard-2-86m"

    assert tier_for_severity("routine") == "balanced"

    assert tier_for_severity("high") == "balanced"

    assert tier_for_severity("high", escalated=True) == "balanced"

    assert tier_for_task("classifier") == "fast"

    assert tier_for_task("document_analysis") == "balanced"





def test_resolve_tier_model_grok(monkeypatch):

    monkeypatch.setenv("LLM_PROVIDER", "grok")

    monkeypatch.setenv("XAI_API_KEY", "test-key")

    monkeypatch.setenv("GROK_MODEL_FAST", "grok-4.1-fast")

    monkeypatch.setenv("GROK_MODEL_BALANCED", "grok-4.3")

    monkeypatch.setenv("GROK_MODEL_POWERFUL", "grok-4.6")



    from app.llm_provider import resolve_tier_model, tier_for_severity, tier_for_task



    assert resolve_tier_model("fast") == "grok-4.1-fast"

    assert resolve_tier_model("balanced") == "grok-4.3"

    assert resolve_tier_model("powerful") == "grok-4.6"

    assert tier_for_severity("routine") == "fast"

    assert tier_for_severity("high") == "balanced"

    assert tier_for_severity("high", escalated=True) == "powerful"

    assert tier_for_task("classifier") == "fast"

    assert tier_for_task("document_analysis") == "balanced"





def test_resolve_tier_model_anthropic(monkeypatch):

    monkeypatch.setenv("LLM_PROVIDER", "anthropic")

    monkeypatch.setenv("CLASSIFIER_MODEL", "claude-haiku-test")

    monkeypatch.setenv("ANSWER_MODEL_ROUTINE", "claude-haiku-test")

    monkeypatch.setenv("ANSWER_MODEL_HIGH", "claude-sonnet-test")

    monkeypatch.setenv("ANSWER_MODEL_OPUS", "claude-opus-test")



    from app.llm_provider import resolve_tier_model



    assert resolve_tier_model("fast") == "claude-haiku-test"

    assert resolve_tier_model("balanced") == "claude-sonnet-test"

    assert resolve_tier_model("powerful") == "claude-opus-test"





def test_resolve_answer_model_groq_tiers(monkeypatch):

    monkeypatch.setenv("LLM_PROVIDER", "groq")

    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")

    monkeypatch.setenv("GROQ_MODEL_FAST", "openai/gpt-oss-20b")

    monkeypatch.setenv("GROQ_MODEL_BALANCED", "openai/gpt-oss-120b")

    monkeypatch.setenv("GROQ_MODEL_POWERFUL", "openai/gpt-oss-120b")



    from app.llm.client import resolve_answer_model



    assert resolve_answer_model("routine", escalated=False) == "openai/gpt-oss-120b"

    assert resolve_answer_model("high", escalated=False) == "openai/gpt-oss-120b"

    assert resolve_answer_model("high", escalated=True) == "openai/gpt-oss-120b"





def test_resolve_answer_model_grok_tiers(monkeypatch):

    monkeypatch.setenv("LLM_PROVIDER", "grok")

    monkeypatch.setenv("XAI_API_KEY", "test-key")

    monkeypatch.setenv("GROK_MODEL_FAST", "grok-4.1-fast")

    monkeypatch.setenv("GROK_MODEL_BALANCED", "grok-4.3")

    monkeypatch.setenv("GROK_MODEL_POWERFUL", "grok-4.6")



    from app.llm.client import resolve_answer_model



    assert resolve_answer_model("routine", escalated=False) == "grok-4.1-fast"

    assert resolve_answer_model("high", escalated=False) == "grok-4.3"

    assert resolve_answer_model("high", escalated=True) == "grok-4.6"





def test_groq_cost_inference(monkeypatch):

    monkeypatch.setenv("LLM_PROVIDER", "groq")

    monkeypatch.setenv("GROQ_MODEL_FAST", "openai/gpt-oss-20b")

    monkeypatch.setenv("GROQ_MODEL_BALANCED", "openai/gpt-oss-120b")

    monkeypatch.setenv("PRICE_GROQ_FAST_INPUT_PER_MTOK", "0.075")

    monkeypatch.setenv("PRICE_GROQ_FAST_OUTPUT_PER_MTOK", "0.30")



    from app.analytics.costing import cost_usd, infer_role



    assert infer_role("openai/gpt-oss-20b") == "groq-fast"

    assert infer_role("openai/gpt-oss-120b") == "groq-powerful"

    cost = cost_usd("groq-fast", 1000, 500)

    assert cost == pytest.approx(0.000225, rel=1e-3)





def test_grok_cost_inference(monkeypatch):

    monkeypatch.setenv("LLM_PROVIDER", "grok")

    monkeypatch.setenv("GROK_MODEL_FAST", "grok-4.1-fast")

    monkeypatch.setenv("GROK_MODEL_BALANCED", "grok-4.3")

    monkeypatch.setenv("GROK_MODEL_POWERFUL", "grok-4.6")

    monkeypatch.setenv("PRICE_GROK_FAST_INPUT_PER_MTOK", "0.20")

    monkeypatch.setenv("PRICE_GROK_FAST_OUTPUT_PER_MTOK", "0.50")



    from app.analytics.costing import cost_usd, infer_role



    assert infer_role("grok:grok-4.1-fast") == "grok-fast"

    assert infer_role("grok-4.3") == "grok-balanced"

    cost = cost_usd("grok-fast", 1000, 500)

    assert cost == pytest.approx(0.00045, rel=1e-3)





def test_is_llm_configured_groq(monkeypatch):

    monkeypatch.setenv("LLM_PROVIDER", "groq")

    monkeypatch.setenv("GROQ_API_KEY", "")



    from app.llm.client import is_llm_configured



    assert is_llm_configured() is False



    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")

    get_settings.cache_clear()

    assert is_llm_configured() is True





def test_is_llm_configured_grok(monkeypatch):

    monkeypatch.setenv("LLM_PROVIDER", "grok")

    monkeypatch.setenv("XAI_API_KEY", "")



    from app.llm.client import is_llm_configured



    assert is_llm_configured() is False



    monkeypatch.setenv("XAI_API_KEY", "sk-test")

    get_settings.cache_clear()

    assert is_llm_configured() is True





def test_ollama_provider_rejected(monkeypatch):

    monkeypatch.setenv("LLM_PROVIDER", "ollama")



    with pytest.raises(ValueError, match="ollama is no longer supported"):

        get_settings()





def test_get_llm_requires_langchain_provider(monkeypatch):

    monkeypatch.setenv("LLM_PROVIDER", "anthropic")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")



    from app.llm_provider import get_llm



    with pytest.raises(ValueError, match="groq/grok only"):

        get_llm("fast")

