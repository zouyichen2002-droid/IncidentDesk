import json
import subprocess
from pathlib import Path

commands = {
    "agent_cannot_write_business": "SET ROLE incident_agent; INSERT INTO business.admins VALUES('unauthorized');",
    "agent_cannot_read_business": "SET ROLE incident_agent; SELECT * FROM business.actions;",
    "source_cannot_write": "SET ROLE incident_source; UPDATE sources.deployments SET deleted=true;",
    "api_cannot_write_checkpoints": "SET ROLE incident_api; DELETE FROM agent.checkpoints;",
}
out = []
for name, sql in commands.items():
    r = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "postgres",
            "-d",
            "incidentdesk",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0 and "permission denied" in r.stderr, (name, r.stderr)
    out.append({"test": name, "pass": True, "result": r.stderr.strip()})
r = subprocess.run(
    [
        "docker",
        "compose",
        "exec",
        "-T",
        "worker",
        "python",
        "-c",
        "import os;assert not os.getenv('GITHUB_TOKEN');print('No GitHub credential in Worker environment')",
    ],
    capture_output=True,
    text=True,
    check=True,
)
out.append(
    {"test": "worker_no_github_credential", "pass": True, "result": r.stdout.strip()}
)
Path("docs/evidence/db-boundary.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
