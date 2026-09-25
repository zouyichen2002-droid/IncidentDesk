import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx

os.environ["TEST_API"] = "http://localhost:18080"
os.environ["TEST_SOURCE"] = "http://localhost:18090"
from smoke import login, BASE, wait


def k(*args):
    return subprocess.run(
        ["kubectl", "-n", "incidentdesk", *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def connect():
    return httpx.Client(base_url=BASE, headers=login("alice"), timeout=15)


def create(c):
    end = datetime.now(timezone.utc)
    r = c.post(
        "/api/v1/investigations",
        json={
            "service": "svc-17",
            "symptom": "Kubernetes failure recovery test",
            "start": (end - timedelta(days=1)).isoformat(),
            "end": end.isoformat(),
            "timezone": "UTC",
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    r.raise_for_status()
    time.sleep(0.03)
    return r.json()["id"]


def measure(replicas, n=30):
    k("scale", "deploy/worker", f"--replicas={replicas}")
    k("rollout", "status", "deploy/worker", "--timeout=90s")
    with connect() as c:
        start = time.monotonic()
        ids = [create(c) for _ in range(n)]
        finished = {}
        claimed = {}
        while len(finished) < n and time.monotonic() - start < 120:
            for i in c.get("/api/v1/investigations").json():
                if i["id"] in ids and i["status"] not in {"queued", "running"}:
                    finished[i["id"]] = i["status"]
            time.sleep(0.25)
        for id in ids:
            events = c.get("/api/v1/investigations/" + id + "/events").json()
            q = next(e for e in events if e["kind"] == "queued")
            cl = next((e for e in events if e["kind"] == "claimed"), None)
            if cl:
                claimed[id] = (
                    datetime.fromisoformat(cl["created_at"])
                    - datetime.fromisoformat(q["created_at"])
                ).total_seconds()
        elapsed = time.monotonic() - start
        assert len(finished) == n and all(
            x in {"completed", "partial", "waiting_information"}
            for x in finished.values()
        ), finished
        return {
            "replicas": replicas,
            "tasks": n,
            "seconds": elapsed,
            "throughput_tasks_s": n / elapsed,
            "mean_queue_seconds": sum(claimed.values()) / len(claimed),
            "terminals": finished,
        }


def main():
    out = {}
    k("set", "env", "deploy/worker", "TEST_DELAY_SECONDS=2")
    k("rollout", "status", "deploy/worker", "--timeout=90s")
    out["one_worker"] = measure(1)
    out["three_workers"] = measure(3)
    Path("docs/evidence/k8s-reliability-progress.json").write_text(
        json.dumps(out, indent=2)
    )
    with connect() as c:
        # Kill the worker after a real persisted checkpoint, before result publication.
        id = create(c)
        end = time.time() + 30
        while time.time() < end:
            ev = c.get("/api/v1/investigations/" + id + "/events").json()
            if any(e["kind"] == "checkpoint_saved" for e in ev):
                break
            time.sleep(0.1)
        else:
            raise AssertionError("checkpoint not observed")
        k("delete", "pods", "-l", "app=worker", "--grace-period=0", "--force")
        i = wait(c, id, timeout=90)
        out["worker_pod_failure"] = {
            "task": id,
            "terminal": i["status"],
            "events": c.get("/api/v1/investigations/" + id + "/events").json(),
        }
        assert i["status"] in {"completed", "partial", "waiting_information"}
        # 100 admitted tasks with controllable delay; server enforces global maximum 10.
        ids = [create(c) for _ in range(100)]
        observed = []
        deadline = time.time() + 180
        while time.time() < deadline:
            metrics = httpx.get(BASE + "/metrics").text
            active = next(
                float(x.split()[-1])
                for x in metrics.splitlines()
                if x.startswith("incident_active_jobs ")
            )
            observed.append(active)
            latest = []
            for offset in (0, 50):
                latest += c.get(
                    "/api/v1/investigations", params={"offset": offset}
                ).json()
            statusmap = {i["id"]: i["status"] for i in latest}
            statuses = [statusmap.get(id, "queued") for id in ids]
            if all(s not in {"queued", "running"} for s in statuses):
                break
            time.sleep(1)
        assert max(observed) <= 10 and all(
            s in {"completed", "partial", "waiting_information"} for s in statuses
        ), statuses
        out["capacity"] = {
            "accepted": 100,
            "terminal_counts": {s: statuses.count(s) for s in set(statuses)},
            "peak_active": max(observed),
        }
    k("set", "env", "deploy/worker", "TEST_DELAY_SECONDS-")
    out["pass"] = True
    Path("docs/evidence/k8s-reliability.json").write_text(json.dumps(out, indent=2))
    print(
        json.dumps(
            {k: v for k, v in out.items() if k not in {"worker_pod_failure"}}, indent=2
        )
    )


if __name__ == "__main__":
    main()
