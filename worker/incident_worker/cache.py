"""Cache keyed by current scope, source watermark and contract versions."""

import hashlib
import json
import os
import psycopg
from .contracts import ContextBundle


class ContextCache:
    def __init__(self):
        self.db = os.environ["CHECKPOINT_DATABASE_URL"]
        with psycopg.connect(self.db) as c:
            c.execute(
                "create table if not exists context_cache(key text primary key,service text,watermark bigint,bundle jsonb,recording jsonb,created_at timestamptz default now())"
            )
            c.execute(
                "create table if not exists source_index(service text,source text,record_id text,version text,watermark bigint,available bool,primary key(service,source,record_id))"
            )

    def key(self, runtime, scope):
        value = [
            scope["subject"],
            scope["team"],
            scope["service"],
            str(runtime.run.start),
            str(runtime.run.end),
            scope["watermark"],
            scope.get("query", {}),
            "retrieval:2",
            "ontology:1",
            "mapping:2",
        ]
        return hashlib.sha256(json.dumps(value).encode()).hexdigest()

    def get(self, runtime):
        scope = runtime.authorize("context")
        with psycopg.connect(self.db) as c:
            c.execute(
                "delete from context_cache where service=%s and watermark<>%s",
                (scope["service"], scope["watermark"]),
            )
            c.execute(
                "update source_index set available=false where service=%s and watermark<>%s",
                (scope["service"], scope["watermark"]),
            )
            row = c.execute(
                "select bundle,recording from context_cache where key=%s and created_at>now()-interval '30 seconds'",
                (self.key(runtime, scope),),
            ).fetchone()
        if not row:
            return None
        return ContextBundle.model_validate(row[0]), row[1]

    def put(self, runtime, bundle, recording):
        scope = runtime.authorize("context")
        if scope["watermark"] != runtime.run.source_version:
            raise PermissionError("source_changed")
        with psycopg.connect(self.db) as c:
            c.execute(
                "insert into context_cache(key,service,watermark,bundle,recording) values(%s,%s,%s,%s,%s) on conflict(key) do update set bundle=excluded.bundle,recording=excluded.recording,created_at=now()",
                (
                    self.key(runtime, scope),
                    scope["service"],
                    scope["watermark"],
                    bundle.model_dump_json(),
                    json.dumps(recording),
                ),
            )
            for source, result in recording.items():
                for row in result["records"]:
                    c.execute(
                        "insert into source_index values(%s,%s,%s,%s,%s,%s) on conflict(service,source,record_id) do update set version=excluded.version,watermark=excluded.watermark,available=excluded.available",
                        (
                            scope["service"],
                            source,
                            row["id"],
                            row["version"],
                            scope["watermark"],
                            not row.get("deleted", False),
                        ),
                    )
