import json
import subprocess
import tempfile
from pathlib import Path
from sandbox import analyze

out = {}
out["analysis"] = analyze([{"level": "ERROR"}, {"level": "INFO"}])
assert out["analysis"]["count"] == 2
base = [
    "docker",
    "run",
    "--rm",
    "--network=none",
    "--read-only",
    "--cap-drop=ALL",
    "--security-opt=no-new-privileges",
    "--memory=64m",
    "--cpus=.5",
    "--pids-limit=16",
    "--entrypoint",
    "python",
    "incidentdesk-sandbox:0.1.0",
    "-I",
    "-c",
]
with tempfile.TemporaryDirectory() as directory:
    mounted = (
        base[:3]
        + ["--mount", f"type=bind,src={directory},dst=/input,readonly"]
        + base[3:]
    )
    r = subprocess.run(
        mounted + ["from pathlib import Path;Path('/input/deny').write_text('x')"],
        capture_output=True,
    )
    out["read_only_denied"] = r.returncode != 0 and b"Read-only file system" in r.stderr
r = subprocess.run(
    base + ["import socket;socket.create_connection(('1.1.1.1',443),timeout=1)"],
    capture_output=True,
)
out["network_denied"] = r.returncode != 0
r = subprocess.run(base + ["x=bytearray(128*1024*1024)"], capture_output=True)
out["memory_limited"] = r.returncode in {-9, 137}
name = "incident-sandbox-timeout"
try:
    subprocess.run(
        base[:3] + ["--name", name] + base[3:] + ["import time;time.sleep(60)"],
        capture_output=True,
        timeout=2,
    )
    out["timeout_killed"] = False
except subprocess.TimeoutExpired:
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    out["timeout_killed"] = True
assert all(v for k, v in out.items())
Path("docs/evidence/sandbox.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
