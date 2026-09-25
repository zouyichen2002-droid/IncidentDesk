import concurrent.futures
import logging
import os
from pathlib import Path
import signal
import threading
import time
import uuid
import httpx
import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from .contracts import RunContext
from .context import assemble, report
from .harness import graph, deep_report
from .runtime import Runtime

STOP = threading.Event()


def manifest(run, recording, result=None):
    return {
        "version": "1",
        "code": os.getenv("CODE_VERSION", "working-tree"),
        "model": (result or {}).get("model", {}).get("model")
        or (
            os.getenv("MODEL_NAME", "unknown")
            if os.getenv("HARNESS") == "deepagents"
            else "none-deterministic"
        ),
        "model_parameters": {"temperature": 0}
        if os.getenv("HARNESS") == "mistral"
        else {"temperature": "provider-default"},
        "prompt": "investigate-v1",
        "skills": ["release-compare@1", "log-analysis@1"],
        "tool_schema": "1",
        "ontology": "1",
        "source_mapping": "2",
        "retrieval": "indexed-stratified-3-pages-v2",
        "permission_policy": "go-v1",
        "snapshots": recording,
        "evaluator": "rules-v1",
        "cost": {
            "known_model_tokens": (result or {})
            .get("model", {})
            .get("usage", {})
            .get("total_tokens"),
            "estimated_usd": None,
            "unknown": "USD cost not calculated; interpretation usage is in queued event",
        },
        "generation": run.generation,
    }


def report_status(result):
    has_logs = any(e["source"] == "logs" for e in result["evidence"])
    known = {e["id"] for e in result["evidence"]}
    has_answer = bool(set(result.get("answer_evidence", [])) & known)
    if not has_logs and not has_answer:
        return "waiting_information"
    return "partial" if result["missing"] else "completed"


def process(raw):
    run = RunContext.model_validate(raw)
    rt = Runtime(run)
    done = threading.Event()
    lost = threading.Event()

    def heartbeat():
        while not done.wait(3):
            try:
                rt.call("heartbeat")
            except Exception:
                lost.set()
                return

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        before_query = float(os.getenv("TEST_BEFORE_QUERY_SECONDS", "0"))
        if before_query:
            time.sleep(min(before_query, 120))
        with psycopg.connect(
            os.environ["CHECKPOINT_DATABASE_URL"], autocommit=True, prepare_threshold=0
        ) as conn:
            saver = PostgresSaver(conn)
            # Every generation has a distinct namespace: late old writes are unreachable.
            config = {
                "configurable": {
                    "thread_id": run.id + f":g{run.generation}",
                    "checkpoint_ns": "",
                }
            }
            checkpoint = saver.get_tuple(config)
            if not checkpoint and run.generation > 1 and run.attempt > 1:
                previous = saver.get_tuple(
                    {"configurable": {"thread_id": run.id + f":g{run.generation - 1}"}}
                )
                if previous and previous.checkpoint.get("channel_values", {}).get(
                    "report"
                ):
                    rt.authorize("context")
                    # Reuse only recorded computation if the source watermark still matches.
                    scope = rt.call("authorize", tool="context")
                    if (
                        scope["watermark"] == run.source_version
                        and previous.checkpoint.get("channel_values", {}).get(
                            "source_version"
                        )
                        == scope["watermark"]
                    ):
                        cp = previous.checkpoint.copy()
                        cp["id"] = str(uuid.uuid4())
                        saver.put(
                            config,
                            cp,
                            {
                                "source": "generation-recovery",
                                "step": -1,
                                "parents": {},
                            },
                            cp.get("channel_versions", {}),
                        )
            if os.getenv("HARNESS", "langgraph") == "baseline":
                bundle, recording = assemble(rt)
                result = report(bundle)
            else:
                g = graph(rt, saver)
                current = g.get_state(config)
                output = g.invoke(None if current.values else {}, config)
                result = output["report"]
                recording = output["recording"]
                if os.getenv("HARNESS") == "mistral":
                    from .contracts import ContextBundle
                    from .mistral import investigate

                    result = investigate(
                        rt, ContextBundle.model_validate(result["context"])
                    )
                if os.getenv("HARNESS") == "deepagents":
                    from .contracts import ContextBundle

                    result = deep_report(
                        rt, ContextBundle.model_validate(result["context"]), saver
                    )
            rt.event("checkpoint_saved", {"generation": run.generation})
            delay = float(os.getenv("TEST_DELAY_SECONDS", "0"))
            if delay:
                time.sleep(min(delay, 120))
            if os.getenv("ENABLE_SANDBOX", "0") == "1":
                analysis = rt.call(
                    "sandbox",
                    records=[
                        e["snippet"]
                        for e in result["evidence"]
                        if e["source"] == "logs"
                    ],
                )
                rt.event("sandbox_analysis", analysis)
            if os.getenv("ENABLE_MCP", "0") == "1":
                import asyncio
                from .gateway import mcp_analyze

                analysis = asyncio.run(
                    mcp_analyze(
                        rt,
                        [
                            e["snippet"]
                            for e in result["evidence"]
                            if e["source"] == "logs"
                        ],
                    )
                )
                rt.event("mcp_analysis", analysis)
            if os.getenv("S3_ENDPOINT"):
                from .artifacts import Artifacts

                pointer = Artifacts().put(rt, recording)
                rt.event("artifact_saved", pointer)
            if lost.is_set():
                raise RuntimeError("lease_lost")
            rt.hook(
                "run_finished", {"mode": result["mode"], "facts": len(result["facts"])}
            )
            status = report_status(result)
            rt.result(status, result, manifest(run, recording, result))
    except Exception as exc:
        reason = (
            str(exc)
            if isinstance(exc, (RuntimeError, ValueError))
            and str(exc).startswith(
                ("mistral_", "model_", "budget_", "lease_", "ungrounded_")
            )
            else "redacted"
        )
        logging.error(
            "task_failed id=%s class=%s reason=%s", run.id, type(exc).__name__, reason
        )
        try:
            rt.call("failure", kind=type(exc).__name__)
        except Exception:
            pass
    finally:
        done.set()
        thread.join(timeout=5)
        rt.client.close()


def main():
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    # One migration owner at a time; no DDL races across replicas.
    with psycopg.connect(
        os.environ["CHECKPOINT_DATABASE_URL"], autocommit=True, prepare_threshold=0
    ) as conn:
        conn.execute("select pg_advisory_lock(7100)")
        PostgresSaver(conn).setup()
        from .cache import ContextCache

        ContextCache()
        if os.getenv("S3_ENDPOINT"):
            from .artifacts import Artifacts

            Artifacts()
        conn.execute("select pg_advisory_unlock(7100)")
    owner = os.getenv("HOSTNAME", "local") + ":" + str(uuid.uuid4())
    slots = int(os.getenv("WORKER_SLOTS", "3"))
    with (
        concurrent.futures.ThreadPoolExecutor(max_workers=slots) as pool,
        httpx.Client(
            base_url=os.getenv("API_URL", "http://localhost:8080"), timeout=5
        ) as client,
    ):
        pending = set()
        while not STOP.is_set():
            Path("/tmp/worker-alive").touch()
            pending = {f for f in pending if not f.done()}
            if len(pending) < slots:
                try:
                    r = client.post(
                        "/internal/v1/claim",
                        headers={
                            "X-Worker-Key": os.getenv(
                                "INTERNAL_KEY", "local-worker-key"
                            ),
                            "X-Protocol-Version": "1",
                        },
                        json={"owner": owner},
                    )
                    if r.status_code == 200:
                        pending.add(pool.submit(process, r.json()))
                        continue
                except httpx.HTTPError:
                    pass
            STOP.wait(0.3)


if __name__ == "__main__":
    main()
