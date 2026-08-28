"""Standalone Grok API smoke test — run before wiring LangGraph."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.llm_provider import get_llm  # noqa: E402


def main() -> None:
    llm = get_llm("fast")
    response = llm.invoke(
        [
            ("system", "You are a helpful HR assistant."),
            (
                "human",
                "What is the standard notice period for resignation?",
            ),
        ]
    )
    print(response.content)
    meta = getattr(response, "usage_metadata", None)
    if meta:
        print(f"\nTokens used: {meta}")


if __name__ == "__main__":
    main()
