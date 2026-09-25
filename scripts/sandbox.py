#!/usr/bin/env python3
"""Fixed-program sandbox runner. Never accepts code/commands from the model."""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path


def analyze(records, timeout=5):
    if not isinstance(records, list) or len(records) > 1000:
        raise ValueError("input_limit")
    with tempfile.TemporaryDirectory(prefix="incident-sandbox-") as d:
        root = Path(d)
        (root / "input").mkdir()
        (root / "output").mkdir()
        (root / "output").chmod(0o777)
        (root / "input" / "records.json").write_text(json.dumps(records))
        (root / "input" / "records.json").chmod(0o444)
        name = "incident-sandbox-" + root.name[-8:]
        cmd = [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--memory=64m",
            "--cpus=.5",
            "--pids-limit=16",
            "--mount",
            f"type=bind,src={root / 'input'},dst=/input,readonly",
            "--mount",
            f"type=bind,src={root / 'output'},dst=/output",
            "incidentdesk-sandbox:0.1.0",
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)
            return json.loads((root / "output" / "report.json").read_text())
        finally:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("snapshot")
    a = p.parse_args()
    print(json.dumps(analyze(json.loads(Path(a.snapshot).read_text()))))
