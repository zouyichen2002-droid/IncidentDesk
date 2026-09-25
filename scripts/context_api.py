import json
from pathlib import Path
from k8s_reliability import k, connect, create
import httpx

api = "http://localhost:18080"
context = "http://localhost:18091"
internal = {"X-Worker-Key": "local-worker-key", "X-Protocol-Version": "1"}
k("scale", "deploy/worker", "--replicas=0")
k("wait", "--for=delete", "pod", "-l", "app=worker", "--timeout=90s")
try:
    with connect() as c:
        id = create(c)
        r = httpx.post(
            api + "/internal/v1/claim",
            headers=internal,
            json={"owner": "context-contract-test"},
        )
        r.raise_for_status()
        run = r.json()
        assert run["id"] == id, run["id"]
        r = httpx.post(context + "/context/v1/query", json={"run": run})
        assert r.status_code == 401
        r = httpx.post(
            context + "/context/v1/query",
            headers=internal,
            json={"run": run},
            timeout=30,
        )
        r.raise_for_status()
        bundle = r.json()
        assert len({e["source"] for e in bundle["evidence"]}) >= 3
        wrong = {**run, "service": "svc-23"}
        r = httpx.post(
            context + "/context/v1/query", headers=internal, json={"run": wrong}
        )
        assert r.status_code == 403
        c.post("/api/v1/investigations/" + id + "/cancel", json={}).raise_for_status()
        # The old lease can no longer invoke even a read-only context query.
        r = httpx.post(
            context + "/context/v1/query", headers=internal, json={"run": run}
        )
        assert r.status_code in {403, 409}
        out = {
            "task": id,
            "ordinary_api_sources": sorted({e["source"] for e in bundle["evidence"]}),
            "invalid_identity": 401,
            "cross_scope": 403,
            "cancelled_status": r.status_code,
            "pass": True,
        }
        Path("docs/evidence/context-api.json").write_text(json.dumps(out, indent=2))
        print(json.dumps(out, indent=2))
finally:
    k("scale", "deploy/worker", "--replicas=3")
