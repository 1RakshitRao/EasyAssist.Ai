"""Print the latest query trace from audit.db."""
import json
import sqlite3
import sys
from pathlib import Path

db = Path(__file__).resolve().parents[1] / "data" / "audit.db"
if not db.exists():
    print(f"No audit DB at {db}", file=sys.stderr)
    sys.exit(1)

conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
row = conn.execute(
    """
    SELECT query_id, user_email, query, intent, target_node, model_used,
           duration_ms, created_at, steps_json
    FROM query_traces ORDER BY created_at DESC LIMIT 1
    """
).fetchone()
if not row:
    print("No query traces found.")
    sys.exit(0)

data = dict(row)
steps = json.loads(data.pop("steps_json") or "[]")
print(f"query_id: {data['query_id'][:8]}... ({data['query_id']})")
print(f"user:     {data['user_email']}")
print(f"query:    {data['query']}")
print(f"intent:   {data['intent']}  node: {data['target_node']}  model: {data['model_used']}")
print(f"duration: {data['duration_ms']:.0f}ms  steps: {len(steps)}")
print()
for s in steps:
    agent = (s.get("agent") or "?")[:16].ljust(16)
    qid = (s.get("query_id") or "")[:8]
    msg = (s.get("message") or "").replace("\u2192", "->")
    print(f"[{agent}] [{qid}] {msg}")
