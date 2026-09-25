import os
from datetime import datetime, timezone
from typing import Protocol
import httpx
import psycopg
from psycopg.rows import dict_row
from .resilience import Circuit


class Connector(Protocol):
    name: str

    def capabilities(self) -> dict: ...
    def discover(self) -> dict: ...
    def query(self, runtime, step, cursor=None) -> dict: ...
    def health(self) -> bool: ...


class HTTPSource:
    def __init__(self, name):
        self.name = name
        self.circuit = Circuit()

    def capabilities(self):
        return {
            "query": True,
            "pagination": True,
            "deletions": True,
            "incremental": self.name == "logs",
            "scope": "connection plus current task authorization",
            "sync": "incremental" if self.name == "logs" else "rescan",
        }

    def discover(self):
        return {
            "record_fields": [
                "id",
                "event_time",
                "content",
                "locator",
                "version",
                "deleted",
            ],
            "version": "1",
        }

    def health(self):
        try:
            return httpx.get(
                os.getenv("SOURCE_URL", "http://localhost:8090") + "/healthz", timeout=3
            ).is_success
        except httpx.HTTPError:
            return False

    def query(self, runtime, step, cursor=None):
        runtime.authorize(self.name)
        r = self.circuit.call(
            lambda: httpx.post(
                os.getenv("SOURCE_URL", "http://localhost:8090")
                + "/sources/"
                + self.name,
                headers=runtime.headers,
                json={
                    "task": {
                        "id": runtime.run.id,
                        "owner": runtime.run.owner,
                        "generation": runtime.run.generation,
                    },
                    "cursor": cursor,
                    "limit": step.limit,
                },
                timeout=10 if self.name == "logs" else 3,
            )
        )
        r.raise_for_status()
        return r.json()


class DeploymentSource:
    name = "deployments"

    def capabilities(self):
        return {
            "query": True,
            "pagination": True,
            "incremental": True,
            "deletions": True,
            "scope": "current task service",
            "sync": "watermark",
        }

    def discover(self):
        return {
            "record_fields": [
                "id",
                "service",
                "app_id",
                "version",
                "commit_sha",
                "event_time",
                "watermark",
                "deleted",
            ],
            "version": "1",
        }

    def health(self):
        try:
            with psycopg.connect(
                os.environ["SOURCE_DATABASE_URL"], connect_timeout=3
            ) as c:
                c.execute("select 1")
            return True
        except psycopg.Error:
            return False

    def query(self, runtime, step, cursor=None):
        scope = runtime.authorize(self.name)
        with psycopg.connect(
            os.environ["SOURCE_DATABASE_URL"], connect_timeout=3, row_factory=dict_row
        ) as c:
            c.execute("set statement_timeout='3s'")
            rows = c.execute(
                "select * from sources.deployments where service=%s and event_time<=%s and (event_time>=%s or id=(select id from sources.deployments where service=%s and not deleted and event_time<=%s order by event_time desc,watermark desc limit 1)) and watermark>%s order by watermark,id limit %s",
                (
                    scope["service"],
                    scope["end"],
                    scope["start"],
                    scope["service"],
                    scope["start"],
                    int(cursor or 0),
                    step.limit + 1,
                ),
            ).fetchall()
        records = [
            {
                "id": r["id"],
                "content": {k: v for k, v in r.items() if k not in {"event_time"}},
                "event_time": r["event_time"].isoformat(),
                "version": str(r["watermark"]),
                "locator": "postgres://sources/deployments/" + r["id"],
                "deleted": r["deleted"],
            }
            for r in rows
        ]
        return {
            "records": records[: step.limit],
            "next_cursor": str(rows[step.limit - 1]["watermark"])
            if len(rows) > step.limit
            else None,
            "watermark": scope["watermark"],
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "scope": scope,
        }


REGISTRY = {
    "logs": HTTPSource("logs"),
    "deployments": DeploymentSource(),
    "git": HTTPSource("git"),
    "runbook": HTTPSource("runbook"),
    "cluster": HTTPSource("cluster"),
}


def register(connector: Connector):
    if connector.name in REGISTRY:
        raise ValueError("duplicate_connector")
    REGISTRY[connector.name] = connector
