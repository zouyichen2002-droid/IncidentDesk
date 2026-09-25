"""Indexed, bounded log retrieval. Labels are never used for selection."""

import base64
from datetime import datetime, timezone
import json
import re
import sqlite3
import time

LEVEL = "upper(coalesce(json_extract(payload,'$.level'),'UNKNOWN'))"
ERROR_LEVELS = (
    "ERROR",
    "FATAL",
    "SEVERE",
    "FAILURE",
    "WARN",
    "WARNING",
    "CRITICAL",
    "ALERT",
    "EMERG",
)


def initialize(db):
    with sqlite3.connect(db, timeout=120) as c:
        c.execute("pragma journal_mode=WAL")
        c.execute(
            "create index if not exists logs_service_time_id on logs(service,event_time,id)"
        )
        c.execute(
            f"create index if not exists logs_service_level_time on logs(service,{LEVEL},event_time,id)"
        )
        exists = c.execute(
            "select 1 from sqlite_master where name='logs_fts'"
        ).fetchone()
        c.execute("BEGIN IMMEDIATE")
        c.execute(
            "create view if not exists logs_search_content as select id,json_extract(payload,'$.message') as message from logs"
        )
        c.execute(
            "create virtual table if not exists logs_fts using fts5(message, content='logs_search_content', content_rowid='id')"
        )
        if not exists:
            c.execute("insert into logs_fts(logs_fts) values('rebuild')")
        c.executescript("""
        CREATE TRIGGER IF NOT EXISTS logs_fts_ai AFTER INSERT ON logs BEGIN
          INSERT INTO logs_fts(rowid,message) VALUES(new.id,json_extract(new.payload,'$.message')); END;
        CREATE TRIGGER IF NOT EXISTS logs_fts_ad AFTER DELETE ON logs BEGIN
          INSERT INTO logs_fts(logs_fts,rowid,message) VALUES('delete',old.id,json_extract(old.payload,'$.message')); END;
        CREATE TRIGGER IF NOT EXISTS logs_fts_au AFTER UPDATE ON logs BEGIN
          INSERT INTO logs_fts(logs_fts,rowid,message) VALUES('delete',old.id,json_extract(old.payload,'$.message'));
          INSERT INTO logs_fts(rowid,message) VALUES(new.id,json_extract(new.payload,'$.message')); END;
        """)


def connection(db, seconds=4):
    c = sqlite3.connect(db, timeout=seconds)
    deadline = time.monotonic() + seconds
    c.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
    return c


def canonical(value):
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        .astimezone(timezone.utc)
        .isoformat()
    )


def catalog(db, services):
    result = []
    with connection(db) as c:
        for service in services:
            first = c.execute(
                "select event_time,payload from logs where service=? order by event_time,id limit 1",
                (service,),
            ).fetchone()
            last = c.execute(
                "select event_time from logs where service=? order by event_time desc,id desc limit 1",
                (service,),
            ).fetchone()
            payload = json.loads(first[1]) if first else {}
            result.append(
                dict(
                    id=service,
                    aliases=[
                        x
                        for x in (payload.get("dataset"), payload.get("service_name"))
                        if x
                    ],
                    available_from=first[0] if first else None,
                    available_to=last[0] if last else None,
                    provenance="public-dataset"
                    if payload.get("dataset")
                    else "local-demo",
                )
            )
    return result


def query(db, scope, spec, limit=50, cursor=None):
    limit = max(1, min(100, int(limit)))
    terms = spec.get("terms", [])
    levels = spec.get("levels", [])
    mode = spec.get("mode", "anomalies")
    if (
        mode not in {"anomalies", "search", "all"}
        or len(terms) > 6
        or any(not isinstance(t, str) or not 1 <= len(t) <= 100 for t in terms)
    ):
        raise ValueError("invalid_log_query")
    if len(levels) > 12 or any(
        v not in ERROR_LEVELS + ("INFO", "DEBUG", "TRACE", "UNKNOWN") for v in levels
    ):
        raise ValueError("invalid_levels")
    start, end = canonical(scope["start"]), canonical(scope["end"])
    conditions = ["service=?", "event_time>=?", "event_time<=?"]
    args = [scope["service"], start, end]
    # JSON path restricts FTS matches to the message, not service metadata or labels.
    if terms:
        expression = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
        conditions.append("id in (select rowid from logs_fts where logs_fts match ?)")
        args.append(expression)
    where = " and ".join(conditions)
    with connection(db, 8) as c:
        histogram = dict(
            c.execute(
                f"select {LEVEL},count(*) from logs where {where} group by {LEVEL}",
                args,
            ).fetchall()
        )
        total = sum(histogram.values())
        selected_levels = levels or (
            list(ERROR_LEVELS) if mode == "anomalies" and not terms else []
        )
        if selected_levels:
            conditions.append(
                LEVEL + " in (" + ",".join("?" for _ in selected_levels) + ")"
            )
            args.extend(selected_levels)
        where = " and ".join(conditions)
        matched = (
            sum(histogram.get(level, 0) for level in selected_levels)
            if selected_levels
            else total
        )
        # Deterministic severity-stratified representatives across the entire interval.
        # Keyset paging walks each severity partition instead of only the oldest 50 overall.
        partitions = selected_levels or sorted(
            histogram, key=lambda x: (x not in ERROR_LEVELS, x)
        )
        if mode == "anomalies" and not levels and not matched:
            partitions = sorted(histogram)
            if selected_levels:
                where = " and ".join(conditions[:-1])
                args = args[: -len(selected_levels)]
        positions = {}
        if cursor:
            try:
                if len(str(cursor)) > 4096:
                    raise ValueError("cursor_too_large")
                positions = json.loads(base64.urlsafe_b64decode(str(cursor).encode()))
                if not isinstance(positions, dict):
                    raise ValueError("invalid_cursor")
            except Exception as exc:
                raise ValueError("invalid_cursor") from exc
        records = []
        next_positions = dict(positions)

        def record(row):
            identity, stamp, payload = row
            return dict(
                id=str(identity),
                event_time=stamp,
                content=json.loads(payload),
                locator=f"logs://{scope['service']}/{identity}",
                version=str(identity),
                deleted=False,
            )

        featured = positions.get("_featured", [])
        if (
            not isinstance(featured, list)
            or len(featured) > 50
            or any(not isinstance(n, int) for n in featured)
        ):
            raise ValueError("invalid_cursor")
        template_scan = 0
        if not cursor and mode == "anomalies" and not terms and 0 < matched <= 10000:
            groups = {}
            for row in c.execute(
                f"select id,event_time,payload from logs where {where}", args
            ):
                payload = json.loads(row[2])
                message = payload.get("message", "")
                if payload.get("dataset") == "BGL":
                    message = message.split(" ", 8)[-1]
                elif payload.get("dataset") == "HDFS":
                    message = message.split(" ", 5)[-1]
                signature = re.sub(r"0x[0-9a-fA-F]+|blk_-?\d+|\d+", "#", message)[:500]
                if signature not in groups:
                    groups[signature] = [0, row]
                groups[signature][0] += 1
                template_scan += 1
            rare = sorted(groups.values(), key=lambda x: (x[0], x[1][0]))[
                : max(1, limit // 2)
            ]
            records = [record(row) for _, row in rare]
            featured = [int(r["id"]) for r in records]
            next_positions["_featured"] = featured
        eligible = [level for level in partitions if histogram.get(level, 0)]
        quota = max(1, (limit - len(records)) // max(1, len(eligible)))
        has_more = False
        for level in eligible:
            pos = positions.get(level, [start, 0])
            if (
                not isinstance(pos, list)
                or len(pos) != 2
                or not isinstance(pos[0], str)
                or not isinstance(pos[1], int)
            ):
                raise ValueError("invalid_cursor")
            count = min(quota, limit - len(records))
            if count <= 0:
                has_more = True
                continue
            rows = c.execute(
                f"select id,event_time,payload from logs where {where} and {LEVEL}=? and (event_time,id)>(?,?) order by event_time,id limit ?",
                [*args, level, *pos, count + 1],
            ).fetchall()
            has_more = has_more or len(rows) > count
            for row in rows[:count]:
                identity, stamp, _ = row
                next_positions[level] = [stamp, identity]
                if identity not in featured:
                    records.append(record(row))
        return dict(
            records=records,
            next_cursor=base64.urlsafe_b64encode(
                json.dumps(next_positions).encode()
            ).decode()
            if has_more
            else None,
            summary=dict(
                total_in_query=total,
                matched=matched,
                levels=histogram,
                selection="rare-patterns-and-severity-keyset",
                template_scan=template_scan,
                terms=terms,
                mode=mode,
                labels_used=False,
            ),
            provenance=catalog(db, [scope["service"]])[0]["provenance"],
        )
