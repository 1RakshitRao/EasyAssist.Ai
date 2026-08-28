import json
from pathlib import Path
data = json.loads(Path("app/static/company-facts-data.json").read_text(encoding="utf-8"))
for f in data["facts"]:
    if f.get("category") != "locations":
        continue
    print("---", f["name"])
    print("  desc:", f.get("description"))
    print("  d1:", f.get("detail_1"))
    print("  d2:", f.get("detail_2"))
    print("  attrs:", f.get("attributes"))
