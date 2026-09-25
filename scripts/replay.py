#!/usr/bin/env python3
"""Historical replay never runs tools. Re-evaluation uses only complete recordings."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from incident_worker.contracts import RunContext
from incident_worker.evaluation import OfflineRuntime
from incident_worker.context import assemble, report

p = argparse.ArgumentParser()
p.add_argument("recording")
p.add_argument("--reevaluate", action="store_true")
a = p.parse_args()
data = json.loads(Path(a.recording).read_text())
original = data["report"]
context = original["context"]
scope = context["scope"]
plan = context["plan"]
recorded = data["manifest"]["snapshots"]
if any(step["source"] not in recorded for step in plan["steps"]):
    raise RuntimeError("unreplayable_missing_recording")
ids = {e["id"] for e in original["evidence"]}
assert all(
    c["evidence"] and set(c["evidence"]) <= ids
    for c in original["facts"] + original["candidates"]
)
result = original
if a.reevaluate:
    run = RunContext(
        protocol_version=1,
        id="offline",
        subject=scope["subject"],
        team=scope["team"],
        service=scope["service"],
        symptom="replay",
        start=plan["start"],
        end=plan["end"],
        source_version=1,
        generation=1,
        owner="offline",
        lease_seconds=15,
        budget={
            "steps": 12,
            "seconds": 120,
            "output_bytes": 262144,
            "model_calls": 0,
            "tokens": 12000,
        },
    )
    bundle, _ = assemble(OfflineRuntime(run), recorded=recorded)
    result = report(bundle)
print(
    json.dumps(
        {
            "mode": "offline_reevaluation" if a.reevaluate else "historical_replay",
            "writes_enabled": False,
            "original_facts": len(original["facts"]),
            "current_facts": len(result["facts"]),
            "changed": original["facts"] != result["facts"],
            "pass": True,
        }
    )
)
