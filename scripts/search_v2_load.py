"""Four concurrent investigations over full corpus; run with BENCH_HARNESS=langgraph."""

import asyncio, json, time, uuid, math
from datetime import datetime, timedelta
from pathlib import Path
import httpx

ROOT = Path("docs/evidence/search-v2")


async def main():
    cases = json.loads(Path("docs/evidence/public-logs/ingestion.json").read_text())[
        "cases"
    ]
    cases = [c for c in cases if c["expected_records"]][0:16]
    result = []
    health = []
    done = asyncio.Event()
    sem = asyncio.Semaphore(4)
    async with httpx.AsyncClient(timeout=15) as c:
        auth = {}
        for user in ["alice", "carol"]:
            r = await c.post(
                "http://localhost:28090/token",
                json={"username": user, "password": "demo-password"},
            )
            r.raise_for_status()
            auth[user] = {"Authorization": "Bearer " + r.json()["access_token"]}

        async def probe():
            while not done.is_set():
                t = time.monotonic()
                try:
                    r = await c.get("http://localhost:28090/healthz")
                    health.append({"s": time.monotonic() - t, "status": r.status_code})
                except httpx.HTTPError:
                    health.append({"s": time.monotonic() - t, "status": 0})
                await asyncio.sleep(0.15)

        async def one(n):
            async with sem:
                case = cases[n % len(cases)]
                h = auth["alice" if case["dataset"] == "BGL" else "carol"]
                body = {k: case[k] for k in ["service", "start", "end"]}
                body["end"] = (
                    datetime.fromisoformat(body["end"].replace("Z", "+00:00"))
                    + timedelta(microseconds=20000 + n)
                ).isoformat()
                body.update(symptom=f"Full corpus search-v2 load {n}", timezone="UTC")
                t = time.monotonic()
                r = await c.post(
                    "http://localhost:28080/api/v1/investigations",
                    headers={**h, "Idempotency-Key": str(uuid.uuid4())},
                    json=body,
                )
                r.raise_for_status()
                identity = r.json()["id"]
                for _ in range(150):
                    d = (
                        await c.get(
                            "http://localhost:28080/api/v1/investigations/" + identity,
                            headers=h,
                        )
                    ).json()
                    if d["status"] not in ["queued", "running"]:
                        break
                    await asyncio.sleep(0.2)
                report = d.get("report") or {}
                retrieval = report.get("retrieval", {})
                events = (
                    await c.get(
                        f"http://localhost:28080/api/v1/investigations/{identity}/events",
                        headers=h,
                    )
                ).json()
                item = {
                    "case": case["name"],
                    "id": identity,
                    "seconds": round(time.monotonic() - t, 3),
                    "status": d["status"],
                    "checks": {
                        "has_logs": retrieval.get("evidence_count", 0) > 0,
                        "full_counts": retrieval.get("total_in_query")
                        == case["expected_records"],
                        "no_source_error": not any(
                            "Error" in m for m in report.get("missing", [])
                        ),
                        "no_cache_hit": not any(
                            e["kind"] == "cache_hit" for e in events
                        ),
                    },
                }
                result.append(item)
                print(json.dumps(item), flush=True)

        task = asyncio.create_task(probe())
        try:
            await asyncio.gather(*(one(n) for n in range(24)))
        finally:
            done.set()
            await task

        def stats(a):
            a = sorted(a)
            return {
                "p50": round(a[math.ceil(len(a) * 0.5) - 1], 3),
                "p95": round(a[math.ceil(len(a) * 0.95) - 1], 3),
                "max": round(max(a), 3),
            }

        output = {
            "concurrency": 4,
            "model": "langgraph deterministic, excludes provider latency",
            "runs": result,
            "investigation_seconds": stats([r["seconds"] for r in result]),
            "source_health_seconds": stats([r["s"] for r in health]),
            "source_health_probes": len(health),
            "source_health_failures": sum(r["status"] != 200 for r in health),
        }
        (ROOT / "concurrency.json").write_text(json.dumps(output, indent=2))
        print(json.dumps({k: v for k, v in output.items() if k != "runs"}))
        assert (
            all(all(r["checks"].values()) for r in result)
            and not output["source_health_failures"]
        )


if __name__ == "__main__":
    asyncio.run(main())
