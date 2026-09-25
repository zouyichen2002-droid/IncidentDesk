"""Local identity issuer, fault-producing service, read-only sources, and labelled Issue stub."""

import asyncio
import json
import os
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import jwt
import psycopg
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
import secrets
import log_store

app = FastAPI(title="IncidentDesk development fixtures")
ROOT = Path(os.getenv("DEMO_DATA", "/data"))
ROOT.mkdir(parents=True, exist_ok=True)
ISSUER = os.getenv("OIDC_ISSUER", "http://localhost:8090")
KEYFILE = ROOT / "issuer.pem"
if not KEYFILE.exists():
    KEYFILE.write_bytes(
        rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
KEY = serialization.load_pem_private_key(KEYFILE.read_bytes(), password=None)
JWK = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key()))
JWK.update(kid="local-1", use="sig", alg="RS256")
DB = ROOT / "demo.sqlite"
with sqlite3.connect(DB) as c:
    c.executescript(
        "CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY,event_time TEXT,service TEXT,payload TEXT); CREATE TABLE IF NOT EXISTS issues(number INTEGER PRIMARY KEY,repo TEXT,title TEXT,body TEXT); CREATE TABLE IF NOT EXISTS config(key TEXT PRIMARY KEY,value TEXT);"
    )
GIT = ROOT / "repo"
GIT.mkdir(exist_ok=True)


def git(*args):
    return subprocess.check_output(["git", "-C", str(GIT), *args], text=True).strip()


if not (GIT / ".git").exists():
    git("init", "-b", "main")
    git("config", "user.email", "demo@incidentdesk.invalid")
    git("config", "user.name", "IncidentDesk Demo")
    (GIT / "config.json").write_text('{"pool_size":10,"timeout_ms":500}')
    git("add", ".")
    git("commit", "-m", "demo: healthy baseline")
    (GIT / "config.json").write_text('{"pool_size":1,"timeout_ms":50}')
    git("add", ".")
    git("commit", "-m", "demo: reduce pool and dependency timeout")
SHA = git("log", "-1", "--format=%H", "--", "config.json")
RUNBOOK = "# Demo order service\nInvestigate pool utilization, dependency latency and recent deployments. A temporal correlation is not proof of causation. Confirm config against the deployed commit before proposing a fix.\n"
RUNBOOK_PATH = GIT / "RUNBOOK.md"
if not RUNBOOK_PATH.exists():
    RUNBOOK_PATH.write_text(RUNBOOK)
    git("add", ".")
    git("commit", "-m", "docs: add versioned demo runbook")


def now():
    return datetime.now(timezone.utc).isoformat()


def config(key, default=""):
    with sqlite3.connect(DB) as c:
        row = c.execute("select value from config where key=?", (key,)).fetchone()
    return row[0] if row else default


@app.get("/healthz")
def health():
    if config("fault") == "probe_failure":
        raise HTTPException(503, "injected_probe_failure")
    return {"status": "ok", "mode": "development-fixtures", "commit": SHA}


@app.get("/.well-known/openid-configuration")
def discovery():
    return {
        "issuer": ISSUER,
        "jwks_uri": ISSUER + "/jwks",
        "authorization_endpoint": ISSUER + "/authorize",
        "token_endpoint": ISSUER + "/token",
        "response_types_supported": ["id_token"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
    }


@app.get("/jwks")
def jwks():
    return {"keys": [JWK]}


@app.post("/token")
async def token(r: Request):
    b = await r.json()
    if b.get("username") not in {"alice", "bob", "carol", "admin"} or b.get(
        "password"
    ) != os.getenv("DEMO_PASSWORD", "demo-password"):
        raise HTTPException(401, "invalid_credentials")
    return {
        "access_token": jwt.encode(
            {
                "iss": ISSUER,
                "aud": "incidentdesk",
                "sub": b["username"],
                "iat": int(time.time()),
                "exp": int(time.time()) + 3600,
            },
            KEY,
            algorithm="RS256",
            headers={"kid": "local-1"},
        ),
        "token_type": "Bearer",
        "expires_in": 3600,
        "identity_mode": "local-development",
    }


@app.post("/control")
async def control(r: Request):
    if r.headers.get("X-Demo-Key") != os.getenv("DEMO_KEY", "local-demo-key"):
        raise HTTPException(403)
    b = await r.json()
    with sqlite3.connect(DB) as c:
        for k, v in b.items():
            c.execute("insert or replace into config values(?,?)", (k, str(v)))
    if "release" in b and os.getenv("SEED_DATABASE_URL"):
        with psycopg.connect(os.environ["SEED_DATABASE_URL"]) as connection:
            connection.execute("lock table sources.deployments in exclusive mode")
            connection.execute(
                "insert into sources.deployments(id,service,app_id,version,commit_sha,event_time,watermark) select %s,'svc-17','svc-17',%s,%s,now(),coalesce(max(watermark),0)+1 from sources.deployments",
                ("dep-" + str(time.time_ns()), str(b["release"]), SHA),
            )
    if any(k in b for k in ("delete_runbook", "release", "runbook")):
        if "runbook" in b:
            RUNBOOK_PATH.write_text(str(b["runbook"]))
            git("add", ".")
            git("commit", "-m", "demo: update source runbook")
        async with httpx.AsyncClient(timeout=5) as client:
            result = await client.post(
                os.getenv("API_URL", "http://api:8080") + "/internal/v1/source-change",
                headers={
                    "X-Source-Key": os.getenv("SOURCE_NOTIFY_KEY", "local-source-key"),
                    "X-Protocol-Version": "1",
                },
                json={"service": "svc-17", "delete": b.get("delete_runbook") == "true"},
            )
            result.raise_for_status()
    return {"configured": list(b)}


POOL = asyncio.Semaphore(1)
POOL_BLOCKED = False


@app.get("/dependency")
async def dependency():
    await asyncio.sleep(0.2)
    return {"status": "ok"}


@app.get("/business")
async def business(service: str = "svc-17"):
    global POOL_BLOCKED
    if service not in {"svc-17", "svc-23"}:
        raise HTTPException(400)
    fault = config("fault", "healthy")
    start = time.perf_counter()
    message = "request completed"
    status = 200
    error_class = None
    if fault != "pool_exhaustion" and POOL_BLOCKED:
        POOL.release()
        POOL_BLOCKED = False
    try:
        if fault == "pool_exhaustion" and not POOL_BLOCKED:
            await POOL.acquire()
            POOL_BLOCKED = True
        if fault == "bad_config":
            int("invalid-pool-size")
        try:
            await asyncio.wait_for(POOL.acquire(), timeout=0.05)
        except TimeoutError:
            message = "database pool exhausted: active=1 max=1"
            raise
        try:
            with sqlite3.connect(DB) as c:
                c.execute("select 1").fetchone()
        finally:
            POOL.release()
        if fault in {"dependency_timeout", "release_error"}:
            async with httpx.AsyncClient(timeout=0.05) as client:
                await client.get("http://127.0.0.1:8090/dependency")
    except TimeoutError:
        status = 503
        error_class = "PoolAcquireTimeout"
    except httpx.TimeoutException:
        status = 503
        error_class = "DependencyReadTimeout"
        message = "upstream inventory timed out after 50ms" + (
            " after release" if fault == "release_error" else ""
        )
    except ValueError:
        status = 503
        error_class = "InvalidConfiguration"
        message = "invalid DB_POOL_SIZE configuration"
    payload = {
        "service_name": "checkout-api" if service == "svc-17" else "payment-api",
        "level": "INFO" if status == 200 else "ERROR",
        "message": message,
        "error_class": error_class,
        "duration_ms": round((time.perf_counter() - start) * 1000, 2),
        "release": config("release", "v2"),
        "commit": SHA,
    }
    if fault != "missing_logs":
        with sqlite3.connect(DB) as c:
            c.execute(
                "insert into logs(event_time,service,payload) values(?,?,?)",
                (now(), service, json.dumps(payload)),
            )
    return JSONResponse(payload, status_code=status)


def related_records(source, scope):
    # Fixtures belong to orders and must never be attached to public datasets.
    if scope["service"] != "svc-17":
        return []
    profile = log_store.catalog(DB, [scope["service"]])[0]
    if profile["provenance"] == "public-dataset":
        return []
    if source == "runbook":
        if config("delete_runbook") == "true":
            return []
        versions = git(
            "log", "-1", "--until=" + scope["end"], "--format=%H", "--", "RUNBOOK.md"
        )
        if not versions:
            return []
        return [
            {
                "id": "orders-runbook",
                "event_time": git("show", "-s", "--format=%cI", versions),
                "content": {
                    "markdown": git("show", versions + ":RUNBOOK.md"),
                    "service": "svc-17",
                    "provenance": "local-demo",
                    "valid_as_of": scope["end"],
                },
                "locator": "demo-git://repo/" + versions + "/RUNBOOK.md",
                "version": versions,
                "deleted": False,
            }
        ]
    url = os.getenv("SEED_DATABASE_URL")
    if not url:
        return []
    with psycopg.connect(url) as c:
        shas = c.execute(
            "select distinct commit_sha from sources.deployments where service=%s and not deleted and event_time<=%s and (event_time>=%s or id=(select id from sources.deployments where service=%s and not deleted and event_time<=%s order by event_time desc,watermark desc limit 1)) limit 50",
            (
                scope["service"],
                scope["end"],
                scope["start"],
                scope["service"],
                scope["start"],
            ),
        ).fetchall()
    result = []
    import re

    for (sha,) in shas:
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            continue
        try:
            stamp = git("show", "-s", "--format=%cI", sha)
            if datetime.fromisoformat(stamp) > datetime.fromisoformat(scope["end"]):
                continue
            result.append(
                {
                    "id": sha,
                    "event_time": stamp,
                    "content": {
                        "commit": sha,
                        "diff": git("show", "--stat", "--format=fuller", sha),
                        "config": git("show", sha + ":config.json"),
                        "config_path": "config.json",
                        "config_locator": "demo-git://repo/" + sha + "/config.json",
                        "service": scope["service"],
                        "provenance": "local-demo",
                    },
                    "locator": "demo-git://repo/commit/" + sha,
                    "version": sha,
                    "deleted": False,
                }
            )
        except subprocess.CalledProcessError:
            continue
    return result


@app.post("/catalog")
async def source_catalog(r: Request):
    if not secrets.compare_digest(
        r.headers.get("X-Worker-Key", ""), os.getenv("INTERNAL_KEY", "local-worker-key")
    ):
        raise HTTPException(401, "service_identity_required")
    b = await r.json()
    services = b.get("services", [])
    if (
        not isinstance(services, list)
        or len(services) > 100
        or any(not isinstance(s, str) for s in services)
    ):
        raise HTTPException(400, "invalid_services")
    return await run_in_threadpool(log_store.catalog, DB, services)


@app.post("/sources/{source}")
async def sources(source: str, r: Request):
    b = await r.json()
    task = b["task"]
    if source not in {"logs", "git", "runbook", "cluster"}:
        raise HTTPException(404)
    async with httpx.AsyncClient(timeout=5) as client:
        auth = await client.post(
            os.getenv("API_URL", "http://api:8080")
            + f"/internal/v1/tasks/{task['id']}/authorize",
            headers={
                "X-Worker-Key": r.headers.get("X-Worker-Key", ""),
                "X-Protocol-Version": "1",
            },
            json={
                "owner": task["owner"],
                "generation": task["generation"],
                "tool": source,
            },
        )
    if auth.status_code != 200:
        raise HTTPException(auth.status_code, "scope_rejected")
    scope = auth.json()
    cursor = b.get("cursor")
    limit = min(100, int(b.get("limit", 50)))
    if limit < 1:
        raise HTTPException(400)
    if config("unavailable") == source:
        raise HTTPException(503, "source_unavailable")
    records = []
    extra = {}
    if source == "logs":
        try:
            data = await run_in_threadpool(
                log_store.query, DB, scope, scope.get("query", {}), limit, cursor
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        records = data.pop("records")
        return {
            **data,
            "records": records,
            "watermark": scope["watermark"],
            "observed_at": now(),
            "scope": scope,
            "sync": "indexed-keyset-v2",
        }
    elif source in {"git", "runbook"}:
        records = await run_in_threadpool(related_records, source, scope)
        extra["provenance"] = "local-demo"
    elif source == "cluster":
        ns = os.getenv("OBSERVE_NAMESPACE", "")
        if not ns:
            raise HTTPException(503, "cluster_observer_not_configured")
        if scope["service"] != "svc-17":
            raise HTTPException(403, "namespace_outside_service_scope")
        sa = Path("/var/run/secrets/kubernetes.io/serviceaccount")
        async with httpx.AsyncClient(verify=str(sa / "ca.crt"), timeout=5) as client:
            for resource in ("pods", "events"):
                response = await client.get(
                    f"https://kubernetes.default.svc/api/v1/namespaces/{ns}/{resource}",
                    headers={"Authorization": "Bearer " + (sa / "token").read_text()},
                )
                response.raise_for_status()
                for item in response.json()["items"]:
                    records.append(
                        {
                            "id": item["metadata"]["uid"],
                            "event_time": item["metadata"]["creationTimestamp"],
                            "content": {
                                "name": item["metadata"]["name"],
                                "release": item["metadata"]
                                .get("labels", {})
                                .get("release"),
                                **{
                                    k: v
                                    for k, v in item.items()
                                    if k
                                    in ("status", "reason", "message", "involvedObject")
                                },
                            },
                            "locator": f"k8s://{ns}/{resource}/{item['metadata']['name']}",
                            "version": item["metadata"]["resourceVersion"],
                            "deleted": False,
                        }
                    )
    return {
        **extra,
        "records": records[:limit],
        "next_cursor": records[limit - 1]["id"] if len(records) > limit else None,
        "watermark": scope["watermark"],
        "observed_at": now(),
        "scope": scope,
        "sync": "rescan" if source != "logs" else "monotonic_id",
    }


@app.post("/github/repos/{owner}/{repo}/issues")
async def create_issue(owner: str, repo: str, r: Request):
    b = await r.json()
    with sqlite3.connect(DB) as c:
        cur = c.execute(
            "insert into issues(repo,title,body) values(?,?,?)",
            (owner + "/" + repo, b["title"], b["body"]),
        )
        n = cur.lastrowid
    if config("drop_issue_response") == "true":
        await asyncio.sleep(12)
    return issue(owner, repo, n)


@app.get("/github/repos/{owner}/{repo}/issues/{number}")
def issue(owner: str, repo: str, number: int):
    with sqlite3.connect(DB) as c:
        row = c.execute(
            "select title,body from issues where number=? and repo=?",
            (number, owner + "/" + repo),
        ).fetchone()
    if not row:
        raise HTTPException(404)
    return {
        "number": number,
        "title": row[0],
        "body": row[1],
        "html_url": f"http://localhost:8090/github/repos/{owner}/{repo}/issues/{number}",
        "integration": "local-github-stub",
    }


@app.get("/github/repos/{owner}/{repo}/issues")
def issues(
    owner: str, repo: str, page: int = 1, per_page: int = 100, state: str = "all"
):
    if config("hide_issues") == "true":
        return []
    with sqlite3.connect(DB) as c:
        rows = c.execute(
            "select number from issues where repo=? order by number desc limit ? offset ?",
            (owner + "/" + repo, per_page, (page - 1) * per_page),
        ).fetchall()
    return [issue(owner, repo, n[0]) for n in rows]


@app.on_event("startup")
def seed():
    log_store.initialize(DB)
    url = os.getenv("SEED_DATABASE_URL")
    if url:
        with psycopg.connect(url) as c:
            for s in ("svc-17", "svc-23"):
                c.execute(
                    "insert into sources.deployments values(%s,%s,%s,'v2',%s,now(),1,false) on conflict do nothing",
                    ("dep-" + s, s, s, SHA),
                )
