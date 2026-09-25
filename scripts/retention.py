"""Administrative local retention; default 30 days. Metadata remains."""

import argparse
import json
import os
import sys
from pathlib import Path
import psycopg

sys.path.insert(0, str(Path("worker").resolve()))
from incident_worker.artifacts import Artifacts

p = argparse.ArgumentParser()
p.add_argument("--days", type=int, default=30)
args = p.parse_args()
assert args.days >= 1
url = os.getenv(
    "DATABASE_URL",
    "postgres://incident_api:local-api@localhost:55432/incidentdesk?options=-csearch_path%3Dbusiness",
)
with psycopg.connect(url) as c:
    rows = c.execute(
        "update investigations set report=null,manifest=null where created_at<now()-make_interval(days=>%s) returning id",
        (args.days,),
    ).fetchall()
    for (id,) in rows:
        c.execute(
            "update events set payload=jsonb_build_object('retention_removed',true) where investigation=%s",
            (id,),
        )
    c.execute(
        "delete from rate_limits where window_start<extract(epoch from now())-3600"
    )
print(json.dumps({"reports_redacted": len(rows), "days": args.days}))
if os.getenv("CHECKPOINT_DATABASE_URL"):
    with psycopg.connect(os.environ["CHECKPOINT_DATABASE_URL"]) as agent:
        for (task_id,) in rows:
            for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                agent.execute(
                    f"delete from {table} where thread_id like %s",
                    (str(task_id) + ":g%",),
                )
        agent.execute(
            "delete from context_cache where created_at<now()-make_interval(days=>%s)",
            (args.days,),
        )
if os.getenv("S3_ENDPOINT") and os.getenv("CHECKPOINT_DATABASE_URL"):
    print(json.dumps({"objects_removed": Artifacts().cleanup(args.days)}))
