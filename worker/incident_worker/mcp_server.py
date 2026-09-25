from collections import Counter
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("IncidentDesk log analysis v1")


@mcp.tool()
def analyze_logs(records: list[dict]) -> dict:
    """Count levels in caller-authorized snapshots. No filesystem, network or write tools."""
    if len(records) > 100:
        raise ValueError("record_limit")
    return {
        "version": "1",
        "count": len(records),
        "levels": dict(Counter(str(r.get("level", "UNKNOWN")) for r in records)),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
