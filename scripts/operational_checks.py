import json
from pathlib import Path
import httpx
from smoke import login

out = {}
with httpx.Client(
    base_url="http://localhost:8080", headers=login("alice"), timeout=10
) as c:
    task = c.get("/api/v1/investigations").json()[0]
    id = task["id"]
    with c.stream(
        "GET",
        f"/api/v1/investigations/{id}/events",
        headers={"Accept": "text/event-stream", "Last-Event-ID": "9999999"},
    ) as r:
        r.raise_for_status()
        lines = []
        for line in r.iter_lines():
            lines.append(line)
            if line.startswith("data:"):
                break
        assert any("event: snapshot" == x for x in lines)
        out["expired_cursor_snapshot"] = lines
    r = c.get(
        f"/api/v1/investigations/{id}/events", headers={"Last-Event-ID": "invalid"}
    )
    assert r.status_code == 400
    out["invalid_cursor_status"] = r.status_code
metrics = httpx.get("http://localhost:8080/metrics").text
for metric in [
    "incident_active_jobs",
    "incident_queue_depth",
    "incident_http_requests_total",
]:
    assert metric in metrics, metric
prom = httpx.get("http://localhost:9090/api/v1/targets").json()
assert any(x["health"] == "up" for x in prom["data"]["activeTargets"])
out["prometheus_up"] = True
r = httpx.get(
    "http://localhost:3000/api/dashboards/uid/incidentdesk",
    auth=("admin", "local-grafana"),
)
r.raise_for_status()
d = r.json()
out["grafana_dashboard"] = {
    "title": d["dashboard"]["title"],
    "panels": len(d["dashboard"]["panels"]),
}
assert out["grafana_dashboard"]["panels"] > 0
out["pass"] = True
Path("docs/evidence/operational-checks.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
