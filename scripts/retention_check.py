"""Age only a newly created disposable fixture and verify physical retention cleanup."""

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx
import psycopg
from smoke import login, wait

with httpx.Client(
    base_url="http://localhost:8080", headers=login("alice"), timeout=15
) as c:
    end = datetime.now(timezone.utc)
    r = c.post(
        "/api/v1/investigations",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={
            "service": "svc-17",
            "symptom": "Disposable retention fixture",
            "start": (end - timedelta(days=1)).isoformat(),
            "end": end.isoformat(),
            "timezone": "UTC",
        },
    )
    r.raise_for_status()
    id = r.json()["id"]
    task = wait(c, id)
    assert task["report"] is not None
    with psycopg.connect(
        "postgres://postgres:local-bootstrap@localhost:55432/incidentdesk"
    ) as db:
        db.execute(
            "update business.investigations set created_at=now()-interval '31 days' where id=%s",
            (id,),
        )
        db.execute(
            "update agent.artifacts set created_at=now()-interval '31 days' where task=%s",
            (id,),
        )
    env = {
        **os.environ,
        "CHECKPOINT_DATABASE_URL": "postgres://incident_agent:local-agent@localhost:55432/incidentdesk?options=-csearch_path%3Dagent",
        "S3_ENDPOINT": "http://localhost:9000",
    }
    r = subprocess.run(
        [sys.executable, "scripts/retention.py"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert c.get("/api/v1/investigations/" + id).json()["report"] is None
    with psycopg.connect(
        "postgres://postgres:local-bootstrap@localhost:55432/incidentdesk"
    ) as db:
        checkpoints = db.execute(
            "select count(*) from agent.checkpoints where thread_id like %s",
            (id + ":g%",),
        ).fetchone()[0]
        artifacts = db.execute(
            "select count(*) from agent.artifacts where task=%s", (id,)
        ).fetchone()[0]
        assert checkpoints == 0 and artifacts == 0
    out = {
        "task": id,
        "report_redacted": True,
        "checkpoints_remaining": checkpoints,
        "objects_metadata_remaining": artifacts,
        "cleanup_output": r.stdout,
        "pass": True,
    }
    Path("docs/evidence/retention.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
