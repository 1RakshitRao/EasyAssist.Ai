"""Public fun facts endpoint for chat loading state."""

from __future__ import annotations

from fastapi import APIRouter

from app.fun_facts.loader import load_fun_facts

router = APIRouter(tags=["fun-facts"])


@router.get("/fun-facts")
def get_fun_facts():
    """Public endpoint — no auth. Facts loaded from data/fun-facts.json."""
    facts = load_fun_facts()
    return {"facts": facts, "count": len(facts)}
