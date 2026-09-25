import os
import unittest

os.environ.setdefault("LLM_API_KEY", "test-key-never-used")
from fastapi.testclient import TestClient

from main import app


class ServiceIdentityTests(unittest.TestCase):
    def test_direct_requests_require_internal_identity(self):
        old = os.environ.get("INTERNAL_KEY")
        os.environ["INTERNAL_KEY"] = "test-internal"
        try:
            client = TestClient(app)
            self.assertEqual(client.get("/healthz").status_code, 200)
            self.assertEqual(
                client.post("/api/query", json={"query": "sales"}).status_code, 401
            )
            self.assertEqual(
                client.post("/api/route", json={"text": "sales"}).status_code, 401
            )
            self.assertEqual(
                client.post(
                    "/api/query",
                    headers={"X-Worker-Key": "wrong"},
                    json={"query": "sales"},
                ).status_code,
                401,
            )
        finally:
            if old is None:
                os.environ.pop("INTERNAL_KEY", None)
            else:
                os.environ["INTERNAL_KEY"] = old
