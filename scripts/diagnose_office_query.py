"""Diagnostic: office location queries vs Chroma vs company_facts."""

from __future__ import annotations

import sqlite3

from app.agents.supervisor import _keyword_fallback, supervise
from app.audit.db import init_audit_db
from app.config import get_settings
from app.nlp_query.company_facts import seed_company_facts_if_empty
from app.nlp_query.orchestrator import run_nlp_query
from app.rag.chroma_store import DEPARTMENTS, get_store


def main() -> None:
    settings = get_settings()
    store = get_store()

    print("=== CHROMA COLLECTION COUNTS ===")
    print(store.collection_counts())
    print(f"RETRIEVAL_MAX_DISTANCE: {settings.retrieval_max_distance}")
    print()

    queries = [
        "Is there a Ampcus office in Illinois?",
        "Do we have a Ampcus office in chicago?",
        "Chicago office location",
        "Which offices do we have in Illinois?",
    ]

    for q in queries:
        print(f"=== QUERY: {q}")
        print(f"Keyword fallback intent: {_keyword_fallback(q)['intent']}")
        try:
            s = supervise(q, user_role="employee")
            print(f"Supervisor intent: {s.get('intent')} | {s.get('reason', '')[:100]}")
        except Exception as exc:
            print(f"Supervisor error: {exc}")
        for dept in DEPARTMENTS:
            results = store.query(dept, q, top_k=3)
            if results:
                best = results[0]
                dist = best.get("distance")
                passed = dist is not None and float(dist) <= settings.retrieval_max_distance
                print(
                    f"  chroma/{dept}: best={best.get('title')!r} "
                    f"dist={float(dist):.4f} {'PASS' if passed else 'REJECT'}"
                )
            else:
                print(f"  chroma/{dept}: (empty)")
        print()

    init_audit_db()
    seed_company_facts_if_empty()
    db_path = settings.audit_db_path or "./data/audit.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT name, description, detail_1
        FROM company_facts
        WHERE category = 'locations'
          AND (
            name LIKE '%Chicago%'
            OR name LIKE '%Illinois%'
            OR description LIKE '%Chicago%'
            OR description LIKE '%Illinois%'
          )
        """
    ).fetchall()
    print("=== SQLITE company_facts (Chicago/Illinois) ===")
    for row in rows:
        print(dict(row))
    print("count:", len(rows))
    conn.close()

    print()
    print("=== NLP QUERY PIPELINE (Chicago) ===")
    user = {"id": "diag", "email": "diag@ampcus.com", "role": "employee", "name": "Diag"}
    result = run_nlp_query("Do we have an Ampcus office in Chicago?", user)
    print("allowed:", result.get("nlp_allowed"))
    print("answer preview:", (result.get("answer") or "")[:300])


    print()
    print("=== HEURISTIC CLASSIFY + CHROMA (helpdesk fallback path) ===")
    from app.agents.classifier import heuristic_classify

    for q in queries[:2]:
        c = heuristic_classify(q)
        dept = (c.get("department") or "hr").lower()
        print(f"Q: {q}")
        print(f"  heuristic dept={dept} severity={c.get('severity')}")
        raw = store.query(dept, q, top_k=4)
        for r in raw:
            dist = float(r.get("distance") or 0)
            ok = dist <= settings.retrieval_max_distance
            print(f"    {r.get('title')}: dist={dist:.4f} {'PASS' if ok else 'REJECT'}")


if __name__ == "__main__":
    main()
