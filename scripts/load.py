#!/usr/bin/env python3
"""Real metadata API load, framework-free latency-injected worker measurement is separate."""

import asyncio
import json
import os
import platform
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx
from smoke import login, BASE


async def main():
    duration = int(os.getenv("LOAD_SECONDS", "600"))
    rate = int(os.getenv("LOAD_RPS", "20"))
    results = []
    end = datetime.now(timezone.utc)
    b = {
        "service": "svc-17",
        "symptom": "Load test metadata request",
        "start": (end - timedelta(days=1)).isoformat(),
        "end": end.isoformat(),
        "timezone": "UTC",
    }
    async with httpx.AsyncClient(
        base_url=BASE,
        headers=login("alice"),
        timeout=10,
        limits=httpx.Limits(max_connections=50),
    ) as c:

        async def request(n):
            start = time.perf_counter()
            try:
                if n % 2:
                    r = await c.get("/api/v1/investigations")
                else:
                    r = await c.post(
                        "/api/v1/investigations",
                        json=b,
                        headers={"Idempotency-Key": str(uuid.uuid4())},
                    )
                results.append(
                    {
                        "ms": (time.perf_counter() - start) * 1000,
                        "status": r.status_code,
                        "kind": "list" if n % 2 else "create",
                    }
                )
            except httpx.HTTPError:
                results.append(
                    {
                        "ms": (time.perf_counter() - start) * 1000,
                        "status": 0,
                        "kind": "transport",
                    }
                )

        start = time.monotonic()
        pending = []
        for n in range(duration * rate):
            await asyncio.sleep(max(0, start + n / rate - time.monotonic()))
            pending.append(asyncio.create_task(request(n)))
        await asyncio.gather(*pending)
    times = sorted(x["ms"] for x in results)
    errors = sum(x["status"] not in {200, 202} for x in results)
    hist = {
        str(s): sum(x["status"] == s for x in results)
        for s in {x["status"] for x in results}
    }
    out = {
        "environment": {
            "host": platform.platform(),
            "cpu_count": os.cpu_count(),
            "host_ram_gib": 32,
            "deployment": "Docker Compose",
            "model": "deterministic baseline, separate from API timing",
        },
        "target_rps": rate,
        "duration_seconds": duration,
        "requests": len(results),
        "p50_ms": times[len(times) // 2],
        "p95_ms": times[int(len(times) * 0.95)],
        "max_ms": max(times),
        "non_success": errors,
        "non_success_rate": errors / len(results),
        "statuses": hist,
        "pass": duration >= 600
        and rate >= 20
        and times[int(len(times) * 0.95)] < 500
        and errors / len(results) < 0.01,
    }
    Path("docs/evidence/load.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
