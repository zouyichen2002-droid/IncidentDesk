from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Budget(Strict):
    steps: int = Field(ge=1, le=32)
    seconds: int = Field(ge=1, le=300)
    output_bytes: int = Field(ge=100, le=1048576)
    model_calls: int = Field(ge=0, le=5)
    tokens: int = Field(ge=1, le=32000)


class LogQuery(Strict):
    mode: Literal["anomalies", "search", "all"] = "anomalies"
    terms: list[str] = Field(default_factory=list, max_length=6)
    levels: list[
        Literal[
            "ERROR",
            "FATAL",
            "SEVERE",
            "FAILURE",
            "WARN",
            "WARNING",
            "CRITICAL",
            "ALERT",
            "EMERG",
            "INFO",
            "DEBUG",
            "TRACE",
            "UNKNOWN",
        ]
    ] = Field(default_factory=list, max_length=12)


class RunContext(Strict):
    model_config = ConfigDict(extra="ignore")
    protocol_version: Literal[1]
    id: str
    subject: str
    team: str
    service: str
    symptom: str
    start: datetime
    end: datetime
    source_version: int
    generation: int
    attempt: int = 1
    owner: str
    lease_seconds: int
    query: LogQuery = Field(default_factory=LogQuery)
    budget: Budget


class PlanStep(Strict):
    source: Literal["logs", "deployments", "git", "runbook", "cluster"]
    object: Literal["Service", "Deployment", "Commit", "Runbook", "Incident"]
    path: list[str]
    limit: int = Field(default=50, ge=1, le=100)


class QueryPlan(Strict):
    version: Literal["1"] = "1"
    service: str
    start: datetime
    end: datetime
    steps: list[PlanStep] = Field(max_length=12)


class Evidence(Strict):
    id: str
    source: str
    locator: str
    collected_at: str
    event_time: str
    version: str
    sha256: str
    snippet: Any
    team: str
    source_record: str
    available: bool = True


class ToolResult(Strict):
    tool: str
    status: Literal["ok", "error", "denied", "truncated"]
    records: list[dict] = []
    next_cursor: str | None = None
    watermark: str
    observed_at: str
    error: str | None = None


class ContextBundle(Strict):
    version: Literal["1"] = "1"
    scope: dict
    objects: list[dict]
    facts: list[dict]
    evidence: list[Evidence]
    missing: list[str]
    conflicts: list[dict]
    freshness: list[dict]
    plan: QueryPlan
    token_budget: int
    memories: list[dict] = []
    retrieval: dict = Field(default_factory=dict)
    mapping_version: str = "2"
    ontology_version: str = "1"
