import json
import os
from pathlib import Path
import httpx

url = os.getenv("TEST_SOURCE", "http://localhost:18090")
results = []
for fault, code in [
    ("healthy", 200),
    ("pool_exhaustion", 503),
    ("dependency_timeout", 503),
    ("bad_config", 503),
    ("release_error", 503),
    ("missing_logs", 200),
]:
    httpx.post(
        url + "/control",
        headers={"X-Demo-Key": "local-demo-key"},
        json={"fault": fault},
    ).raise_for_status()
    r = httpx.get(url + "/business")
    assert r.status_code == code
    data = r.json()
    results.append(
        {"fault": fault, "http_status": r.status_code, "observed": data, "pass": True}
    )
httpx.post(
    url + "/control",
    headers={"X-Demo-Key": "local-demo-key"},
    json={"fault": "pool_exhaustion"},
)
Path("docs/evidence/demo-faults.json").write_text(json.dumps(results, indent=2))
print(json.dumps(results, indent=2))
