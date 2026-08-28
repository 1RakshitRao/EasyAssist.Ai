"""Tests for fun facts loader and endpoint."""

from __future__ import annotations

import json

import pytest

from app.fun_facts.loader import load_fun_facts, reset_fun_facts_cache


def test_load_fun_facts_from_json(tmp_path, monkeypatch):
    reset_fun_facts_cache()
    facts_file = tmp_path / "fun-facts.json"
    facts_file.write_text(
        json.dumps(["Fact one.", "Fact two."]),
        encoding="utf-8",
    )
    monkeypatch.setenv("FUN_FACTS_PATH", str(facts_file))
    from app.config import get_settings

    get_settings.cache_clear()

    facts = load_fun_facts()
    assert facts == ["Fact one.", "Fact two."]


def test_load_fun_facts_from_txt(tmp_path, monkeypatch):
    reset_fun_facts_cache()
    facts_file = tmp_path / "fun-facts.txt"
    facts_file.write_text("Line one.\nLine two.\n\n", encoding="utf-8")
    monkeypatch.setenv("FUN_FACTS_PATH", str(facts_file))
    from app.config import get_settings

    get_settings.cache_clear()

    facts = load_fun_facts()
    assert facts == ["Line one.", "Line two."]


def test_get_fun_facts_endpoint(client, tmp_path, monkeypatch):
    reset_fun_facts_cache()
    facts_file = tmp_path / "fun-facts.json"
    facts_file.write_text(json.dumps(["A fun fact."]), encoding="utf-8")
    monkeypatch.setenv("FUN_FACTS_PATH", str(facts_file))
    from app.config import get_settings

    get_settings.cache_clear()

    res = client.get("/fun-facts")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 1
    assert data["facts"] == ["A fun fact."]
