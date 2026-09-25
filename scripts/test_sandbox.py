import json
import subprocess
import tempfile
import uuid
from pathlib import Path
from sandbox import analyze

out = {}
diagnostics = {}


def probe(name, command):
    result = subprocess.run(command, capture_output=True, timeout=15)
    diagnostics[name] = {
        "returncode": result.returncode,
        "stdout": result.stdout.decode(errors="replace")[-2000:],
        "stderr": result.stderr.decode(errors="replace")[-2000:],
    }
    return result


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
    "--memory-swap=64m",
    "--cpus=.5",
    "--pids-limit=16",
    "--entrypoint",
    "python",
    "incidentdesk-sandbox:0.1.0",
    "-I",
    "-c",
]
with tempfile.TemporaryDirectory() as directory:
    # TemporaryDirectory is 0700 on Linux. Let the non-root container access
    # this disposable fixture so the probe tests the mount, not host UID access.
    Path(directory).chmod(0o777)
    (Path(directory) / "readable.txt").write_text("fixture")
    (Path(directory) / "readable.txt").chmod(0o444)
    mounted = (
        base[:3]
        + ["--mount", f"type=bind,src={directory},dst=/input,readonly"]
        + base[3:]
    )
    r = probe(
        "mounted_input_readable",
        mounted + ["from pathlib import Path;assert Path('/input/readable.txt').read_text() == 'fixture'"],
    )
    out["mounted_input_readable"] = r.returncode == 0
    r = probe(
        "read_only_denied",
        mounted + ["from pathlib import Path;Path('/input/deny').write_text('x')"],
    )
    out["read_only_denied"] = r.returncode != 0 and b"Read-only file system" in r.stderr
r = probe(
    "network_denied",
    base + ["import socket;socket.create_connection(('1.1.1.1',443),timeout=1)"],
)
out["network_denied"] = r.returncode != 0 and b"Network is unreachable" in r.stderr
r = probe("memory_limited", base + ["x=bytearray(128*1024*1024)"])
out["memory_limited"] = r.returncode in {-9, 137}
name = "incident-sandbox-timeout-" + uuid.uuid4().hex[:8]
try:
    subprocess.run(
        base[:3] + ["--name", name] + base[3:] + ["import time;time.sleep(60)"],
        capture_output=True,
        timeout=2,
    )
    out["timeout_killed"] = False
except subprocess.TimeoutExpired:
    killed = probe("timeout_cleanup", ["docker", "rm", "-f", name])
    assert killed.returncode == 0, "timed-out container was not removed"
    out["timeout_killed"] = True
Path("docs/evidence").mkdir(parents=True, exist_ok=True)
Path("docs/evidence/sandbox.json").write_text(json.dumps(out, indent=2))
Path("docs/evidence/sandbox-diagnostics.json").write_text(json.dumps(diagnostics, indent=2))
print(json.dumps(out, indent=2))
assert all(out.values()), {key: value for key, value in out.items() if not value}
