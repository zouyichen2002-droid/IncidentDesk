#!/usr/bin/env python3
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from incident_worker.evaluation import replay

cases = [
    json.loads(p.read_text()) for p in sorted(Path("evaluation/cases").glob("*.json"))
]
results = []
for c in cases:
    for repeat in range(3 if c["split"] == "heldout" else 1):
        results.append({**replay(c), "repeat": repeat + 1})
old = [replay(c, "regressed") for c in cases if c["split"] == "development"]
report = {
    "mode": "offline deterministic rule checks; NOT human investigation effectiveness or real-model evaluation",
    "cases": len(cases),
    "heldout_cases": sum(c["split"] == "heldout" for c in cases),
    "heldout_repeats": 3,
    "passed": sum(r["pass"] for r in results),
    "runs": len(results),
    "failed": [r for r in results if not r["pass"]],
    "latency_mean_ms": statistics.mean(r["latency_ms"] for r in results),
    "latency_stdev_ms": statistics.stdev(r["latency_ms"] for r in results),
    "human_effectiveness": {
        "status": "external_input_required",
        "scored": 0,
        "threshold": 0.8,
    },
    "regression_gate": {
        "candidate_pass": all(r["pass"] for r in results),
        "injected_regression_blocked": any(not r["pass"] for r in old),
    },
    "per_case": results,
    "version_diffs": [
        {
            "case": r["case"],
            "old_pass": r["pass"],
            "new_pass": next(n["pass"] for n in results if n["case"] == r["case"]),
        }
        for r in old
    ],
}
Path("docs/evidence/evaluation.json").write_text(
    json.dumps(report, indent=2, ensure_ascii=False)
)
print(
    json.dumps(
        {k: v for k, v in report.items() if k not in {"per_case", "version_diffs"}},
        indent=2,
    )
)
assert (
    report["regression_gate"]["candidate_pass"]
    and report["regression_gate"]["injected_regression_blocked"]
)
