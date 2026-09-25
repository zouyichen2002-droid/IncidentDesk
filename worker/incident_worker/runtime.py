"""Application SDK. No framework types or action write credentials cross this interface."""

import os
import time
import uuid
import httpx
from .contracts import RunContext


class Runtime:
    def __init__(self, run: RunContext, client=None):
        self.run = run
        self.started = time.monotonic()
        self.calls = 0
        self.client = client or httpx.Client(
            base_url=os.getenv("API_URL", "http://localhost:8080"), timeout=8
        )
        self.headers = {
            "X-Worker-Key": os.getenv("INTERNAL_KEY", "local-worker-key"),
            "X-Protocol-Version": "1",
        }

    def call(self, operation, **payload):
        b = {"owner": self.run.owner, "generation": self.run.generation, **payload}
        r = self.client.post(
            f"/internal/v1/tasks/{self.run.id}/{operation}",
            headers=self.headers,
            json=b,
        )
        r.raise_for_status()
        return r.json()

    def authorize(self, tool):
        if (
            self.calls >= self.run.budget.steps
            or time.monotonic() - self.started > self.run.budget.seconds
        ):
            raise RuntimeError("budget_exhausted")
        self.calls += 1
        scope = self.call("authorize", tool=tool)
        return scope

    def event(self, kind, payload):
        return self.call("event", kind=kind, payload=payload)

    def result(self, status, report, manifest):
        body = {
            "status": status,
            "report": report,
            "manifest": manifest,
            "callback_id": str(uuid.uuid4()),
        }
        for attempt in range(3):
            try:
                return self.call("result", **body)
            except httpx.TransportError:
                if attempt == 2:
                    raise
                time.sleep(0.2 * (attempt + 1))

    def hook(self, name, data, policy=True):
        if name not in {
            "plan_validated",
            "retrieval_returned",
            "context_assembled",
            "tool_before",
            "tool_after",
            "run_finished",
        }:
            raise ValueError("unknown_hook")
        if not policy:
            raise PermissionError("policy_hook_denied")
        self.event("hook", {"name": name, "status": "pass", "summary": data})
