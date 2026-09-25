#!/usr/bin/env python3
"""Full Loghub ingestion and source benchmark; never touches the default demo volume.

Docker: python /bench-scripts/public_log_benchmark.py prepare|source
Dataset labels are held outside the application's logs payload.
"""

import argparse
from collections import Counter
import csv
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import io
import json
from pathlib import Path
import resource
import sqlite3
import time
import urllib.request
import zipfile

SPECS = {
    "BGL": dict(
        file="BGL.zip",
        member="BGL.log",
        md5="4452953c470f2d95fcb32d5f6e733f7a",
        lines=4747963,
        service="svc-17",
    ),
    "HDFS": dict(
        file="HDFS_v1.zip",
        member="HDFS.log",
        md5="76a24b4d9a6164d543fb275f89773260",
        lines=11175629,
        service="svc-23",
    ),
}
LICENSE = """Loghub datasets: https://github.com/logpai/loghub
Source: https://zenodo.org/records/8196385 (ISSRE 2023 / version v8)
The datasets are freely available for research or academic work, subject to the following condition: For any usage or distribution of the loghub datasets, please refer to the loghub repository URL (https://github.com/logpai/loghub) and cite the loghub paper (Loghub: A Large Collection of System Log Datasets for AI-driven Log Analytics) where applicable.
The above license notice shall be included in all copies of the datasets.
Citation: Jieming Zhu, Shilin He, Pinjia He, Jinyang Liu, Michael R. Lyu. Loghub: A Large Collection of System Log Datasets for AI-driven Log Analytics. ISSRE, 2023.
BGL: Adam J. Oliner, Jon Stearley. What Supercomputers Say: A Study of Five System Logs. DSN, 2007.
HDFS: Wei Xu, Ling Huang, Armando Fox, David Patterson, Michael Jordan. Detecting Large-Scale System Problems by Mining Console Logs. SOSP, 2009.
"""
SQL = "select id,event_time,payload from logs where service=? and event_time>=? and event_time<=? and id>? order by id limit ?"


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False))


def digest(path, algorithm):
    h = hashlib.new(algorithm)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@lru_cache(maxsize=8192)
def epoch_iso(second):
    return datetime.fromtimestamp(int(second), timezone.utc).isoformat()


def prepare(root, evidence, db):
    downloads = root / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    (downloads / "LOGHUB_LICENSE.txt").write_text(LICENSE)
    manifests = {}
    for name, spec in SPECS.items():
        path = downloads / spec["file"]
        url = "https://zenodo.org/records/8196385/files/" + spec["file"] + "?download=1"
        if not path.exists():
            print("download", name, flush=True)
            partial = path.with_suffix(".partial")
            urllib.request.urlretrieve(url, partial)
            partial.replace(path)
        actual = digest(path, "md5")
        if actual != spec["md5"]:
            raise ValueError(f"{name}: archive checksum mismatch")
        manifests[name] = dict(
            url=url,
            archive_bytes=path.stat().st_size,
            md5=actual,
            sha256=digest(path, "sha256"),
        )
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY,event_time TEXT,service TEXT,payload TEXT)"
    )
    if con.execute("select count(*) from logs").fetchone()[0]:
        raise RuntimeError(
            "Refusing to append to nonempty logs; use a fresh benchmark volume"
        )
    con.execute("CREATE TABLE benchmark_alerts(log_id INTEGER PRIMARY KEY,label TEXT)")
    con.commit()
    total = 0
    cases = []
    started = time.perf_counter()
    for name, spec in SPECS.items():
        stamp = time.perf_counter()
        levels, labels, buckets, alerts = Counter(), Counter(), Counter(), Counter()
        first_id = total + 1
        raw_hash = hashlib.sha256()
        min_time, max_time = "9999", ""
        raw_bytes = 0
        batch, truth = [], []
        empty_message_rows = 0
        with zipfile.ZipFile(downloads / spec["file"]) as z:
            if name == "HDFS":
                with z.open("preprocessed/anomaly_label.csv") as f:
                    ground_truth = Counter(
                        row["Label"] for row in csv.DictReader(io.TextIOWrapper(f))
                    )
                manifests[name]["block_labels"] = dict(ground_truth)
            with z.open(spec["member"]) as f:
                for n, raw in enumerate(f, 1):
                    raw_hash.update(raw)
                    raw_bytes += len(raw)
                    line = raw.decode("utf-8", errors="strict").rstrip("\r\n")
                    total += 1
                    if name == "BGL":
                        fields = line.split(" ", 9)
                        if len(fields) < 9:
                            raise ValueError(f"BGL malformed line {n}")
                        if len(fields) == 9:
                            empty_message_rows += 1
                        event_time = epoch_iso(fields[1])
                        level = fields[8]
                        label = fields[0]
                        labels[label] += 1
                        # Ground truth alert category is deliberately not sent to the app.
                        message = line.split(" ", 1)[1]
                        bucket = event_time[:10]
                        if label != "-":
                            truth.append((total, label))
                            alerts[bucket] += 1
                    else:
                        fields = line.split(" ", 5)
                        if (
                            len(fields) != 6
                            or len(fields[0]) != 6
                            or len(fields[1]) != 6
                        ):
                            raise ValueError(f"HDFS malformed line {n}")
                        date, clock = fields[:2]
                        # Original HDFS timestamps have no zone; assume UTC only for replay.
                        event_time = f"20{date[:2]}-{date[2:4]}-{date[4:]}T{clock[:2]}:{clock[2:4]}:{clock[4:]}+00:00"
                        level, message = fields[3], line
                        bucket = event_time[:13]
                    min_time, max_time = (
                        min(min_time, event_time),
                        max(max_time, event_time),
                    )
                    levels[level] += 1
                    buckets[bucket] += 1
                    payload = dict(
                        service_name="checkout-api" if name == "BGL" else "payment-api",
                        level=level,
                        message=message,
                        dataset=name,
                        original_line=n,
                    )
                    batch.append(
                        (
                            total,
                            event_time,
                            spec["service"],
                            json.dumps(payload, separators=(",", ":")),
                        )
                    )
                    if len(batch) >= 10000:
                        con.executemany("insert into logs values(?,?,?,?)", batch)
                        con.executemany(
                            "insert into benchmark_alerts values(?,?)", truth
                        )
                        con.commit()
                        batch.clear()
                        truth.clear()
                    if n % 500000 == 0:
                        print(
                            json.dumps(
                                dict(
                                    dataset=name,
                                    lines=n,
                                    elapsed_s=round(time.perf_counter() - stamp, 2),
                                )
                            ),
                            flush=True,
                        )
            if batch:
                con.executemany("insert into logs values(?,?,?,?)", batch)
                con.executemany("insert into benchmark_alerts values(?,?)", truth)
                con.commit()
            if n != spec["lines"]:
                raise AssertionError((name, n, spec["lines"]))
        manifests[name].update(
            lines=n,
            raw_bytes=raw_bytes,
            raw_sha256=raw_hash.hexdigest(),
            first_id=first_id,
            last_id=total,
            min_time=min_time,
            max_time=max_time,
            levels=dict(levels),
            alert_categories=dict(labels),
            empty_message_rows=empty_message_rows,
            nonstandard_level_rows=sum(
                v
                for k, v in levels.items()
                if k
                not in {
                    "INFO",
                    "FATAL",
                    "WARNING",
                    "WARN",
                    "SEVERE",
                    "ERROR",
                    "FAILURE",
                    "DEBUG",
                    "TRACE",
                }
            ),
            ingestion_s=round(time.perf_counter() - stamp, 3),
            buckets=dict(sorted(buckets.items())),
            alert_buckets=dict(sorted(alerts.items())),
        )
        available = sorted(buckets)
        chosen = {
            available[round((len(available) - 1) * f)]
            for f in (0, 0.1, 0.25, 0.5, 0.75, 0.9, 1)
        }
        if alerts:
            chosen.add(max(alerts, key=alerts.get))
            mixed = [k for k in alerts if buckets[k] > alerts[k]]
            if mixed:
                chosen.add(min(mixed, key=lambda k: alerts[k] / buckets[k]))
        for key in sorted(chosen):
            start = key + ("T00:00:00+00:00" if name == "BGL" else ":00:00+00:00")
            finish = (
                datetime.fromisoformat(start.replace("Z", "+00:00"))
                + (timedelta(days=1) if name == "BGL" else timedelta(hours=1))
                - timedelta(seconds=1)
            )
            cases.append(
                dict(
                    name=name + ":" + key,
                    dataset=name,
                    service=spec["service"],
                    start=start,
                    end=finish.isoformat(),
                    expected_records=buckets[key],
                    expected_alerts=alerts.get(key, 0) if name == "BGL" else None,
                )
            )
        save(evidence / "ingestion-progress.json", manifests)
        print("imported", name, n, flush=True)
    for name, spec in SPECS.items():
        cases.append(
            dict(
                name=name + ":empty",
                dataset=name,
                service=spec["service"],
                start="2020-01-01T00:00:00Z",
                end="2020-01-01T00:59:59Z",
                expected_records=0,
                expected_alerts=0 if name == "BGL" else None,
            )
        )
    count = con.execute("select count(*) from logs").fetchone()[0]
    assert count == total
    check = con.execute("pragma quick_check").fetchone()[0]
    summary = dict(
        datasets=manifests,
        total_rows=count,
        rejected_rows=0,
        db_bytes=db.stat().st_size,
        quick_check=check,
        total_ingestion_s=round(time.perf_counter() - started, 3),
        max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        indexes=con.execute("pragma index_list('logs')").fetchall(),
        cases=cases,
        adaptations=[
            "BGL epoch seconds interpreted UTC",
            "HDFS naive timestamps assumed UTC; original text preserved",
            "BGL maps to svc-17; HDFS maps to svc-23 only for fixed application service aliases",
            "No log multiplication, time shifting, fabricated releases or label injection",
        ],
    )
    save(evidence / "ingestion.json", summary)
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k not in ("datasets", "cases")},
            indent=2,
        ),
        flush=True,
    )


def source(evidence, db, repetitions):
    meta = json.loads((evidence / "ingestion.json").read_text())
    results = []
    with sqlite3.connect(db) as con:
        for case in meta["cases"]:
            times = []
            params = (case["service"], case["start"], case["end"], 0, 51)
            for _ in range(repetitions):
                t = time.perf_counter()
                rows = con.execute(SQL, params).fetchall()
                times.append(round((time.perf_counter() - t) * 1000, 3))
            first_page = rows[:50]
            alert_hits = sum(
                con.execute(
                    "select count(*) from benchmark_alerts where log_id=?", (r[0],)
                ).fetchone()[0]
                for r in first_page
            )
            result = dict(
                **case,
                milliseconds=times,
                returned=len(first_page),
                next_cursor=str(first_page[-1][0]) if len(rows) > 50 else None,
                first_page_ids=[r[0] for r in first_page],
                first_page_alerts=alert_hits if case["dataset"] == "BGL" else None,
                query_plan=con.execute("explain query plan " + SQL, params).fetchall(),
                expected_page_matches=len(first_page)
                == min(case["expected_records"], 50),
            )
            results.append(result)
            print(
                case["name"],
                times,
                "page",
                len(first_page),
                "alerts",
                result["first_page_alerts"],
                flush=True,
            )
            save(
                evidence / "source.json",
                dict(
                    mode="native-volume SQLite exact production SQL; sequential; mixed/warm OS cache, not cold disk",
                    repetitions=repetitions,
                    cases=results,
                ),
            )
    assert all(r["expected_page_matches"] for r in results)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["prepare", "source"])
    p.add_argument("--root", type=Path, default=Path("/benchmark"))
    p.add_argument("--evidence", type=Path, default=Path("/evidence"))
    p.add_argument("--db", type=Path, default=Path("/data/demo.sqlite"))
    p.add_argument("--repetitions", type=int, default=3)
    args = p.parse_args()
    if args.mode == "prepare":
        prepare(args.root, args.evidence, args.db)
    else:
        source(args.evidence, args.db, args.repetitions)
