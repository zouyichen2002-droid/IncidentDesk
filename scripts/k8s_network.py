import json
import subprocess
from pathlib import Path

N = "incidentdesk"


def k(*args, check=True):
    return subprocess.run(
        ["kubectl", *args], capture_output=True, text=True, check=check
    )


# Query the actual service IP, so denied DNS cannot masquerade as a denied service connection.
ip = k("-n", N, "get", "svc", "api", "-o", "jsonpath={.spec.clusterIP}").stdout
for name, labels in [("denied", "test=denied"), ("allowed", "incidentdesk=true")]:
    k("-n", N, "delete", "pod", "net-" + name, "--ignore-not-found=true")
    k(
        "-n",
        N,
        "run",
        "net-" + name,
        "--image=rancher/mirrored-library-busybox:1.36.1",
        "--restart=Never",
        "--labels=" + labels,
        "--command",
        "--",
        "sh",
        "-c",
        f"wget -T 3 -qO- http://{ip}:8080/readyz",
    )
    k(
        "-n",
        N,
        "wait",
        "--for=jsonpath={.status.phase}=Succeeded",
        "pod/net-" + name,
        "--timeout=12s",
        check=False,
    )
out = {}
for name in ("denied", "allowed"):
    pod = json.loads(k("-n", N, "get", "pod", "net-" + name, "-o", "json").stdout)
    out[name] = {
        "phase": pod["status"]["phase"],
        "log": k("-n", N, "logs", "net-" + name, check=False).stdout,
    }
out["rbac_allowed"] = k(
    "auth",
    "can-i",
    "list",
    "pods",
    "-n",
    "incident-demo",
    "--as=system:serviceaccount:incidentdesk:demo",
).stdout.strip()
out["rbac_denied"] = k(
    "auth",
    "can-i",
    "list",
    "secrets",
    "-n",
    "incidentdesk",
    "--as=system:serviceaccount:incidentdesk:demo",
    check=False,
).stdout.strip()
out["rbac_cross_namespace"] = k(
    "auth",
    "can-i",
    "list",
    "pods",
    "-n",
    "kube-system",
    "--as=system:serviceaccount:incidentdesk:demo",
    check=False,
).stdout.strip()
out["pass"] = (
    out["denied"]["phase"] == "Failed"
    and out["allowed"]["phase"] == "Succeeded"
    and out["rbac_allowed"] == "yes"
    and out["rbac_denied"] == "no"
    and out["rbac_cross_namespace"] == "no"
)
Path("docs/evidence/k8s-network.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
assert out["pass"]
