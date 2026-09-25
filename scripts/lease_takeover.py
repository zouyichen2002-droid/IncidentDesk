import json
import subprocess
import time
from pathlib import Path
from k8s_reliability import k, connect, create, wait

out = {}
stopped = None
try:
    k("scale", "deploy/worker", "--replicas=3")
    k("set", "env", "deploy/worker", "TEST_DELAY_SECONDS=22")
    k("rollout", "status", "deploy/worker", "--timeout=90s")
    with connect() as c:
        id = create(c)
        deadline = time.time() + 40
        while time.time() < deadline:
            events = c.get("/api/v1/investigations/" + id + "/events").json()
            if any(e["kind"] == "checkpoint_saved" for e in events):
                owner = next(
                    e["payload"]["worker"] for e in events if e["kind"] == "claimed"
                )
                stopped = owner.split(":")[0]
                break
            time.sleep(0.1)
        assert stopped
        k(
            "exec",
            stopped,
            "--",
            "python",
            "-c",
            "import os,signal,pathlib;p=next(int(x.name) for x in pathlib.Path('/proc').iterdir() if x.name.isdigit() and int(x.name)>1 and int(x.name)!=os.getpid() and bytes([0]).join([b'python',b'-m',b'incident_worker.main']) in (x/'cmdline').read_bytes());os.kill(p,signal.SIGSTOP)",
        )
        deadline = time.time() + 24
        claims = []
        while time.time() < deadline:
            events = c.get("/api/v1/investigations/" + id + "/events").json()
            claims = [e for e in events if e["kind"] == "claimed"]
            if len(claims) >= 2:
                break
            time.sleep(0.3)
        assert len(claims) >= 2, "new worker did not take expired lease"
        k(
            "exec",
            stopped,
            "--",
            "python",
            "-c",
            "import os,signal,pathlib;p=next(int(x.name) for x in pathlib.Path('/proc').iterdir() if x.name.isdigit() and int(x.name)>1 and int(x.name)!=os.getpid() and bytes([0]).join([b'python',b'-m',b'incident_worker.main']) in (x/'cmdline').read_bytes());os.kill(p,signal.SIGCONT)",
        )
        stopped = None
        result = wait(c, id, timeout=70)
        events = c.get("/api/v1/investigations/" + id + "/events").json()
        results = [e for e in events if e["kind"] == "result"]
        assert (
            result["status"] in {"completed", "partial"}
            and len(results) == 1
            and results[0]["payload"]["generation"] >= 2
        )
        out = {
            "task": id,
            "claims": claims,
            "result_events": results,
            "terminal": result["status"],
            "pass": True,
        }
        Path("docs/evidence/lease-takeover.json").write_text(json.dumps(out, indent=2))
        print(json.dumps(out, indent=2))
finally:
    if stopped:
        subprocess.run(
            [
                "kubectl",
                "-n",
                "incidentdesk",
                "exec",
                stopped,
                "--",
                "python",
                "-c",
                "import os,signal,pathlib;p=next(int(x.name) for x in pathlib.Path('/proc').iterdir() if x.name.isdigit() and int(x.name)>1 and int(x.name)!=os.getpid() and bytes([0]).join([b'python',b'-m',b'incident_worker.main']) in (x/'cmdline').read_bytes());os.kill(p,signal.SIGCONT)",
            ],
            capture_output=True,
        )
    k("set", "env", "deploy/worker", "TEST_DELAY_SECONDS-")
