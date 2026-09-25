"""Worker termination at durable queue/action boundaries; local Issue stub only."""

import json
import time
from pathlib import Path
import httpx
from k8s_reliability import k, connect, create, wait

out = {}


def workers(n=3):
    k("scale", "deploy/worker", f"--replicas={n}")
    if n:
        k("rollout", "status", "deploy/worker", "--timeout=90s")
    else:
        k("wait", "--for=delete", "pod", "-l", "app=worker", "--timeout=90s")


def kill():
    k("delete", "pods", "-l", "app=worker", "--grace-period=0", "--force")
    k("rollout", "status", "deploy/worker", "--timeout=90s")


def control(b):
    r = httpx.post(
        "http://localhost:18090/control",
        headers={"X-Demo-Key": "local-demo-key"},
        json=b,
    )
    r.raise_for_status()


try:
    with connect() as c:
        workers(0)
        id = create(c)
        assert c.get("/api/v1/investigations/" + id).json()["status"] == "queued"
        workers()
        task = wait(c, id)
        assert task["status"] in {"completed", "partial"}
        out["after_submit"] = {"task": id, "terminal": task["status"]}
        k("set", "env", "deploy/worker", "TEST_BEFORE_QUERY_SECONDS=8")
        k("rollout", "status", "deploy/worker", "--timeout=90s")
        id = create(c)
        deadline = time.time() + 20
        while time.time() < deadline:
            ev = c.get("/api/v1/investigations/" + id + "/events").json()
            if any(e["kind"] == "claimed" for e in ev):
                break
            time.sleep(0.05)
        assert not any(e["kind"] == "checkpoint_saved" for e in ev)
        kill()
        task = wait(c, id, timeout=90)
        ev = c.get("/api/v1/investigations/" + id + "/events").json()
        claims = [e for e in ev if e["kind"] == "claimed"]
        assert len(claims) >= 2 and task["status"] in {"completed", "partial"}
        out["after_claim"] = {"task": id, "claims": claims, "terminal": task["status"]}
        k("set", "env", "deploy/worker", "TEST_BEFORE_QUERY_SECONDS-")
        k("rollout", "status", "deploy/worker", "--timeout=90s")
        r = c.put(
            "/api/v1/investigations/" + id + "/action",
            json={
                "version": 0,
                "title": "Worker recovery demonstration",
                "body": "Reviewed local stub action",
            },
        )
        r.raise_for_status()
        kill()
        assert (
            c.get("/api/v1/investigations/" + id).json()["action"]["state"] == "draft"
        )
        out["waiting_approval"] = {"task": id, "state": "draft"}
        control({"drop_issue_response": "true", "hide_issues": "true"})
        c.post(
            "/api/v1/investigations/" + id + "/action/approve", json={"version": 1}
        ).raise_for_status()
        task = wait(c, id, action=True)
        assert task["action"]["state"] == "unknown"
        kill()
        assert (
            c.get("/api/v1/investigations/" + id).json()["action"]["state"] == "unknown"
        )
        control({"drop_issue_response": "false", "hide_issues": "false"})
        c.post(
            "/api/v1/investigations/" + id + "/action/reconcile", json={"version": 1}
        ).raise_for_status()
        deadline = time.time() + 40
        while time.time() < deadline:
            task = c.get("/api/v1/investigations/" + id).json()
            if task["action"]["state"] == "succeeded":
                break
            time.sleep(0.5)
        assert task["action"]["state"] == "succeeded"
        action = task["action"]
        issues = httpx.get(
            "http://localhost:18090/github/repos/" + action["target"] + "/issues"
        ).json()
        matches = [i for i in issues if action["marker"] in i["body"]]
        assert len(matches) == 1
        out["lost_response"] = {
            "task": id,
            "matching_issues": len(matches),
            "result": action["result"],
        }
    out["pass"] = True
    Path("docs/evidence/recovery-matrix.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
finally:
    control({"drop_issue_response": "false", "hide_issues": "false"})
    k("set", "env", "deploy/worker", "TEST_BEFORE_QUERY_SECONDS-")
    workers()
