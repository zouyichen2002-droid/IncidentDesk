import httpx
from k8s_reliability import connect, create, wait
import json
import subprocess
import time
from pathlib import Path


def k(*args, check=True):
    return subprocess.run(
        ["kubectl", *args], capture_output=True, text=True, check=check
    ).stdout


# A separate observed workload; the investigation worker has no injection privileges.
def apply(obj):
    subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=json.dumps(obj),
        text=True,
        check=True,
        capture_output=True,
    )


base = {
    "apiVersion": "apps/v1",
    "kind": "Deployment",
    "metadata": {"name": "checkout-demo", "namespace": "incident-demo"},
    "spec": {
        "replicas": 1,
        "selector": {"matchLabels": {"app": "checkout-demo"}},
        "template": {
            "metadata": {"labels": {"app": "checkout-demo", "release": "v1"}},
            "spec": {
                "containers": [
                    {
                        "name": "demo",
                        "image": "python:3.12.13-slim-bookworm",
                        "command": ["python", "-m", "http.server", "8088"],
                        "resources": {
                            "requests": {"cpu": "50m", "memory": "32Mi"},
                            "limits": {"cpu": "200m", "memory": "64Mi"},
                        },
                        "livenessProbe": {
                            "httpGet": {"path": "/", "port": 8088},
                            "periodSeconds": 2,
                            "failureThreshold": 2,
                        },
                        "readinessProbe": {
                            "httpGet": {"path": "/", "port": 8088},
                            "periodSeconds": 2,
                        },
                    }
                ]
            },
        },
    },
}
apply(base)
k("-n", "incident-demo", "rollout", "status", "deploy/checkout-demo", "--timeout=120s")
base["spec"]["template"]["metadata"]["labels"]["release"] = "v2-probe-failure"
base["spec"]["template"]["spec"]["containers"][0]["livenessProbe"]["httpGet"][
    "path"
] = "/missing"
base["spec"]["template"]["spec"]["containers"][0]["readinessProbe"]["httpGet"][
    "path"
] = "/missing"
apply(base)
deadline = time.time() + 50
probe = None
while time.time() < deadline:
    pods = json.loads(
        k("-n", "incident-demo", "get", "pods", "-l", "app=checkout-demo", "-o", "json")
    )["items"]
    probe = next(
        (
            p
            for p in pods
            if p["metadata"]["labels"]["release"] == "v2-probe-failure"
            and any(
                c.get("restartCount", 0) > 0
                for c in p["status"].get("containerStatuses", [])
            )
        ),
        None,
    )
    if probe:
        break
    time.sleep(2)
assert probe, "probe failure did not cause restart"
# A controlled allocator with a limit lower than its allocation; actual kernel OOM, not a fake status.
oom = {
    "apiVersion": "v1",
    "kind": "Pod",
    "metadata": {
        "name": "checkout-oom",
        "namespace": "incident-demo",
        "labels": {"app": "checkout-demo", "release": "v3-oom"},
    },
    "spec": {
        "restartPolicy": "Never",
        "containers": [
            {
                "name": "demo",
                "image": "python:3.12.13-slim-bookworm",
                "command": ["python", "-c", "x=bytearray(256*1024*1024)"],
                "resources": {
                    "requests": {"cpu": "50m", "memory": "32Mi"},
                    "limits": {"cpu": "200m", "memory": "64Mi"},
                },
            }
        ],
    },
}
k("-n", "incident-demo", "delete", "pod", "checkout-oom", "--ignore-not-found=true")
apply(oom)
deadline = time.time() + 60
reason = None
while time.time() < deadline:
    p = json.loads(k("-n", "incident-demo", "get", "pod", "checkout-oom", "-o", "json"))
    cs = p["status"].get("containerStatuses", [])
    if cs:
        reason = cs[0]["state"].get("terminated", {}).get("reason")
    if reason:
        break
    time.sleep(2)
assert reason == "OOMKilled", reason
out = {
    "probe_failure": {
        "pod": probe["metadata"]["name"],
        "restart_count": probe["status"]["containerStatuses"][0]["restartCount"],
    },
    "oom": {
        "reason": reason,
        "pod": "checkout-oom",
        "memory_limit": "64Mi",
        "allocation": "256Mi",
    },
    "events": json.loads(k("-n", "incident-demo", "get", "events", "-o", "json"))[
        "items"
    ],
    "pass": True,
}
# Register corresponding releases through the actual structured source and investigate
# while the failing Pod and its events still exist.

for version in ("v2-probe-failure", "v3-oom"):
    response = httpx.post(
        "http://localhost:18090/control",
        headers={"X-Demo-Key": "local-demo-key"},
        json={"release": version},
    )
    response.raise_for_status()
httpx.get("http://localhost:18090/business")
with connect() as client:
    task_id = create(client)
    task = wait(client, task_id)
    report = task["report"]
    assert any("OOMKilled" in c["text"] for c in report["candidates"])
    assert any("探针失败" in c["text"] for c in report["candidates"])
    assert any(
        f.get("transform") == "release-label-equality-v1" for f in report["facts"]
    )
    out["investigation"] = {"id": task_id, "status": task["status"], "report": report}
Path("docs/evidence/k8s-demo-faults.json").write_text(json.dumps(out, indent=2))
print(json.dumps({k: v for k, v in out.items() if k != "events"}, indent=2))
# Restore healthy workload after recording failure; OOM pod retained as diagnostic evidence.
base["spec"]["template"]["metadata"]["labels"]["release"] = "v4-restored"
base["spec"]["template"]["spec"]["containers"][0]["livenessProbe"]["httpGet"][
    "path"
] = "/"
base["spec"]["template"]["spec"]["containers"][0]["readinessProbe"]["httpGet"][
    "path"
] = "/"
apply(base)
