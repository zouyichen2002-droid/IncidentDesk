import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path("worker").resolve()))
from incident_worker.contracts import (
    RunContext,
    QueryPlan,
    ContextBundle,
    ToolResult,
    Evidence,
    LogQuery,
)

from incident_worker.context import ONTOLOGY, MAPPINGS
from incident_worker.context_api import app

for model in [RunContext, QueryPlan, ContextBundle, ToolResult, Evidence]:
    Path(f"contracts/{model.__name__}.schema.json").write_text(
        json.dumps(model.model_json_schema(), indent=2)
    )
paths = {}


def endpoint(path, method, summary, body=None, internal=False):
    op = {
        "summary": summary,
        "security": [{"WorkerKey": []}] if internal else [{"BearerAuth": []}],
        "responses": {
            str(s): {"description": d}
            for s, d in [
                (200, "Success"),
                (202, "Durably accepted"),
                (400, "Invalid input"),
                (401, "Authentication required"),
                (403, "Scope or role forbidden"),
                (409, "Version, lease or idempotency conflict"),
                (429, "Quota exceeded"),
            ]
        },
    }
    if body:
        op["requestBody"] = {
            "required": True,
            "content": {"application/json": {"schema": body}},
        }
    params = []
    import re

    for p in re.findall(r"{(.*?)}", path):
        params.append(
            {"name": p, "in": "path", "required": True, "schema": {"type": "string"}}
        )
    if internal:
        params.append(
            {
                "name": "X-Protocol-Version",
                "in": "header",
                "required": True,
                "schema": {"type": "string", "enum": ["1"]},
            }
        )
    if (
        path in {"/api/v1/investigations", "/api/v1/investigations/natural", "/api/v1/queries", "/api/v1/conversations", "/api/v1/conversations/{id}/turns"}
        and method == "post"
    ):
        params.append(
            {
                "name": "Idempotency-Key",
                "in": "header",
                "required": True,
                "schema": {"type": "string", "maxLength": 128},
            }
        )
    if params:
        op["parameters"] = params
    paths.setdefault(path, {})[method] = op


def obj(props, required=None):
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": props,
        "required": required or list(props),
    }


s = {"type": "string"}
n = {"type": "integer"}
endpoint(
    "/api/v1/investigations/natural",
    "post",
    "Interpret one sentence with Mistral; 200 clarification or 202 scoped investigation",
    obj({"text": {**s, "minLength": 3, "maxLength": 4000}, "timezone": s}),
)
endpoint('/api/v1/queries', 'post', 'Conversational assistant; answer, clarification or durable query job', obj({'text': {**s, 'minLength': 1, 'maxLength': 2000}, 'history': {'type':'array','maxItems':12,'items':obj({'role':{**s,'enum':['user','assistant']},'content':{**s,'minLength':1,'maxLength':2000}},['role','content'])}, 'timezone': s, 'mode': {**s, 'enum': ['auto','warehouse','investigation']}}, ['text']))
endpoint('/api/v1/queries', 'get', 'Latest 50 owned business queries, filtered by current dataset access')
endpoint('/api/v1/queries/{id}', 'get', 'Persisted query progress, executed SQL, rows and errors')
endpoint('/api/v1/conversations', 'post', 'Idempotently create an owned persistent conversation', {"type":"object","additionalProperties":False})
endpoint('/api/v1/conversations', 'get', 'Latest 50 owned conversations filtered by current source permissions')
paths['/api/v1/conversations']['get']['parameters']=[{'name':'offset','in':'query','schema':{'type':'integer','minimum':0,'maximum':100000}}]
endpoint('/api/v1/conversations/{id}', 'get', 'Owned conversation with latest 50 turns; before sequence cursor loads earlier turns')
paths['/api/v1/conversations/{id}']['get']['parameters'].append({'name':'before','in':'query','schema':{'type':'integer','minimum':1}})
endpoint('/api/v1/conversations/{id}/turns', 'post', 'Append using server-owned history, expected revision and idempotency key; replay is safe', obj({'text':{**s,'minLength':1,'maxLength':2000},'mode':{**s,'enum':['auto','warehouse','investigation']},'timezone':s,'revision':{**n,'minimum':0}},['text','revision']))
endpoint('/api/v1/datasets', 'get', 'Enabled datasets visible to current team memberships')
endpoint("/api/v1/me", "get", "Current identity and memberships")
endpoint("/api/v1/services", "get", "Accessible services")
endpoint(
    "/api/v1/investigations",
    "post",
    "Atomically create investigation and queue job",
    obj(
        {
            "service": s,
            "symptom": {**s, "minLength": 3, "maxLength": 4000},
            "start": {**s, "format": "date-time"},
            "end": {**s, "format": "date-time"},
            "timezone": s,
            "query": LogQuery.model_json_schema(),
        },
        ["service", "symptom", "start", "end", "timezone"],
    ),
)
endpoint(
    "/api/v1/investigations",
    "get",
    "Latest 50 accessible investigations; offset query pagination",
)
endpoint(
    "/api/v1/investigations/{id}",
    "get",
    "Investigation, evidence, action and freshness",
)
endpoint(
    "/api/v1/investigations/{id}/events",
    "get",
    "JSON events or SSE; Last-Event-ID cursor, reconnect after 25 seconds",
)
endpoint(
    "/api/v1/investigations/{id}/cancel",
    "post",
    "Persist cancellation; already dispatched actions still reconcile",
)
endpoint(
    "/api/v1/investigations/{id}/resume",
    "post",
    "Resume after information/failure; revalidate scope",
    obj({"information": s}),
)
endpoint(
    "/api/v1/investigations/{id}/action",
    "put",
    "Save draft with expected version; previous approval invalidated",
    obj({"version": n, "title": s, "body": s}),
)
endpoint(
    "/api/v1/investigations/{id}/action/{decision}",
    "post",
    "approve, reject or reconcile expected action version",
    obj({"version": n}),
)
endpoint(
    "/api/v1/investigations/{id}/feedback",
    "post",
    "Keep human feedback separate from report",
    obj(
        {
            "helpful": {"type": "boolean"},
            "confirmed": {"type": "boolean"},
            "final_cause": s,
        }
    ),
)
endpoint(
    "/api/v1/investigations/{id}/replay",
    "get",
    "Currently authorized recording export; deleted/obsolete returns 410",
)
endpoint(
    "/api/v1/investigations/{id}/memory",
    "post",
    "Create unreviewed candidate",
    obj({"content": s}),
)
endpoint("/api/v1/memories", "get", "Only reviewed, current, in-scope memories")
endpoint(
    "/api/v1/memories/{id}/{decision}", "post", "confirm or revoke by team approver"
)
endpoint(
    "/api/v1/investigations/{id}/badcase",
    "post",
    "Candidate or human labelled development sample",
    obj({"category": s, "label": s}),
)
endpoint("/api/v1/admin", "get", "Configuration only; no implicit business access")
endpoint(
    "/api/v1/admin/members",
    "put",
    "Change or revoke team role",
    obj({"subject": s, "team": s, "role": s}),
)
endpoint(
    "/api/v1/admin/services/{id}/invalidate",
    "post",
    "New source version or content deletion",
    obj({"delete": {"type": "boolean"}}),
)
endpoint(
    "/internal/v1/claim",
    "post",
    "Atomic lease claim; 204 when no slot or work",
    obj({"owner": s}),
    True,
)
callback = obj(
    {
        "owner": s,
        "generation": n,
        "callback_id": s,
        "kind": s,
        "payload": {"type": "object"},
        "status": s,
        "report": {"type": "object"},
        "manifest": {"type": "object"},
        "tool": s,
        "records": {"type": "array", "items": {"type": "object"}, "maxItems": 1000},
    },
    ["owner", "generation"],
)
endpoint(
    "/internal/v1/tasks/{id}/{operation}",
    "post",
    "heartbeat, authorize, event, result, failure; all fenced by lease and original principal",
    callback,
    True,
)
endpoint("/api/v1/badcases", "get", "Current team-scoped review samples")
endpoint(
    "/api/v1/badcases/{id}/review",
    "post",
    "Approver confirms development label",
    obj({"label": s}),
)
endpoint(
    "/api/v1/admin/services/{id}",
    "put",
    "Configure service test repository",
    obj({"repo": s, "enabled": {"type": "boolean"}}),
)
endpoint(
    "/internal/v1/source-change",
    "post",
    "Trusted source notification; X-Source-Key identity",
    obj({"service": s, "delete": {"type": "boolean"}}),
)
paths["/internal/v1/source-change"]["post"]["security"] = [{"SourceKey": []}]
openapi = {
    "openapi": "3.1.0",
    "info": {"title": "IncidentDesk", "version": "1.1.0"},
    "servers": [{"url": "http://localhost:8080"}],
    "paths": paths,
    "components": {
        "securitySchemes": {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "OIDC JWT",
            },
            "SourceKey": {"type": "apiKey", "in": "header", "name": "X-Source-Key"},
            "WorkerKey": {"type": "apiKey", "in": "header", "name": "X-Worker-Key"},
        }
    },
}
paths["/internal/v1/source-change"]["post"]["parameters"] = [
    {
        "name": "X-Protocol-Version",
        "in": "header",
        "required": True,
        "schema": {"type": "string", "enum": ["1"]},
    }
]

for name, value in [
    ("ontology", ONTOLOGY),
    ("source-mappings", MAPPINGS),
    ("context-openapi", app.openapi()),
]:
    Path(f"contracts/{name}.json").write_text(json.dumps(value, indent=2))
Path("contracts/openapi.json").write_text(json.dumps(openapi, indent=2))
