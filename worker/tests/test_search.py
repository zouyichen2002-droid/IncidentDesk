import importlib.util
import json
from pathlib import Path
import sqlite3
import pytest
from incident_worker.natural import NaturalRequest, interpret
from incident_worker.contracts import LogQuery

spec = importlib.util.spec_from_file_location(
    "log_store", Path(__file__).resolve().parents[2] / "demo/log_store.py"
)
logs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(logs)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "logs.sqlite"
    with sqlite3.connect(path) as c:
        c.execute(
            "create table logs(id integer primary key,event_time text,service text,payload text)"
        )
        # Rare, late exception beyond the old first-page cap, and an inaccessible team.
        for n in range(1, 121):
            level = "ERROR" if n == 119 else "INFO"
            msg = "disk checksum failure blk_-123" if n == 119 else "request completed"
            c.execute(
                "insert into logs values(?,?,?,?)",
                (
                    n,
                    f"2005-11-11T00:{n // 60:02d}:{n % 60:02d}+00:00",
                    "svc-17",
                    json.dumps(
                        dict(level=level, message=msg, service_name="checkout-api")
                    ),
                ),
            )
        c.execute(
            "insert into logs values(200,?,?,?)",
            (
                "2005-11-11T01:00:00+00:00",
                "svc-23",
                json.dumps(dict(level="ERROR", message="private checksum failure")),
            ),
        )
    logs.initialize(path)
    return path


SCOPE = {
    "service": "svc-17",
    "start": "2005-11-11T00:00:00Z",
    "end": "2005-11-11T23:59:59Z",
}


def test_late_anomaly_and_full_counts(db):
    r = logs.query(db, SCOPE, {"mode": "anomalies"}, 20)
    assert r["summary"]["total_in_query"] == 120
    assert r["summary"]["matched"] == 1
    assert [e["id"] for e in r["records"]] == ["119"]


def test_keyword_scope_cursor_and_mutation(db):
    result = logs.query(db, SCOPE, {"mode": "search", "terms": ["checksum"]})
    assert [e["id"] for e in result["records"]] == ["119"]
    pages = []
    cursor = None
    while True:
        r = logs.query(db, SCOPE, {"mode": "all"}, 13, cursor)
        pages.extend(e["id"] for e in r["records"])
        cursor = r["next_cursor"]
        if not cursor:
            break
    assert len(pages) == len(set(pages)) == 120
    with sqlite3.connect(db) as c:
        c.execute("delete from logs where id=119")
    assert not logs.query(db, SCOPE, {"mode": "search", "terms": ["checksum"]})[
        "records"
    ]
    # FTS syntax is quoted as data; it cannot bypass service predicates.
    assert not logs.query(
        db, SCOPE, {"mode": "search", "terms": ["checksum OR private"]}
    )["records"]


def test_level_validation_and_empty_window(db):
    with pytest.raises(ValueError):
        logs.query(db, SCOPE, {"levels": ["ERROR');drop table logs;--"]})
    assert (
        logs.query(
            db,
            {**SCOPE, "start": "2020-01-01T00:00:00Z", "end": "2020-01-02T00:00:00Z"},
            {},
        )["summary"]["total_in_query"]
        == 0
    )


def request(text):
    return NaturalRequest(
        text=text,
        timezone="UTC",
        now="2026-09-24T20:00:00Z",
        services=[
            dict(
                id="svc-17",
                name="订单服务",
                aliases=["BGL", "checkout-api"],
                available_to="2006-01-04T16:00:05Z",
            )
        ],
    )


def test_natural_historical_date_and_scope(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    r = interpret(request("BGL在2005年11月11日的异常"))
    assert r["start"].startswith("2005-11-11T00:00:00") and r["end"].startswith(
        "2005-11-11T23:59:59"
    )
    assert r["query"]["mode"] == "anomalies"
    assert interpret(request("查看HDFS的错误日志"))["status"] == "clarification"
    assert interpret(request("查看BGL最近30天的异常"))["status"] == "clarification"


def test_model_entity_filter_and_block_preservation(monkeypatch):
    monkeypatch.setattr("incident_worker.natural.mistral.configured", lambda: True)

    def completion(*args):
        return dict(
            service="svc-17",
            start="2006-01-01T00:00:00Z",
            end="2006-01-02T00:00:00Z",
            query=LogQuery(terms=["BGL"]).model_dump(),
            explanation="test",
            clarification=None,
        ), {}

    monkeypatch.setattr("incident_worker.natural.mistral.complete", completion)
    r = interpret(request("BGL 2005年11月11日 blk_-123"))
    assert r["query"]["terms"] == ["blk_-123"]
    assert r["start"].startswith("2005-11-11")
    assert interpret(request("BGL 2005年11月11日 异常"))["query"]["terms"] == []


def test_rare_pattern_and_anomaly_pagination(db):
    with sqlite3.connect(db) as c:
        for n in range(1, 121):
            c.execute(
                "update logs set payload=? where id=?",
                (
                    json.dumps(
                        dict(
                            level="ERROR",
                            message=f"repeated failure {n}"
                            if n != 119
                            else "unique controller fault",
                            service_name="checkout-api",
                        )
                    ),
                    n,
                ),
            )
    first = logs.query(db, SCOPE, {}, 10)
    assert "119" in [r["id"] for r in first["records"]]
    rows = first["records"]
    cursor = first["next_cursor"]
    while cursor:
        page = logs.query(db, SCOPE, {}, 10, cursor)
        rows.extend(page["records"])
        cursor = page["next_cursor"]
    assert len(rows) == len({r["id"] for r in rows}) == 120


def test_fts_idempotent_initialization_and_update(db):
    logs.initialize(db)
    with sqlite3.connect(db) as c:
        c.execute(
            "update logs set payload=? where id=119",
            (
                json.dumps(
                    dict(
                        level="ERROR",
                        message="replacement unique",
                        service_name="checkout-api",
                    )
                ),
            ),
        )
    assert not logs.query(db, SCOPE, {"terms": ["checksum"]})["records"]
    assert (
        logs.query(db, SCOPE, {"terms": ["replacement"]})["records"][0]["id"] == "119"
    )


def test_normal_logs_are_background_not_anomaly(db):
    with sqlite3.connect(db) as c:
        c.execute("delete from logs where id=119")
    result = logs.query(db, SCOPE, {})
    assert result["records"] and result["summary"]["matched"] == 0


def test_mistral_rejects_invented_answer_reference(monkeypatch):
    from incident_worker import mistral
    from incident_worker.evaluation import OfflineRuntime
    from incident_worker.contracts import RunContext
    from incident_worker.context import assemble

    case = json.loads(
        (
            Path(__file__).resolve().parents[2] / "evaluation/cases/case-00.json"
        ).read_text()
    )
    rt = OfflineRuntime(RunContext.model_validate(case["run"]))
    bundle, _ = assemble(rt, recorded=case["recording"])
    monkeypatch.setattr(
        mistral,
        "complete",
        lambda *a: (
            {
                "answer": "untrusted",
                "answer_evidence": ["invented"],
                "candidates": [],
                "next_steps": [],
            },
            {},
        ),
    )
    with pytest.raises(ValueError, match="ungrounded"):
        mistral.investigate(rt, bundle)


def test_mistral_zero_call_budget_stops_dispatch(monkeypatch):
    from incident_worker import mistral
    from incident_worker.evaluation import OfflineRuntime
    from incident_worker.contracts import RunContext
    from incident_worker.context import assemble

    case = json.loads(
        (
            Path(__file__).resolve().parents[2] / "evaluation/cases/case-00.json"
        ).read_text()
    )
    run = RunContext.model_validate(case["run"])
    run.budget.model_calls = 0
    rt = OfflineRuntime(run)
    bundle, _ = assemble(rt, recorded=case["recording"])
    monkeypatch.setattr(
        mistral, "complete", lambda *a: pytest.fail("model must not be called")
    )
    with pytest.raises(RuntimeError, match="budget"):
        mistral.investigate(rt, bundle)


def test_model_lowercase_levels_and_timeout_expansion(monkeypatch):
    monkeypatch.setattr("incident_worker.natural.mistral.configured", lambda: True)
    monkeypatch.setattr(
        "incident_worker.natural.mistral.complete",
        lambda *a: (
            dict(
                service="svc-17",
                start="2026-09-24T00:00:00Z",
                end="2026-09-24T01:00:00Z",
                query=dict(
                    mode="search",
                    terms=["a", "b", "c", "d", "e", "f"],
                    levels=["error"],
                ),
                explanation="incorrectly clipped to archive",
                clarification=None,
            ),
            {},
        ),
    )
    r = interpret(request("订单服务最近24小时的超时"))
    assert r["query"]["levels"] == ["ERROR"]
    assert r["query"]["terms"][:2] == ["timed out", "timeout"]
    assert r["start"].startswith("2026-09-23T20:00:00")
    assert "incorrectly" not in r["explanation"]


def test_mistral_false_no_hit_uses_retrieval_truth(monkeypatch):
    from incident_worker import mistral
    from incident_worker.evaluation import OfflineRuntime
    from incident_worker.contracts import RunContext
    from incident_worker.context import assemble

    case = json.loads(
        (
            Path(__file__).resolve().parents[2] / "evaluation/cases/case-00.json"
        ).read_text()
    )
    rt = OfflineRuntime(RunContext.model_validate(case["run"]))
    rt.event = lambda *a: None
    bundle, _ = assemble(rt, recorded=case["recording"])
    bundle.retrieval = {"matched": 1, "total_in_query": 1}
    monkeypatch.setattr(
        mistral,
        "complete",
        lambda *a: (
            {
                "answer": "未在最近24小时内检索到超时日志。",
                "answer_evidence": [],
                "candidates": [],
                "next_steps": [],
            },
            {},
        ),
    )
    r = mistral.investigate(rt, bundle)
    assert r["answer_validation"] and "未在" not in r["answer"]
    assert r["answer_evidence"]
    assert r["next_steps"]


def test_config_survives_long_diff_and_zero_log_count(monkeypatch):
    from incident_worker import mistral
    from incident_worker.evaluation import OfflineRuntime
    from incident_worker.contracts import RunContext
    from incident_worker.context import assemble
    from incident_worker.main import report_status

    case = json.loads(
        (
            Path(__file__).resolve().parents[2] / "evaluation/cases/case-00.json"
        ).read_text()
    )
    rt = OfflineRuntime(RunContext.model_validate(case["run"]))
    rt.event = lambda *a: None
    bundle, _ = assemble(rt, recorded=case["recording"])
    bundle.evidence = [e for e in bundle.evidence if e.source == "git"]
    assert bundle.evidence
    target = bundle.evidence[0]
    target.snippet = {
        "diff": "x" * 8000,
        "config": '{"pool_size":1}',
        "config_path": "config.json",
    }
    bundle.retrieval = {"matched": 0}
    bundle.missing = ["logs: no accessible records in scope"]

    def completion(schema, messages, *args):
        payload = json.loads(messages[1]["content"])
        git = next(e for e in payload["evidence"] if e["source"] == "git")
        assert git["content"]["config_path"] == "config.json"
        assert git["content"]["config"] == '{"pool_size":1}'
        assert len(git["content"]["diff"]) == 500 and git["locator"]
        assert payload["source_evidence_counts"]["git"] == 1
        return {
            "answer": "配置在config.json，pool_size=1",
            "answer_evidence": [target.id],
            "candidates": [],
            "next_steps": [],
        }, {}

    monkeypatch.setattr(mistral, "complete", completion)
    result = mistral.investigate(rt, bundle)
    assert report_status(result) == "partial"
    result["answer_evidence"] = []
    assert report_status(result) == "waiting_information"
