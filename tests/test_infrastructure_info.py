"""Tests for infrastructure informational queries."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.agents.supervisor import supervise
from app.infrastructure import store
from app.rag.chroma_store import SEED_DIR


def test_it_seed_json_contains_printer_doc():
    docs = json.loads((SEED_DIR / "it.json").read_text(encoding="utf-8"))
    printer_docs = [d for d in docs if "printer" in d.get("title", "").lower()]
    assert printer_docs
    assert any("toshiba" in d.get("content", "").lower() for d in printer_docs)


def test_supervisor_routes_infrastructure_info_keyword():
    result = supervise("where is the nearest printer?", user_role="employee")
    assert result["intent"] == "infrastructure_info"


@patch("app.infrastructure.info_agent.classify_node")
@patch("app.infrastructure.info_agent.retrieve_node")
@patch("app.infrastructure.info_agent.answer_node")
def test_run_infrastructure_info_query(mock_answer, mock_retrieve, mock_classify):
    from app.infrastructure.info_agent import run_infrastructure_info_query

    mock_classify.return_value = {"department": "it", "severity": "routine", "token_usage": {}}
    mock_retrieve.return_value = {
        "chunks": [{"title": "Office Printers", "content": "NY HQ 4th floor"}],
        "sources": ["Office Printers"],
        "context_used": True,
        "token_usage": {},
    }
    mock_answer.return_value = {
        "answer": "The nearest printer is on the 4th floor.",
        "model_used": "test",
        "context_used": True,
        "token_usage": {},
    }

    result = run_infrastructure_info_query(
        query="where is the printer?",
        normalized_query="where is the printer?",
        user_email="employee@ampcus.com",
    )
    assert "printer" in result["answer"].lower()
    assert result["department"] == "it"


def test_default_printer_seed_and_lookup():
    store.seed_office_printers_if_empty()
    printer = store.get_default_printer()
    assert printer is not None
    assert printer["printer_ip"] == "10.1.0.22"
    assert printer["ipp_port"] == 50081
    assert "TOSHIBA" in (printer.get("printer_name") or "").upper()
