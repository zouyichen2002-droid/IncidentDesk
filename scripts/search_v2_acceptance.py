#!/usr/bin/env python3
"""Real Mistral acceptance against the isolated public-log stack (small paid run)."""

import asyncio, json, time, uuid
from pathlib import Path
import httpx

ROOT = Path("docs/evidence/search-v2")
CASES = [
    ("rare", "alice", "查BGL在2005年11月3日的异常日志", 202),
    ("block", "carol", "查HDFS在2008年11月9日 blk_-1608999687919862906 的日志", 202),
    ("empty", "alice", "查BGL在2005年11月3日包含“zznonexistentmarker91472”的日志", 202),
    ("forbidden", "alice", "查HDFS在2008年11月9日的错误日志", 200),
    ("wide", "alice", "查BGL在2005年11月1日到2005年11月30日的异常", 200),
]


async def main():
    ROOT.mkdir(exist_ok=True)
    async with httpx.AsyncClient(timeout=40) as c:
        auth = {}
        for user in ("alice", "carol"):
            r = await c.post(
                "http://localhost:28090/token",
                json={"username": user, "password": "demo-password"},
            )
            r.raise_for_status()
            auth[user] = {"Authorization": "Bearer " + r.json()["access_token"]}

        async def run(case):
            name, user, question, status = case
            h = {**auth[user], "Idempotency-Key": str(uuid.uuid4())}
            body = {"text": question, "timezone": "UTC"}
            t = time.monotonic()
            r = await c.post(
                "http://localhost:28080/api/v1/investigations/natural",
                headers=h,
                json=body,
            )
            checks = {"expected_status": r.status_code == status}
            result = {
                "case": name,
                "question": question,
                "create_status": r.status_code,
                "create_s": round(time.monotonic() - t, 3),
                "checks": checks,
            }
            if r.status_code == 202:
                identity = r.json()["id"]
                result["id"] = identity
                for _ in range(100):
                    d = (
                        await c.get(
                            "http://localhost:28080/api/v1/investigations/" + identity,
                            headers=h,
                        )
                    ).json()
                    if d["status"] not in ("queued", "running"):
                        break
                    await asyncio.sleep(1)
                report = d.get("report") or {}
                es = report.get("evidence", [])
                logs = [e for e in es if e["source"] == "logs"]
                ids = {e["id"] for e in es}
                events = (
                    await c.get(
                        f"http://localhost:28080/api/v1/investigations/{identity}/events",
                        headers=h,
                    )
                ).json()
                result.update(
                    status=d["status"],
                    elapsed_s=round(time.monotonic() - t, 3),
                    mode=report.get("mode"),
                    retrieval=report.get("retrieval"),
                    log_evidence=len(logs),
                    answer=report.get("answer"),
                    model=report.get("model"),
                    query=d.get("query"),
                )
                checks.update(
                    real_mistral_report=report.get("mode") == "mistral",
                    planner_mistral=any(
                        e["kind"] == "queued"
                        and (e["payload"].get("interpretation") or {}).get("mode")
                        == "mistral"
                        for e in events
                    ),
                    answer_references_resolve=set(report.get("answer_evidence", [])) <= ids,
                    references_resolve=all(
                        ref in ids
                        for claim in report.get("facts", [])
                        + report.get("candidates", [])
                        for ref in claim["evidence"]
                    ),
                    no_unrelated_fixtures=all(e["source"] == "logs" for e in es),
                    bounded_logs=len(logs) <= 60,
                    source_gaps=all(
                        any(m.startswith(s + ":") for m in report.get("missing", []))
                        for s in ["git", "runbook", "deployments"]
                    ),
                )
                replay = await c.post(
                    "http://localhost:28080/api/v1/investigations/natural",
                    headers=h,
                    json=body,
                )
                checks["idempotent"] = (
                    replay.status_code == 202 and replay.json()["id"] == identity
                )
                conflict = await c.post(
                    "http://localhost:28080/api/v1/investigations/natural",
                    headers=h,
                    json={**body, "text": question + " changed"},
                )
                checks["idempotency_conflict"] = conflict.status_code == 409
                other = auth["carol" if user == "alice" else "alice"]
                forbidden = await c.get(
                    "http://localhost:28080/api/v1/investigations/" + identity,
                    headers=other,
                )
                checks["cross_team_denied"] = forbidden.status_code == 403
                if name == "rare":
                    checks["rare_event_found"] = any(
                        "kernel panic" in e["snippet"].get("message", "") for e in logs
                    )
                if name == "block":
                    checks["exact_block"] = bool(logs) and all(
                        "blk_-1608999687919862906" in e["snippet"].get("message", "")
                        for e in logs
                    )
                if name == "empty":
                    checks["empty_honest"] = (
                        not logs
                        and d["status"] == "waiting_information"
                        and report.get("retrieval", {}).get("matched") == 0
                    )
                (ROOT / (name + ".json")).write_text(
                    json.dumps(
                        {"detail": d, "events": events}, ensure_ascii=False, indent=2
                    )
                )
            else:
                result["response"] = r.json()
                checks["clarification"] = (
                    r.status_code == 200
                    and r.json().get("status") == "clarification"
                    and bool(r.json().get("clarification"))
                )
            print(json.dumps(result, ensure_ascii=False), flush=True)
            return result

        # At most two simultaneous model requests; source/API remain available throughout.
        sem = asyncio.Semaphore(2)

        async def bounded(case):
            async with sem:
                return await run(case)

        outcomes = await asyncio.gather(*(bounded(case) for case in CASES))
        (ROOT / "natural-acceptance.json").write_text(
            json.dumps(outcomes, ensure_ascii=False, indent=2)
        )
        assert all(all(r["checks"].values()) for r in outcomes), (
            "See natural-acceptance.json"
        )


if __name__ == "__main__":
    asyncio.run(main())
