import json
import subprocess
from pathlib import Path
import httpx

results = []
for name, override in [
    ("expired", {"exp": 1}),
    ("wrong_audience", {"aud": "other"}),
    ("wrong_issuer", {"iss": "https://wrong.invalid"}),
]:
    code = (
        "import jwt,time;from pathlib import Path;claims={'iss':'http://demo:8090','aud':'incidentdesk','sub':'alice','iat':int(time.time()),'exp':int(time.time())+60};claims.update("
        + repr(override)
        + ");print(jwt.encode(claims,Path('/data/issuer.pem').read_bytes(),algorithm='RS256',headers={'kid':'local-1'}))"
    )
    token = subprocess.run(
        ["docker", "compose", "exec", "-T", "demo", "python", "-c", code],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    r = httpx.get(
        "http://localhost:8080/api/v1/me", headers={"Authorization": "Bearer " + token}
    )
    assert r.status_code == 401
    results.append({"test": name, "status": r.status_code, "pass": True})
Path("docs/evidence/oidc.json").write_text(json.dumps(results, indent=2))
print(json.dumps(results, indent=2))
