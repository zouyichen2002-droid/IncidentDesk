"""Offline only: no imports of HTTP/Issue clients in replay runtime."""

import time
from .contracts import RunContext
from .context import assemble, report


class OfflineRuntime:
    def __init__(self, run):
        self.run = run
        self.events = []
        self.calls = 0

    def authorize(self, tool):
        if tool not in {"logs", "deployments", "git", "runbook", "cluster", "context"}:
            raise PermissionError("offline_write_denied")
        self.calls += 1
        if self.calls > self.run.budget.steps:
            raise RuntimeError("budget_exhausted")
        return {"team": self.run.team, "service": self.run.service}

    def hook(self, name, data, policy=True):
        if not policy:
            raise PermissionError("policy_denied")
        self.events.append({"hook": name, "data": data, "status": "pass"})

    def event(self, kind, payload):
        self.events.append({"kind": kind, "payload": payload})


def replay(case, variant="current"):
    rt = OfflineRuntime(RunContext.model_validate(case["run"]))
    start = time.perf_counter()
    bundle, _ = assemble(rt, recorded=case["recording"])
    result = report(bundle)
    if variant == "regressed":
        result["candidates"] = [
            {
                "text": "unsupported definite root cause",
                "evidence": [],
                "label": "confirmed",
            }
        ]
    ids = {e["id"] for e in result["evidence"]}
    expected = case["expected"]
    checks = {
        "fact_count": len(result["facts"]) == expected["facts"],
        "candidate_count": len(result["candidates"]) == expected["candidates"],
        "conflicts": len(result["conflicts"]) == expected["conflicts"],
        "missing": len(result["missing"]) == expected["missing"],
        "grounding": all(
            c["evidence"] and set(c["evidence"]) <= ids
            for c in result["facts"] + result["candidates"]
        ),
        "no_writes": rt.calls <= len(case["recording"]),
    }
    return {
        "case": case["id"],
        "variant": variant,
        "split": case["split"],
        "checks": checks,
        "pass": all(checks.values()),
        "latency_ms": (time.perf_counter() - start) * 1000,
        "tool_calls": rt.calls,
        "model_tokens": 0,
        "model_cost_usd": 0,
        "hooks": rt.events,
    }
