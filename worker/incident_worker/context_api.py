from datetime import datetime
import os
import secrets
import httpx
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from .contracts import RunContext, QueryPlan
from .runtime import Runtime
from .context import assemble
from .natural import NaturalRequest

app = FastAPI(title="IncidentDesk Context API", version="1")


class Query(BaseModel):
    run: RunContext
    plan: QueryPlan | None = None


@app.get("/healthz")
def health():
    return {"ok": True}


@app.post("/context/v1/query")
def query(b: Query, x_worker_key: str = Header(default="")):
    if not secrets.compare_digest(
        x_worker_key, os.getenv("INTERNAL_KEY", "local-worker-key")
    ):
        raise HTTPException(401, "service_identity_required")
    rt = Runtime(b.run)
    try:
        # Identity/team/time from Go, never from caller-supplied RunContext.
        scope = rt.authorize("context")
        for k in ("subject", "team", "service"):
            if scope[k] != getattr(b.run, k):
                raise PermissionError("scope_mismatch")
        if b.run.start != datetime.fromisoformat(
            scope["start"]
        ) or b.run.end != datetime.fromisoformat(scope["end"]):
            raise PermissionError("time_scope_mismatch")
        bundle, _ = assemble(rt, b.plan)
        return bundle.model_dump(mode="json")
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            e.response.status_code
            if e.response.status_code in {401, 403, 409}
            else 502,
            "scope_authorization_failed",
        )
    except PermissionError as e:
        raise HTTPException(403, str(e))
    finally:
        rt.client.close()


@app.post("/context/v1/interpret")
def natural_query(b: NaturalRequest, x_worker_key: str = Header(default="")):
    if not secrets.compare_digest(
        x_worker_key, os.getenv("INTERNAL_KEY", "local-worker-key")
    ):
        raise HTTPException(401, "service_identity_required")
    from .natural import interpret

    try:
        return interpret(b)
    except ValueError:
        raise HTTPException(400, "invalid_interpretation")
    except Exception:
        raise HTTPException(502, "mistral_unavailable")
