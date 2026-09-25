# 数据字典与协议实例

业务 schema 由 Go 独占写入。完整列与约束以 `db/migrations` 为准。

| 实体 | 核心字段与语义 |
|---|---|
| investigation | id、subject/team/service、start/end/timezone、status、source_version、trace_id；创建与job同事务 |
| job | owner、generation、lease_until、attempts、available_at、state、last_callback/result_hash；旧代提交被fence拒绝 |
| event | investigation+seq主键、kind、payload、created_at；游标有序且可重放 |
| action | target/title/body、version/digest、approved_version/digest、source_version、marker、state、result；未知结果不再次POST |
| approval | 审批者、动作、版本与决定；内容变更要求新批准 |
| memory | team/service、来源调查/版本、content、status、reviewer、expires_at；仅confirmed且当前水位/未过期可检索 |
| badcase | 来源调查、category、脱敏manifest、label、reviewer、status；candidate不是reviewed，入开发集后不再算独立保留样本 |
| source_changes | service、水位和modified/deleted；可信通知与管理员操作共用失效路径 |
| agent.context_cache | 身份/团队/服务/时间/水位/协议版本hash、bundle、录制来源、采集时间；TTL30秒 |
| agent.source_index | service/source/record_id、version、watermark、available；版本变化与tombstone同步 |
| agent.artifacts | team/task前缀key、SHA-256、水位、staged/ready、created_at；读取重新授权 |

Badcase 分类：mapping（实体映射）、retrieval（检索遗漏）、conflict（证据冲突）、inference（推断错误）、authorization（越权）、tool（工具失败）、recovery（恢复错误）。审核者须为来源团队审批者；`POST /api/v1/badcases/{id}/review` 的 body 是 `{"label":"人工确认的期望行为"}`。审核身份自动取当前JWT，不接受调用者伪造reviewer。

Ontology/映射/合法关系与 QueryPlan 实现位于 `worker/incident_worker/context.py`，结构定义位于 `contracts/*.schema.json`。具体 QueryPlan、ContextBundle、证据链、RunManifest 见 `docs/evidence/recording.json` 的 report.context / manifest。发布→Commit 的计算事实记录输入引用与 `commit-equality-v1`；集群发布标签匹配记录 `release-label-equality-v1`；二者均不证明因果。

RunManifest 包含代码版本、模型标识/参数、prompt/skill/tool/ontology/mapping/retrieval/policy/evaluator版本与数据录制。早期实验的 code=working-tree 如实保留；后续镜像通过 build ARG 固定提交。模型版本不能由供应商固定时不承诺逐位复现。
