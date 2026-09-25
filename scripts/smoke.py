#!/usr/bin/env python3
import concurrent.futures
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx

BASE = os.getenv("TEST_API", "http://localhost:8080")
SOURCE = os.getenv("TEST_SOURCE", "http://localhost:8090")


def login(user):
    r = httpx.post(
        SOURCE + "/token", json={"username": user, "password": "demo-password"}
    )
    r.raise_for_status()
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def wait(client, id, action=False, timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        r = client.get("/api/v1/investigations/" + id)
        r.raise_for_status()
        v = r.json()
        if action and v.get("action", {}).get("state") in {"succeeded", "unknown"}:
            return v
        if not action and v["status"] not in {"queued", "running"}:
            return v
        time.sleep(0.25)
    raise AssertionError("task_timeout:" + id)


def main():
    results = []

    def check(name, condition, detail=None):
        results.append({"test": name, "pass": bool(condition), "detail": detail})
        assert condition, (name, detail)

    with httpx.Client(base_url=BASE, headers=login("alice"), timeout=15) as c:
        httpx.post(
            SOURCE + "/control",
            headers={"X-Demo-Key": "local-demo-key"},
            json={
                "fault": "pool_exhaustion",
                "drop_issue_response": "false",
                "hide_issues": "false",
            },
        )
        for _ in range(3):
            httpx.get(SOURCE + "/business")
        end = datetime.now(timezone.utc)
        b = {
            "service": "svc-17",
            "symptom": "Investigate pool exhaustion after deployment",
            "start": (end - timedelta(days=1)).isoformat(),
            "end": end.isoformat(),
            "timezone": "UTC",
        }
        key = str(uuid.uuid4())
        r = c.post("/api/v1/investigations", json=b, headers={"Idempotency-Key": key})
        check("create_202", r.status_code == 202, r.text)
        id = r.json()["id"]
        r = c.post("/api/v1/investigations", json=b, headers={"Idempotency-Key": key})
        check("idempotent_create", r.json()["id"] == id)
        r = c.post(
            "/api/v1/investigations",
            json={**b, "symptom": "different"},
            headers={"Idempotency-Key": key},
        )
        check("idempotency_conflict", r.status_code == 409)
        i = wait(c, id)
        check("investigation_terminal", i["status"] in {"completed", "partial"}, i)
        check(
            "four_sources",
            len({e["source"] for e in i["report"]["evidence"]}) == 4,
            i["report"].get("missing"),
        )
        check(
            "candidates_grounded",
            bool(i["report"]["candidates"])
            and all(x["evidence"] for x in i["report"]["candidates"]),
        )
        r = httpx.get(BASE + "/api/v1/investigations/" + id, headers=login("carol"))
        check("cross_team_report_denied", r.status_code == 403)
        r = httpx.get(BASE + "/api/v1/investigations/" + id, headers=login("admin"))
        check("admin_not_business_reader", r.status_code == 403)
        draft = {
            "version": 0,
            "title": "Investigate database pool",
            "body": "Evidence-backed investigation. Verify deployed pool config.",
        }
        r = c.put("/api/v1/investigations/" + id + "/action", json=draft)
        check("draft_created", r.status_code == 200, r.text)
        r = httpx.post(
            BASE + "/api/v1/investigations/" + id + "/action/approve",
            headers=login("bob"),
            json={"version": 1},
        )
        check("investigator_cannot_approve", r.status_code == 403)
        r = c.post(
            "/api/v1/investigations/" + id + "/action/approve", json={"version": 0}
        )
        check("stale_version_denied", r.status_code == 409)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            rs = list(
                pool.map(
                    lambda _: c.post(
                        "/api/v1/investigations/" + id + "/action/approve",
                        json={"version": 1},
                    ),
                    range(8),
                )
            )
        check(
            "concurrent_approve_idempotent",
            all(r.status_code == 200 for r in rs),
            [r.status_code for r in rs],
        )
        i = wait(c, id, True)
        check("stub_issue_readback", i["action"]["state"] == "succeeded", i["action"])
        marker = i["action"]["marker"]
        issues = httpx.get(SOURCE + "/github/repos/local/incident-demo/issues").json()
        check("one_logical_issue", sum(marker in x["body"] for x in issues) == 1)
        r = c.get("/api/v1/investigations/" + id + "/replay")
        check(
            "recording_export",
            r.status_code == 200 and r.json()["mode"] == "offline_no_writes",
        )
        Path("docs/evidence/recording.json").write_text(
            json.dumps(r.json(), indent=2, ensure_ascii=False)
        )
        ev = c.get("/api/v1/investigations/" + id + "/events").json()
        after = ev[len(ev) // 2]["seq"]
        re = c.get(
            "/api/v1/investigations/" + id + "/events", params={"after": after}
        ).json()
        check("event_cursor_replay", re == [e for e in ev if e["seq"] > after])
        mem = c.post(
            "/api/v1/investigations/" + id + "/memory",
            json={
                "content": "Confirmed demo remediation: verify pool configuration before release."
            },
        ).json()
        check(
            "memory_candidate_hidden",
            all(x["id"] != mem["id"] for x in c.get("/api/v1/memories").json()),
        )
        r = c.post("/api/v1/memories/" + mem["id"] + "/confirm", json={})
        check("memory_review", r.status_code == 200)
        check(
            "memory_visible_after_review",
            any(x["id"] == mem["id"] for x in c.get("/api/v1/memories").json()),
        )
        c.post("/api/v1/memories/" + mem["id"] + "/revoke", json={})
        check(
            "memory_revocation",
            all(x["id"] != mem["id"] for x in c.get("/api/v1/memories").json()),
        )
        bad = c.post(
            "/api/v1/investigations/" + id + "/badcase",
            json={
                "category": "inference",
                "label": "human-labelled demonstration, development regression only",
            },
        )
        check("badcase_reviewed", bad.json()["status"] == "reviewed")
        # Ambiguous write: stub commits but delays response longer than Go timeout.
        httpx.post(
            SOURCE + "/control",
            headers={"X-Demo-Key": "local-demo-key"},
            json={"drop_issue_response": "true"},
        )
        r = c.post(
            "/api/v1/investigations",
            json=b,
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        id2 = r.json()["id"]
        wait(c, id2)
        c.put(
            "/api/v1/investigations/" + id2 + "/action", json=draft
        ).raise_for_status()
        c.post(
            "/api/v1/investigations/" + id2 + "/action/approve", json={"version": 1}
        ).raise_for_status()
        i2 = wait(c, id2, True)
        check("write_timeout_unknown", i2["action"]["state"] == "unknown", i2["action"])
        time.sleep(16)
        i2 = wait(c, id2, True)
        check("unknown_reconciled", i2["action"]["state"] == "succeeded", i2["action"])
        httpx.post(
            SOURCE + "/control",
            headers={"X-Demo-Key": "local-demo-key"},
            json={"drop_issue_response": "false"},
        )
    Path("docs/evidence/smoke.json").write_text(
        json.dumps(
            {"mode": "local-stub-and-deterministic", "results": results}, indent=2
        )
    )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
