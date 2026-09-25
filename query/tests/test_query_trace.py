import asyncio
import json
import os
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("LLM_API_KEY", "test-key-never-used")
from fastapi.testclient import TestClient
from main import app
from app.api.dependencies import get_query_service
from app.core.context import request_id_ctx_var
from app.services.query_service import QueryService


def service():
    return QueryService(None, None, None, None, None, None)


async def fake_stream(**kwargs):
    yield {"type": "progress", "step": "测试", "status": "running"}
    await asyncio.sleep(0)
    yield {"type": "progress", "step": "测试", "status": "success"}
    if kwargs["input"]["query"] == "fail":
        raise ValueError("test failure")
    yield {"type": "result", "data": [{"orders": 115}], "sql": "SELECT COUNT(*) FROM fact_order"}


class QueryTraceTests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_streams_and_errors_retain_their_own_identity(self):
        async def run(question, request_id):
            token = request_id_ctx_var.set(request_id)
            try:
                return [json.loads(line[6:]) async for line in service().query(question)]
            finally:
                request_id_ctx_var.reset(token)

        with patch("app.services.query_service.graph", SimpleNamespace(astream=fake_stream)):
            first, second = await asyncio.gather(run("ok", "a"), run("fail", "b"))
        for events, request_id in ((first, "a"), (second, "b")):
            self.assertTrue(all(e["request_id"] == request_id for e in events))
            self.assertGreaterEqual(events[1]["duration_ms"], 0)
            self.assertEqual([e["elapsed_ms"] for e in events], sorted(e["elapsed_ms"] for e in events))
        self.assertEqual(first[-1]["type"], "result")
        self.assertEqual(second[-1]["type"], "error")

    def test_authenticated_uuid_survives_middleware_and_stream(self):
        app.dependency_overrides[get_query_service] = service
        before = request_id_ctx_var.get()
        try:
            with patch.dict(os.environ, INTERNAL_KEY="test-internal"), patch("app.services.query_service.graph", SimpleNamespace(astream=fake_stream)):
                client = TestClient(app)
                for given in (str(uuid.uuid4()), "bad-id"):
                    r = client.post("/api/query", headers={"X-Worker-Key": "test-internal", "X-Request-ID": given}, json={"query": "test"})
                    self.assertEqual(r.status_code, 200)
                    actual = r.headers["X-Request-ID"]
                    uuid.UUID(actual)
                    self.assertEqual(actual == given, given != "bad-id")
                    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
                    self.assertTrue(all(e["request_id"] == actual for e in events))
            self.assertEqual(request_id_ctx_var.get(), before)
        finally:
            app.dependency_overrides.pop(get_query_service, None)
