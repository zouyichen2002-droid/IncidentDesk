"""Finite ontology/query validator and framework-independent evidence assembly."""

import hashlib
import json
import os
import time
from .contracts import ContextBundle, Evidence, PlanStep, QueryPlan
from .connectors import REGISTRY
from .redaction import redact

ONTOLOGY = {
    "Service": {
        "team": "Team",
        "deployments": "Deployment",
        "runbook": "Runbook",
        "incidents": "Incident",
    },
    "Deployment": {"commit": "Commit"},
    "Commit": {},
    "Runbook": {},
    "Incident": {"service": "Service"},
    "Team": {},
}
MAPPINGS = {
    "logs": {
        "checkout-api": ["svc-17"],
        "payment-api": ["svc-23"],
        "ambiguous": ["svc-17", "svc-23"],
    },
    "deployments": {"svc-17": ["svc-17"], "svc-23": ["svc-23"]},
}


def resolve(source, alias):
    ids = MAPPINGS.get(source, {}).get(alias, [])
    if len(ids) != 1:
        raise ValueError("ambiguous_or_unmapped_service")
    return ids[0]


def default_plan(run):
    steps = [
        PlanStep(
            source="deployments", object="Deployment", path=["Service", "deployments"]
        ),
        PlanStep(source="logs", object="Service", path=["Service"], limit=20),
        PlanStep(
            source="git", object="Commit", path=["Service", "deployments", "commit"]
        ),
        PlanStep(source="runbook", object="Runbook", path=["Service", "runbook"]),
    ]
    if os.getenv("OBSERVE_NAMESPACE"):
        steps.append(
            PlanStep(source="cluster", object="Incident", path=["Service", "incidents"])
        )
    return QueryPlan(service=run.service, start=run.start, end=run.end, steps=steps)


def validate_plan(plan, run):
    if (
        plan.service != run.service
        or plan.start < run.start
        or plan.end > run.end
        or plan.end < plan.start
    ):
        raise PermissionError("plan_scope")
    if len(plan.steps) > run.budget.steps:
        raise ValueError("plan_budget")
    for s in plan.steps:
        if not s.path or s.path[0] != "Service":
            raise ValueError("invalid_root")
        obj = s.path[0]
        for relation in s.path[1:]:
            if relation not in ONTOLOGY[obj]:
                raise ValueError("invalid_relation")
            obj = ONTOLOGY[obj][relation]
        if obj != s.object:
            raise ValueError("object_type_mismatch")
        expected = {
            "logs": "Service",
            "deployments": "Deployment",
            "git": "Commit",
            "runbook": "Runbook",
            "cluster": "Incident",
        }
        if s.object != expected[s.source]:
            raise ValueError("source_object_mismatch")
    return plan


def assemble(runtime, plan=None, recorded=None):
    plan = validate_plan(plan or default_plan(runtime.run), runtime.run)
    runtime.hook("plan_validated", {"steps": len(plan.steps)})
    facts = []
    evidence = []
    missing = []
    freshness = []
    conflicts = []
    records = {}
    versions = {}
    retrieval = {}
    for step in plan.steps:
        start = time.perf_counter()
        runtime.hook("tool_before", {"source": step.source})
        try:
            if recorded is not None:
                if step.source not in recorded:
                    raise RuntimeError("unreplayable_missing_recording:" + step.source)
                runtime.authorize(step.source)
                out = recorded[step.source]
            else:
                out = REGISTRY[step.source].query(runtime, step)
                if step.source == "logs":
                    pages = 1
                    while out.get("next_cursor") and pages < 3:
                        more = REGISTRY[step.source].query(
                            runtime, step, out["next_cursor"]
                        )
                        known = {r["id"] for r in out["records"]}
                        out["records"].extend(
                            r for r in more["records"] if r["id"] not in known
                        )
                        out["next_cursor"] = more.get("next_cursor")
                        pages += 1
                    retrieval = {
                        **out.get("summary", {}),
                        "pages": pages,
                        "evidence_count": len(out["records"]),
                        "sampled": bool(out.get("next_cursor")),
                        "provenance": out.get("provenance", "unknown"),
                    }
                    out["retrieval"] = retrieval
            out = redact(out)
            if step.source == "logs":
                retrieval = out.get("retrieval", retrieval)
            records[step.source] = out
            runtime.hook(
                "retrieval_returned",
                {"source": step.source, "count": len(out["records"])},
            )
            freshness.append(
                {
                    "source": step.source,
                    "observed_at": out["observed_at"],
                    "watermark": str(out["watermark"]),
                    "snapshot_consistency": "independent_source",
                }
            )
            if out.get("next_cursor"):
                missing.append(
                    step.source
                    + ": truncated; 已按查询条件检索并分层取样；证据预算内分页结束，仍有更多记录（truncated）"
                )
            available = [r for r in out["records"] if not r.get("deleted")]
            if not available:
                missing.append(step.source + ": no accessible records in scope")
            for row in available:
                content = row["content"]
                if step.source in MAPPINGS:
                    alias = (
                        content.get("service_name")
                        if step.source == "logs"
                        else content.get("app_id")
                    )
                    if resolve(step.source, alias) != runtime.run.service:
                        raise PermissionError("source_scope_mismatch")
                raw = json.dumps(content, sort_keys=True, ensure_ascii=False)
                digest = hashlib.sha256(raw.encode()).hexdigest()
                eid = f"{step.source}:{row['id']}:{digest[:12]}"
                if len(raw) > 12000:
                    raw = raw[:12000]
                    missing.append(step.source + ": evidence snippet truncated")
                ev = Evidence(
                    id=eid,
                    source=step.source,
                    locator=row["locator"],
                    collected_at=out["observed_at"],
                    event_time=row["event_time"],
                    version=row["version"],
                    sha256=digest,
                    snippet=content if len(json.dumps(content)) <= 12000 else raw,
                    team=runtime.run.team,
                    source_record=row["id"],
                )
                evidence.append(ev)
                fact = {
                    "id": "fact:" + eid,
                    "kind": "observation",
                    "text": describe(step.source, content),
                    "evidence": [eid],
                    "transform": "normalize-v1",
                    "query_step": step.model_dump(),
                }
                facts.append(fact)
                if step.source == "logs" and content.get("release"):
                    versions.setdefault("logs", set()).add(content["release"])
                if step.source == "deployments":
                    versions.setdefault("deployments", set()).add(content["version"])
            runtime.hook(
                "tool_after",
                {
                    "source": step.source,
                    "status": "ok",
                    "milliseconds": round((time.perf_counter() - start) * 1000, 2),
                },
            )
        except (PermissionError,):
            raise
        except Exception as exc:
            if recorded is not None:
                raise
            # Revocation/lease loss is fatal, not an apparently successful degraded query.
            import httpx

            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {
                401,
                403,
                409,
            }:
                raise
            missing.append(step.source + ": " + type(exc).__name__)
            runtime.hook(
                "tool_after",
                {
                    "source": step.source,
                    "status": "error",
                    "error_class": type(exc).__name__,
                },
            )
    if (
        versions.get("logs")
        and versions.get("deployments")
        and versions["logs"] != versions["deployments"]
    ):
        conflicts.append(
            {
                "text": "日志与发布表的版本记录不一致；需要核对实例与发布时间。",
                "evidence": [
                    e.id for e in evidence if e.source in {"logs", "deployments"}
                ],
            }
        )
    objects = [{"type": "Service", "id": runtime.run.service, "team": runtime.run.team}]
    releases = [e for e in evidence if e.source == "deployments"]
    commits = [e for e in evidence if e.source == "git"]
    for release in releases:
        objects.append(
            {
                "type": "Deployment",
                "id": release.source_record,
                "service": runtime.run.service,
                "evidence": [release.id],
                "valid_time": release.event_time,
            }
        )
        matched = [
            commit
            for commit in commits
            if commit.snippet.get("commit") == release.snippet.get("commit_sha")
        ]
        if matched:
            commit = matched[0]
            objects.append(
                {
                    "type": "Commit",
                    "id": commit.snippet["commit"],
                    "deployment": release.source_record,
                    "evidence": [release.id, commit.id],
                }
            )
            facts.append(
                {
                    "id": "fact:relation:" + release.id,
                    "kind": "computed",
                    "text": "发布记录与 Git 提交标识一致；这只确认变更归属，不证明故障因果。",
                    "evidence": [release.id, commit.id],
                    "transform": "commit-equality-v1",
                    "query_step": {"relation": "Deployment.commit"},
                }
            )
        elif commits:
            conflicts.append(
                {
                    "text": "发布指向的提交未匹配已读取的 Git 记录。",
                    "evidence": [release.id] + [e.id for e in commits],
                }
            )
    for observation in [e for e in evidence if e.source == "cluster"]:
        version = observation.snippet.get("release")
        matches = [
            e for e in releases if e.snippet.get("version") == version and version
        ]
        for release in matches:
            facts.append(
                {
                    "id": "fact:cluster-release:" + observation.id + ":" + release.id,
                    "kind": "computed",
                    "text": "集群工作负载的发布标签与结构化发布版本一致；因果关系仍需验证。",
                    "evidence": [observation.id, release.id],
                    "transform": "release-label-equality-v1",
                    "query_step": {"relation": "Incident.service.deployments"},
                }
            )
    bundle = ContextBundle(
        scope={
            "team": runtime.run.team,
            "subject": runtime.run.subject,
            "service": runtime.run.service,
        },
        objects=objects,
        facts=facts,
        evidence=evidence,
        missing=missing,
        conflicts=conflicts,
        freshness=freshness,
        plan=plan,
        token_budget=runtime.run.budget.tokens,
        retrieval=retrieval,
    )
    if len(bundle.model_dump_json().encode()) > runtime.run.budget.output_bytes:
        raise RuntimeError("output_budget_exhausted")
    if recorded is None:
        historical = runtime.authorize("memory")
        bundle.memories = historical.get("memories", [])
    runtime.hook(
        "context_assembled",
        {"facts": len(facts), "evidence": len(evidence), "conflicts": len(conflicts)},
    )
    return bundle, records


def describe(source, c):
    if source == "logs":
        return f"日志记录 {c.get('level', 'UNKNOWN')}: {c.get('message', '无消息')}"
    if source == "deployments":
        return f"发布版本 {c.get('version')} 指向提交 {c.get('commit_sha')}"
    if source == "git":
        return f"代码提交 {c.get('commit')}，配置差异：{c.get('config', '未提供')}"
    if source == "runbook":
        return "运行手册摘录：" + c.get("markdown", "")[:300]
    return "集群观测：" + json.dumps(c, ensure_ascii=False)[:1500]


def report(bundle):
    candidates = []
    logs = [e for e in bundle.evidence if e.source == "logs"]
    for term, text in [
        ("pool", "连接池耗尽可能导致请求等待；核对活跃连接、池上限和等待时间。"),
        ("timed out", "上游依赖延迟可能超过超时阈值；核对依赖耗时与阈值变更。"),
        ("invalid", "配置值可能不合法；对照运行时配置与发布提交。"),
        ("after release", "发布与异常时间相关；需要对照变更和实例指标验证因果。"),
    ]:
        matches = [e.id for e in logs if term in json.dumps(e.snippet)]
        if matches:
            candidates.append(
                {
                    "text": text,
                    "label": "有待验证",
                    "rule": "日志直接观测支持候选；时间相关不证明因果。",
                    "evidence": matches,
                }
            )
    cluster = [e for e in bundle.evidence if e.source == "cluster"]
    oom = [e.id for e in cluster if "OOMKilled" in json.dumps(e.snippet)]
    probe = [e.id for e in cluster if "Unhealthy" in json.dumps(e.snippet)]
    if oom:
        candidates.append(
            {
                "text": "观测到 OOMKilled 退出；内存为何超限仍需工作集、限制值及请求分布验证。",
                "label": "有待验证",
                "rule": "退出原因是观测事实，应用层原因仍是待验证解释。",
                "evidence": oom,
            }
        )
    if probe:
        candidates.append(
            {
                "text": "观测到探针失败事件；对照对应发布的探针路径与应用启动状态。",
                "label": "有待验证",
                "rule": "集群事件支持探针失败，尚不能单独确定应用故障根因。",
                "evidence": probe,
            }
        )
    return {
        "impact": bundle.scope["service"],
        "retrieval": bundle.retrieval,
        "answer": (
            f"检索范围内共 {bundle.retrieval.get('total_in_query', 0)} 条日志，匹配 {bundle.retrieval.get('matched', 0)} 条；以下展示 {len(logs)} 条可追溯证据。"
            if bundle.retrieval
            else "以下为检索到的证据；候选原因需要进一步验证。"
        ),
        "facts": bundle.facts,
        "candidates": candidates,
        "conflicts": bundle.conflicts,
        "missing": bundle.missing,
        "next_steps": [
            "核对实际部署版本与日志时间窗口。",
            "检查连接池和依赖延迟指标，补齐缺失来源后确认原因。",
        ],
        "evidence": [e.model_dump() for e in bundle.evidence],
        "freshness": bundle.freshness,
        "context": bundle.model_dump(mode="json"),
        "confidence_rule": "事实有直接来源；候选有待验证；无日志时不推断根因。",
        "historical_memory": bundle.memories,
        "mode": "deterministic-baseline",
    }
