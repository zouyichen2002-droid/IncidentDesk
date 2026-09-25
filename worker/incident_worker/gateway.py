"""Versioned skills and an actual MCP SDK client; server-provided identity only."""

import asyncio
import json
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from .context import REGISTRY

SKILLS = {
    "log-analysis": {
        "version": "1",
        "review": "approved",
        "tools": ["logs"],
        "budget": 2,
        "input": {"service": "server_scope"},
        "output": "error_counts",
    },
    "release-compare": {
        "version": "1",
        "review": "approved",
        "tools": ["deployments", "git"],
        "budget": 2,
        "input": {"service": "server_scope"},
        "output": "commit_comparison",
    },
}


def skill(runtime, name, tool, step):
    spec = SKILLS.get(name)
    if not spec or spec["review"] != "approved" or tool not in spec["tools"]:
        raise PermissionError("skill_tool_denied")
    runtime.hook("tool_before", {"skill": name, "version": spec["version"]})
    result = REGISTRY[tool].query(runtime, step)
    runtime.hook("tool_after", {"skill": name, "status": "ok"})
    return result


async def mcp_analyze(runtime, records):
    runtime.authorize("logs")
    if len(records) > 100:
        raise ValueError("mcp_input_limit")
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "incident_worker.mcp_server"], env={}
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            if names != {"analyze_logs"}:
                raise PermissionError("mcp_discovery_mismatch")
            runtime.event(
                "mcp_discovery",
                {
                    "server": "log-analysis@1",
                    "tools": sorted(names),
                    "schema": tools.tools[0].inputSchema,
                },
            )
            result = await asyncio.wait_for(
                session.call_tool("analyze_logs", {"records": records}), timeout=5
            )
            if result.isError:
                raise RuntimeError("mcp_tool_error")
            return json.loads(result.content[0].text)
