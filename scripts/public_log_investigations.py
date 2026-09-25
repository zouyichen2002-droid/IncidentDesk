#!/usr/bin/env python3
"""End-to-end historical Loghub investigation tests against isolated ports only."""

import asyncio
import argparse
from collections import Counter
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import time
import uuid
import httpx

ROOT = Path("docs/evidence/public-logs")
API = "http://localhost:28080"
SOURCE = "http://localhost:28090"


def save(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False))


def percentiles(values):
    values = sorted(values)
    return (
        {
            key: round(values[max(0, math.ceil(len(values) * p) - 1)], 3)
            for key, p in [("p50_s", 0.5), ("p95_s", 0.95), ("max_s", 1)]
        }
        if values
        else {}
    )


async def main():
    cases = json.loads((ROOT / "source.json").read_text())["cases"]
    outcomes = []
    tokens = {}
    async with httpx.AsyncClient(timeout=15) as client:
        for user in ("alice", "carol"):
            r = await client.post(
                SOURCE + "/token", json={"username": user, "password": "demo-password"}
            )
            r.raise_for_status()
            tokens[user] = {"Authorization": "Bearer " + r.json()["access_token"]}

        async def run(case, phase, serial):
            user = "alice" if case["dataset"] == "BGL" else "carol"
            headers = tokens[user]
            body = {k: case[k] for k in ("service", "start", "end")}
            # Unique intervals avoid ContextCache reuse; log resolution is one second.
            body["end"] = (
                datetime.fromisoformat(body["end"].replace("Z", "+00:00"))
                + timedelta(microseconds=serial + 1)
            ).isoformat()
            body.update(
                timezone="UTC",
                symptom=f"[Loghub {phase} {serial}] Investigate public {case['dataset']} system logs in this historical window; identify observations, uncertainty and missing sources.",
            )
            key = str(uuid.uuid4())
            started = time.perf_counter()
            result = dict(
                case=case["name"],
                dataset=case["dataset"],
                phase=phase,
                expected_records=case["expected_records"],
            )
            try:
                r = await client.post(
                    API + "/api/v1/investigations",
                    headers={**headers, "Idempotency-Key": key},
                    json=body,
                )
                result["create_status"] = r.status_code
                r.raise_for_status()
                task = r.json()["id"]
                result["id"] = task
                result["create_ms"] = round((time.perf_counter() - started) * 1000, 3)
                deadline = time.monotonic() + 180
                while True:
                    response = await client.get(
                        API + "/api/v1/investigations/" + task, headers=headers
                    )
                    response.raise_for_status()
                    detail = response.json()
                    if detail["status"] not in ("queued", "running"):
                        break
                    if time.monotonic() > deadline:
                        raise TimeoutError("investigation deadline")
                    await asyncio.sleep(0.5)
                result["elapsed_s"] = round(time.perf_counter() - started, 3)
                result["status"] = detail["status"]
                report = detail.get("report") or {}
                evidence = report.get("evidence", [])
                logs = [e for e in evidence if e["source"] == "logs"]
                result.update(
                    log_evidence=len(logs),
                    total_evidence=len(evidence),
                    candidates=len(report.get("candidates", [])),
                    missing=report.get("missing", []),
                    response_bytes=len(response.content),
                    returned_ids=[int(e["source_record"]) for e in logs],
                    mode=report.get("mode"),
                )
                ids = {e["id"] for e in evidence}
                refs = [
                    ref
                    for f in report.get("facts", []) + report.get("candidates", [])
                    for ref in f["evidence"]
                ]
                lower = datetime.fromisoformat(body["start"].replace("Z", "+00:00"))
                upper = datetime.fromisoformat(body["end"].replace("Z", "+00:00"))
                expected_truncated = case["expected_records"] > 50
                result["checks"] = {
                    "terminal_report": bool(report),
                    "exact_first_page": result["returned_ids"]
                    == case["first_page_ids"],
                    "time_and_dataset_scope": all(
                        lower
                        <= datetime.fromisoformat(
                            e["event_time"].replace("Z", "+00:00")
                        )
                        <= upper
                        and e["snippet"]["dataset"] == case["dataset"]
                        for e in logs
                    ),
                    "bounded_evidence": len(logs) <= 50,
                    "ground_truth_not_in_payload": all(
                        set(e["snippet"])
                        == {
                            "service_name",
                            "level",
                            "message",
                            "dataset",
                            "original_line",
                        }
                        for e in logs
                    ),
                    "references_resolve": all(ref in ids for ref in refs),
                    "truncation_disclosed_when_page_returned": (not expected_truncated)
                    or (not logs)
                    or any("logs: truncated" in m for m in report.get("missing", [])),
                    "missing_logs_disclosed": bool(logs)
                    or any(m.startswith("logs:") for m in report.get("missing", [])),
                    "empty_window_not_completed": bool(case["expected_records"])
                    or detail["status"] == "waiting_information",
                }
                other = tokens["carol" if user == "alice" else "alice"]
                forbidden = await client.get(
                    API + "/api/v1/investigations/" + task, headers=other
                )
                result["checks"]["cross_team_denied"] = forbidden.status_code == 403
                events_response = await client.get(
                    API + "/api/v1/investigations/" + task + "/events", headers=headers
                )
                events_response.raise_for_status()
                events = events_response.json()
                result["cache_hit"] = any(e["kind"] == "cache_hit" for e in events)
                result["checks"]["no_context_cache_hit"] = not result["cache_hit"]
                result["tool_events"] = [
                    e["payload"]["summary"]
                    for e in events
                    if e["kind"] == "hook" and e["payload"].get("name") == "tool_after"
                ]
                result["labelled_alerts_in_first_page"] = (
                    case["first_page_alerts"]
                    if result["checks"]["exact_first_page"]
                    else None
                )
                result["labelled_alerts_in_window"] = case["expected_alerts"]
                if phase == "sequential":
                    replay = await client.get(
                        API + "/api/v1/investigations/" + task + "/replay",
                        headers=headers,
                    )
                    result["checks"]["replay_export"] = (
                        replay.status_code == 200
                        and replay.json().get("mode") == "offline_no_writes"
                    )
                    save(task + ".json", {"investigation": detail, "events": events})
                print(
                    json.dumps(
                        {
                            k: v
                            for k, v in result.items()
                            if k
                            in (
                                "case",
                                "phase",
                                "id",
                                "status",
                                "elapsed_s",
                                "log_evidence",
                                "checks",
                            )
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            except Exception as e:
                result["error"] = type(e).__name__ + ": " + str(e)
                result["elapsed_s"] = round(time.perf_counter() - started, 3)
                print(json.dumps(result), flush=True)
            outcomes.append(result)
            save("investigations-progress.json", outcomes)

        serial = SERIAL_OFFSET
        for case in cases:
            await run(case, "sequential", serial)
            serial += 1
        # 24 investigations, four simultaneously outstanding requests, real worker queue.
        populated = [c for c in cases if c["expected_records"]]
        chosen = [populated[n % len(populated)] for n in range(24)]
        sem = asyncio.Semaphore(4)

        async def bounded(case, n):
            async with sem:
                await run(case, "concurrent-4", n)

        await asyncio.gather(*(bounded(c, serial + n) for n, c in enumerate(chosen)))
    summary = {
        "api": API,
        "dataset_rows": 15923592,
        "worker_replicas": 3,
        "slots_each": 3,
        "model": "deterministic baseline (LangGraph), no external model calls",
        "note": "Full logs stored; per investigation only up to 50 log records, not full-dataset root-cause analysis.",
        "phases": {},
        "results": outcomes,
    }
    for phase in ("sequential", "concurrent-4"):
        values = [r for r in outcomes if r["phase"] == phase]
        summary["phases"][phase] = {
            "tasks": len(values),
            "statuses": dict(Counter(r.get("status", "error") for r in values)),
            **percentiles([r["elapsed_s"] for r in values]),
            "exact_page_success": sum(
                r.get("checks", {}).get("exact_first_page", False) for r in values
            ),
            "with_log_evidence": sum(r.get("log_evidence", 0) > 0 for r in values),
            "check_failures": dict(
                Counter(
                    k for r in values for k, v in r.get("checks", {}).items() if not v
                )
            ),
            "transport_or_runner_errors": sum("error" in r for r in values),
        }
    save("investigations.json", summary)
    print(json.dumps(summary["phases"], indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=ROOT)
    parser.add_argument("--serial-offset", type=int, default=0)
    args = parser.parse_args()
    ROOT = args.evidence
    SERIAL_OFFSET = args.serial_offset
    asyncio.run(main())
