"""Run inside demo; isolated files and mocked deployment rows, never edits live sources."""

import sys

sys.path.insert(0, "/app")
import server, json, sqlite3, tempfile, os, subprocess
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone

checks = {}
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    db = root / "logs.sqlite"
    repo = root / "repo"
    repo.mkdir()
    with sqlite3.connect(db) as c:
        c.executescript(
            "create table logs(id integer primary key,event_time text,service text,payload text);create table config(key text primary key,value text);"
        )

    def git(*args, stamp=None):
        env = os.environ.copy()
        if stamp:
            env.update(GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
        return subprocess.check_output(
            ["git", "-C", str(repo), *args],
            env=env,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()

    git("init", "-b", "main")
    git("config", "user.name", "Association Test")
    git("config", "user.email", "test@invalid")
    (repo / "config.json").write_text('{"version":"old"}')
    (repo / "RUNBOOK.md").write_text("old runbook")
    git("add", ".")
    git("commit", "-m", "old", stamp="2020-01-01T00:00:00Z")
    old = git("rev-parse", "HEAD")
    (repo / "config.json").write_text('{"version":"new"}')
    (repo / "RUNBOOK.md").write_text("new runbook")
    git("add", ".")
    git("commit", "-m", "new", stamp="2022-01-01T00:00:00Z")
    scope = {
        "service": "svc-17",
        "start": "2021-01-01T00:00:00+00:00",
        "end": "2021-01-02T00:00:00+00:00",
    }

    class Fake:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, args):
            assert args[0] == scope["service"] and args[1] == scope["end"]
            return self

        def fetchall(self):
            return [(old,)]

    with (
        patch.object(server, "DB", db),
        patch.object(server, "GIT", repo),
        patch.object(server.psycopg, "connect", lambda *a, **k: Fake()),
        patch.dict(os.environ, {"SEED_DATABASE_URL": "mock-only"}),
    ):
        r = server.related_records("runbook", scope)
        checks["runbook_as_of_end"] = (
            len(r) == 1
            and r[0]["content"]["markdown"] == "old runbook"
            and r[0]["version"] == old
        )
        r = server.related_records("git", scope)
        checks["deployed_commit_not_head"] = (
            len(r) == 1
            and r[0]["id"] == old
            and json.loads(r[0]["content"]["config"])["version"] == "old"
        )
        before = {
            **scope,
            "start": "2019-01-01T00:00:00+00:00",
            "end": "2019-01-02T00:00:00+00:00",
        }
        checks["no_future_runbook"] = not server.related_records("runbook", before)
        checks["other_service_no_fixture"] = not server.related_records(
            "git", {**scope, "service": "svc-23"}
        ) and not server.related_records("runbook", {**scope, "service": "svc-23"})
        with sqlite3.connect(db) as c:
            c.execute(
                "insert into logs values(1,?,?,?)",
                (
                    scope["start"],
                    "svc-17",
                    json.dumps({"dataset": "BGL", "message": "historical log"}),
                ),
            )
        checks["public_source_no_demo_fixture"] = not server.related_records(
            "git", scope
        ) and not server.related_records("runbook", scope)
print(json.dumps(checks, indent=2))
assert all(checks.values())
