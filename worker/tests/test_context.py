import json
from pathlib import Path
import pytest
from incident_worker.contracts import RunContext
from incident_worker.context import resolve, default_plan, validate_plan, assemble
from incident_worker.evaluation import OfflineRuntime, replay
from incident_worker.runtime import Runtime
from incident_worker.gateway import skill, mcp_analyze
from incident_worker.connectors import REGISTRY, register


@pytest.fixture
def case():
    return json.loads(
        (
            Path(__file__).resolve().parents[2] / "evaluation/cases/case-00.json"
        ).read_text()
    )


def test_mapping(case):
    assert resolve("logs", "checkout-api") == "svc-17"
    with pytest.raises(ValueError):
        resolve("logs", "ambiguous")
    with pytest.raises(ValueError):
        resolve("logs", "unknown")


def test_illegal_relation_and_scope(case):
    run = RunContext.model_validate(case["run"])
    p = default_plan(run)
    p.steps[0].path = ["Service", "admin"]
    with pytest.raises(ValueError):
        validate_plan(p, run)
    p = default_plan(run)
    p.service = "svc-23"
    with pytest.raises(PermissionError):
        validate_plan(p, run)


def test_replay_missing_recording_fail_closed(case):
    del case["recording"]["git"]
    with pytest.raises(RuntimeError, match="unreplayable"):
        replay(case)


def test_deleted_not_returned(case):
    case["recording"]["runbook"]["records"][0]["deleted"] = True
    b, _ = assemble(
        OfflineRuntime(RunContext.model_validate(case["run"])),
        recorded=case["recording"],
    )
    assert not any(e.source == "runbook" for e in b.evidence)


def test_prompt_injection_stays_data(case):
    r = replay(case)
    assert r["pass"]
    assert r["tool_calls"] == 4


@pytest.mark.parametrize(
    "hook",
    [
        "plan_validated",
        "retrieval_returned",
        "context_assembled",
        "tool_before",
        "tool_after",
        "run_finished",
    ],
)
def test_hooks_have_positive_negative(hook, case):
    rt = Runtime.__new__(Runtime)
    rt.event = lambda *args: None
    rt.hook(hook, {}, True)
    with pytest.raises(PermissionError):
        rt.hook(hook, {}, False)


def test_skill_disallows_extra_tool(case):
    rt = OfflineRuntime(RunContext.model_validate(case["run"]))
    with pytest.raises(PermissionError):
        skill(rt, "log-analysis", "git", None)


@pytest.mark.asyncio
async def test_actual_mcp_sdk(case):
    rt = OfflineRuntime(RunContext.model_validate(case["run"]))
    r = await mcp_analyze(rt, [{"level": "ERROR"}, {"level": "INFO"}])
    assert r["count"] == 2 and r["levels"] == {"ERROR": 1, "INFO": 1}


def test_connector_contract_extension():
    class Sample:
        name = "sample"

        def capabilities(self):
            return {"query": True, "pagination": True, "deletions": True}

        def discover(self):
            return {"version": "1"}

        def health(self):
            return True

        def query(self, *args):
            return {
                "records": [],
                "next_cursor": None,
                "watermark": 1,
                "observed_at": "2026-09-24T00:00:00Z",
            }

    register(Sample())
    for name, c in REGISTRY.items():
        assert c.capabilities()["query"]
        assert c.discover()["version"] == "1"
        assert callable(c.query) and callable(c.health)
    del REGISTRY["sample"]


def test_framework_free_baseline(case):
    assert replay(case)["pass"]


def test_deepagents_real_harness_with_recorded_model(case):
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.outputs import ChatResult, ChatGeneration
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from incident_worker.harness import deep_report

    class RecordedModel(BaseChatModel):
        index: int = 0

        @property
        def _llm_type(self):
            return "recorded-test-only"

        def bind_tools(self, *args, **kwargs):
            return self

        def _generate(self, *args, **kwargs):
            self.index += 1
            m = (
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "read_context",
                            "args": {},
                            "id": "call_1",
                            "type": "tool_call",
                        }
                    ],
                )
                if self.index == 1
                else AIMessage(
                    content=json.dumps(
                        {"candidates": [], "next_steps": ["Verify evidence"]}
                    )
                )
            )
            return ChatResult(generations=[ChatGeneration(message=m)])

    rt = OfflineRuntime(RunContext.model_validate(case["run"]))
    bundle, _ = assemble(rt, recorded=case["recording"])
    result = deep_report(rt, bundle, InMemorySaver(), model=RecordedModel())
    assert result["mode"] == "deepagents" and result["next_steps"] == [
        "Verify evidence"
    ]


def test_redaction():
    from incident_worker.redaction import redact

    assert redact({"token": "secret", "message": "password=abc"}) == {
        "token": "[REDACTED]",
        "message": "password=[REDACTED]",
    }


def test_protocol_additive_fields_are_compatible(case):
    run = RunContext.model_validate({**case["run"], "future_metadata": "ignored"})
    assert run.service == "svc-17"
    with pytest.raises(Exception):
        RunContext.model_validate({**case["run"], "protocol_version": 2})


def test_cache_reauthorizes_before_read(case):
    from incident_worker.cache import ContextCache

    class Revoked:
        def authorize(self, tool):
            raise PermissionError("revoked")

    cache = ContextCache.__new__(ContextCache)
    with pytest.raises(PermissionError, match="revoked"):
        cache.get(Revoked())


def test_budget_prevents_tool_dispatch(case):
    import time

    rt = Runtime.__new__(Runtime)
    rt.run = RunContext.model_validate(case["run"])
    rt.calls = rt.run.budget.steps
    rt.started = time.monotonic()
    rt.call = lambda *args, **kwargs: pytest.fail("must not dispatch")
    with pytest.raises(RuntimeError, match="budget"):
        rt.authorize("logs")
