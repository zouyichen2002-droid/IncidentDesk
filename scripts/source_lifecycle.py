"""Real source edits and tombstones, cache, report, and memory invalidation."""

import json
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
import httpx
from k8s_reliability import connect, wait, k

SOURCE = "http://localhost:18090"
checks = []


def check(name, ok):
    checks.append({"test": name, "pass": bool(ok)})
    assert ok, name


def control(body):
    r = httpx.post(
        SOURCE + "/control", headers={"X-Demo-Key": "local-demo-key"}, json=body
    )
    r.raise_for_status()


with connect() as c:
    end = datetime.now(timezone.utc) + timedelta(minutes=1)
    body = {
        "service": "svc-17",
        "symptom": "Source lifecycle verification",
        "start": (end - timedelta(days=1)).isoformat(),
        "end": end.isoformat(),
        "timezone": "UTC",
    }

    def investigate():
        r = c.post(
            "/api/v1/investigations",
            json=body,
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        r.raise_for_status()
        id = r.json()["id"]
        return id, wait(c, id)

    control({"fault": "healthy", "delete_runbook": "false"})
    httpx.get(SOURCE + "/business")
    first, task = investigate()
    second, cached = investigate()
    ev = c.get("/api/v1/investigations/" + second + "/events").json()
    check("same_scope_cache_hit", any(e["kind"] == "cache_hit" for e in ev))
    mem = c.post(
        "/api/v1/investigations/" + first + "/memory",
        json={"content": "Confirmed demonstration observation; not a root cause"},
    )
    mem.raise_for_status()
    mid = mem.json()["id"]
    c.post("/api/v1/memories/" + mid + "/confirm", json={}).raise_for_status()
    check(
        "reviewed_memory_visible",
        any(m["id"] == mid for m in c.get("/api/v1/memories").json()),
    )
    marker = "Versioned runbook lifecycle " + str(uuid.uuid4())
    control(
        {
            "runbook": "# Demo runbook\n"
            + marker
            + "\nVerify the deployment and available evidence."
        }
    )
    notifications = c.get("/api/v1/investigations/" + first + "/events").json()
    check(
        "open_workbench_invalidation_event",
        any(e["kind"] == "source_invalidated" for e in notifications),
    )
    check(
        "modified_report_hidden",
        c.get("/api/v1/investigations/" + first).json()["report"] is None,
    )
    check(
        "modified_memory_expired",
        not any(m["id"] == mid for m in c.get("/api/v1/memories").json()),
    )
    third, fresh = investigate()
    check("fresh_source_read", marker in json.dumps(fresh["report"]))
    check(
        "old_recording_not_exported",
        c.get("/api/v1/investigations/" + first + "/replay").status_code == 410,
    )
    control({"delete_runbook": "true"})
    check(
        "deleted_report_hidden",
        c.get("/api/v1/investigations/" + third).json()["report"] is None,
    )
    fourth, deleted = investigate()
    check(
        "deleted_source_not_in_new_evidence",
        all(e["source"] != "runbook" for e in deleted["report"]["evidence"]),
    )
    sql = "select count(*) from agent.source_index where source='runbook' and available"
    index = k(
        "exec",
        "postgres-0",
        "--",
        "psql",
        "-U",
        "postgres",
        "-d",
        "incidentdesk",
        "-tAc",
        sql,
    ).strip()
    check("index_tombstone", index == "0")
    control({"delete_runbook": "false"})
Path("docs/evidence/source-lifecycle.json").write_text(json.dumps(checks, indent=2))
print(json.dumps(checks, indent=2))
