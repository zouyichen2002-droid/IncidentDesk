import json
from pathlib import Path
from k8s_reliability import k, connect, create, wait

# Run after the takeover test, because both deliberately alter worker test settings.
k("set", "env", "deploy/worker", "ENABLE_SANDBOX=1", "ENABLE_MCP=1")
k("rollout", "status", "deploy/worker", "--timeout=90s")
try:
    with connect() as c:
        id = create(c)
        task = wait(c, id, timeout=90)
        events = c.get("/api/v1/investigations/" + id + "/events").json()
        kinds = {e["kind"] for e in events}
        assert (
            task["status"] in {"completed", "partial"}
            and {"sandbox_analysis", "mcp_analysis", "artifact_saved"} <= kinds
        ), (task["status"], kinds)
        out = {
            "task": id,
            "terminal": task["status"],
            "events": [
                e
                for e in events
                if e["kind"]
                in {
                    "sandbox_analysis",
                    "mcp_analysis",
                    "artifact_saved",
                    "mcp_discovery",
                }
            ],
            "pass": True,
        }
        Path("docs/evidence/gateway-integration.json").write_text(
            json.dumps(out, indent=2)
        )
        print(json.dumps(out, indent=2))
finally:
    k("set", "env", "deploy/worker", "ENABLE_SANDBOX-", "ENABLE_MCP-")
