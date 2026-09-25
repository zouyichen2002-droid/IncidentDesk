#!/usr/bin/env python3
import json
import subprocess
import time
from pathlib import Path

prefix = ["docker", "compose", "exec", "-T", "postgres"]


def cmd(*args, input=None):
    return subprocess.run(
        [*prefix, *args],
        input=input,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout


start = time.monotonic()
dump = cmd("pg_dump", "-U", "postgres", "-d", "incidentdesk", "-Fc")
backup_at = time.time()
name = "restore_" + str(int(backup_at))
cmd("createdb", "-U", "postgres", name)
cmd("pg_restore", "-U", "postgres", "-d", name, "--no-owner", input=dump)
checks = {}
for table in ["investigations", "jobs", "actions", "approvals", "events", "memories"]:
    # Source continues changing under load; compare restored consistency, not live count equality.
    checks[table] = int(
        cmd(
            "psql",
            "-U",
            "postgres",
            "-d",
            name,
            "-Atc",
            "select count(*) from business." + table,
        ).strip()
    )
orphans = int(
    cmd(
        "psql",
        "-U",
        "postgres",
        "-d",
        name,
        "-Atc",
        "select count(*) from business.actions a left join business.investigations i on i.id=a.investigation where i.id is null",
    ).strip()
)
assert orphans == 0 and checks["actions"] > 0 and checks["approvals"] > 0
Path(".local").mkdir(exist_ok=True)
Path(".local/backup.dump").write_bytes(dump)
out = {
    "database": name,
    "backup_bytes": len(dump),
    "rto_seconds": time.monotonic() - start,
    "rpo": "consistent pg_dump snapshot; writes after snapshot are not in restore",
    "counts": checks,
    "orphan_actions": orphans,
    "pass": True,
}
Path("docs/evidence/backup.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
