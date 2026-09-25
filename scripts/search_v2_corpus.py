"""Run inside demo container against full public corpus; ground truth read only after retrieval."""

import json
from pathlib import Path
import sqlite3
import time
import sys

sys.path.insert(0, "/app")
import log_store

root = Path("/evidence")
cases = json.loads((root / "ingestion.json").read_text())["cases"]
results = []
for case in cases:
    scope = {k: case[k] for k in ("service", "start", "end")}
    t = time.perf_counter()
    cursor = None
    rows = []
    template_scan = 0
    for page in range(3):
        out = log_store.query("/data/demo.sqlite", scope, {}, 20, cursor)
        rows.extend(out["records"])
        template_scan += out["summary"].get("template_scan", 0)
        cursor = out["next_cursor"]
        if not cursor:
            break
    elapsed = time.perf_counter() - t
    alert_count = None
    if case["dataset"] == "BGL":
        with sqlite3.connect("/data/demo.sqlite") as c:
            alert_count = sum(
                c.execute(
                    "select count(*) from benchmark_alerts where log_id=?",
                    (int(r["id"]),),
                ).fetchone()[0]
                for r in rows
            )
    out["summary"]["template_scan"] = template_scan
    result = dict(
        case=case["name"],
        expected_records=case["expected_records"],
        expected_alerts=case["expected_alerts"],
        **out["summary"],
        retrieved=len(rows),
        retrieved_alerts=alert_count,
        seconds=round(elapsed, 3),
        ids=[r["id"] for r in rows],
    )
    results.append(result)
    print(
        json.dumps({k: v for k, v in result.items() if k not in ("ids", "levels")}),
        flush=True,
    )
    (Path("/benchmark") / "search-v2-corpus.json").write_text(
        json.dumps(results, indent=2)
    )
