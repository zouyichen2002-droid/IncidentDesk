import json
import subprocess
import time
from pathlib import Path


def k(*args, check=True):
    return subprocess.run(
        ["kubectl", "-n", "incidentdesk", *args],
        text=True,
        capture_output=True,
        check=check,
    ).stdout


program = """import concurrent.futures,urllib.request,time
end=time.time()+150
def work(_):
 while time.time()<end:
  try: urllib.request.urlopen('http://api:8080/readyz',timeout=2).read()
  except Exception: pass
with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:list(pool.map(work,range(32)))
"""
pod = {
    "apiVersion": "v1",
    "kind": "Pod",
    "metadata": {
        "name": "hpa-load",
        "namespace": "incidentdesk",
        "labels": {"incidentdesk": "true"},
    },
    "spec": {
        "restartPolicy": "Never",
        "containers": [
            {
                "name": "load",
                "image": "python:3.12.13-slim-bookworm",
                "command": ["python", "-c", program],
                "resources": {
                    "requests": {"cpu": "100m", "memory": "64Mi"},
                    "limits": {"cpu": "1", "memory": "192Mi"},
                },
            }
        ],
    },
}
k("delete", "pod", "hpa-load", "--ignore-not-found=true")
subprocess.run(
    ["kubectl", "apply", "-f", "-"],
    input=json.dumps(pod),
    text=True,
    capture_output=True,
    check=True,
)
observations = []
deadline = time.time() + 180
scaled = False
while time.time() < deadline:
    h = json.loads(k("get", "hpa", "api", "-o", "json"))["status"]
    observations.append({"time": time.time(), "status": h})
    if h.get("currentReplicas", 0) > 2:
        scaled = True
        break
    time.sleep(5)
k("delete", "pod", "hpa-load", "--ignore-not-found=true")
deadline = time.time() + 210
down = False
while time.time() < deadline:
    h = json.loads(k("get", "hpa", "api", "-o", "json"))["status"]
    observations.append({"time": time.time(), "status": h})
    if scaled and h.get("currentReplicas") == 2 and h.get("desiredReplicas") == 2:
        down = True
        break
    time.sleep(5)
out = {
    "scale_up": scaled,
    "scale_down": down,
    "observations": observations,
    "pass": scaled and down,
}
Path("docs/evidence/k8s-hpa.json").write_text(json.dumps(out, indent=2))
print(json.dumps({k: v for k, v in out.items() if k != "observations"}))
assert out["pass"]
