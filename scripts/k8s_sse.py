import json
import subprocess
import time
from pathlib import Path
import httpx

pods = json.loads(
    subprocess.check_output(
        ["kubectl", "-n", "incidentdesk", "get", "pods", "-l", "app=api", "-o", "json"]
    )
)["items"]
names = [p["metadata"]["name"] for p in pods if p["status"]["phase"] == "Running"][:2]
assert len(names) == 2
processes = []
try:
    for name, port in zip(names, [18082, 18083]):
        processes.append(
            subprocess.Popen(
                [
                    "kubectl",
                    "-n",
                    "incidentdesk",
                    "port-forward",
                    "pod/" + name,
                    f"{port}:8080",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
    token = httpx.post(
        "http://localhost:18090/token",
        json={"username": "alice", "password": "demo-password"},
    ).json()["access_token"]
    headers = {"Authorization": "Bearer " + token}
    for _ in range(30):
        try:
            assert (
                httpx.get("http://localhost:18082/readyz").is_success
                and httpx.get("http://localhost:18083/readyz").is_success
            )
            break
        except Exception:
            time.sleep(0.2)
    tasks = httpx.get(
        "http://localhost:18082/api/v1/investigations", headers=headers
    ).json()
    task = next(i for i in tasks if i["status"] in {"completed", "partial"})
    path = "/api/v1/investigations/" + task["id"] + "/events"
    expected = httpx.get("http://localhost:18082" + path, headers=headers).json()
    received = []
    with httpx.stream(
        "GET",
        "http://localhost:18082" + path,
        headers={**headers, "Accept": "text/event-stream"},
        timeout=30,
    ) as response:
        for line in response.iter_lines():
            if line.startswith("data: "):
                received.append(json.loads(line[6:]))
            if len(received) >= 5:
                break
    cursor = received[-1]["seq"]
    with httpx.stream(
        "GET",
        "http://localhost:18083" + path,
        headers={
            **headers,
            "Accept": "text/event-stream",
            "Last-Event-ID": str(cursor),
        },
        timeout=30,
    ) as response:
        for line in response.iter_lines():
            if line.startswith("data: "):
                received.append(json.loads(line[6:]))
            if received[-1]["seq"] == expected[-1]["seq"]:
                break
    ids = [e["seq"] for e in received]
    assert ids == [e["seq"] for e in expected] and len(ids) == len(set(ids))
    out = {
        "replicas": names,
        "task": task["id"],
        "disconnect_cursor": cursor,
        "received": ids,
        "last_event": received[-1]["kind"],
        "pass": True,
    }
    Path("docs/evidence/k8s-sse.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
finally:
    for p in processes:
        p.terminate()
        p.wait(timeout=5)
