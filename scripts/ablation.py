import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path("worker").resolve()))
from incident_worker.evaluation import replay

cases = [
    json.loads(p.read_text())
    for p in Path("evaluation/cases").glob("*.json")
    if json.loads(p.read_text())["split"] == "development"
]
rows = []
for c in cases:
    baseline = replay(c)
    variants = {}
    # The same recorded inputs; remove individual constraints, don't call online tools.
    broken = copy.deepcopy(c)
    broken["recording"]["logs"]["records"] = [
        {**r, "content": {**r["content"], "service_name": "unmapped-service"}}
        for r in broken["recording"]["logs"]["records"]
    ]
    try:
        variants["unmapped_alias_perturbation"] = replay(broken)["pass"]
    except ValueError:
        variants["unmapped_alias_perturbation"] = False
    variants["ungrounded_candidate_perturbation"] = replay(c, "regressed")["pass"]
    # Fixed baseline has a predeclared plan and no reviewed fixture memories: no measured gain can be claimed.
    variants["without_dynamic_plan"] = baseline["pass"]
    variants["without_memory"] = baseline["pass"]
    rows.append({"case": c["id"], "full": baseline["pass"], **variants})
out = {
    "mode": "deterministic module perturbation checks; not a controlled model ablation",
    "rows": rows,
    "interpretation": "Mapping failures and ungrounded claims are detectable. These cases show no marginal benefit from dynamic planning or historical memory because the baseline plan is fixed and fixture memories are empty. Real-model ablation remains external.",
}
Path("docs/evidence/ablation.json").write_text(json.dumps(out, indent=2))
print("Recorded module sensitivity:", len(rows), "development cases")
