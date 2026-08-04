"""Role-gated document operation options."""

from __future__ import annotations

from typing import Any, Dict, List

EMPLOYEE_OPS = (
    {
        "id": "summarize",
        "label": "Summarize",
        "description": "Condense into 150–200 words covering the main point and key actions.",
        "needs_question": False,
    },
    {
        "id": "takeaways",
        "label": "Key takeaways",
        "description": "3–7 actionable bullet points.",
        "needs_question": False,
    },
    {
        "id": "actions",
        "label": "Action items",
        "description": "Extract tasks, deadlines, and owners if mentioned.",
        "needs_question": False,
    },
    {
        "id": "explain",
        "label": "Explain simply",
        "description": "Rewrite the core message in plain language.",
        "needs_question": False,
    },
    {
        "id": "risks",
        "label": "Find risks",
        "description": "Highlight obligations, ambiguities, and red flags.",
        "needs_question": False,
    },
    {
        "id": "ask",
        "label": "Ask a question",
        "description": "Ask anything about this document.",
        "needs_question": True,
    },
)

ADMIN_EXTRA = (
    {
        "id": "push_to_kb",
        "label": "Add to KB",
        "description": "Ingest the whole document into a department knowledge base.",
        "needs_question": False,
        "admin_only": True,
    },
)


def get_options(role: str) -> List[Dict[str, Any]]:
    role_n = (role or "employee").strip().lower()
    options = [dict(o) for o in EMPLOYEE_OPS]
    if role_n == "admin":
        options.extend(dict(o) for o in ADMIN_EXTRA)
    return options


def is_allowed_operation(role: str, operation: str) -> bool:
    op = (operation or "").strip().lower()
    return any(o["id"] == op for o in get_options(role))
