# P0 验收矩阵

唯一基线：[PRD v1.1](PRD.md)。`PASS` 仅表示此行说明的本地验收范围；`EXTERNAL BLOCK` 表示完整目标仍缺明确外部条件。不得把本地接口桩/录制模型计入真实平台、模型或人工质量成绩。历史失败负载保留为 `FAIL`；未运行远端 CI 为 `NOT RUN`。

Python 命令统一前缀 `uv run --project worker python scripts/`；shell 脚本用 `./scripts/`。K8s 命令按 README 建立 18080/18090/18091 端口转发并串行执行；security_regression.py / demo_faults.py 使用 README 的 TEST_API、TEST_SOURCE 配置。Go/Python 单测与浏览器复验作为补充证据。文件路径从仓库根开始。

| ID | 要求 | 实现 | 验证脚本 | 状态 | 实测说明及证据 |
|---|---|---|---|---|---|
| FR-01 | 基于已登录用户、服务和时间范围发起调查。 | [backend/internal/app/app.go](../backend/internal/app/app.go) | `smoke.py` | PASS | OIDC、服务/时间范围、幂等受理；[smoke.json](evidence/smoke.json) |
| FR-02 | 查询四类来源：日志、发布记录、Git 代码变更、Markdown 运行手册。 | [worker/incident_worker/connectors.py](../worker/incident_worker/connectors.py) | `smoke.py` | PASS | 四源实际读取；远程 GitHub 源见外部项；[smoke.json](evidence/smoke.json) |
| FR-03 | 展示调查进度、证据、候选原因和未知项。 | [web/src/main.tsx](../web/src/main.tsx) | `smoke.py` | PASS | 浏览器已检查；事实/候选/缺口/证据/进度；[smoke.json](evidence/smoke.json) |
| FR-04 | 持久保存任务；支持等待补充信息、等待审批、取消和进程重启后的恢复。 | [backend/internal/app/queue.go](../backend/internal/app/queue.go) | `recovery_matrix.py` | PASS | 持久状态、等待补充、草稿审批、重启恢复；[recovery-matrix.json](evidence/recovery-matrix.json) |
| FR-05 | 生成 GitHub Issue 草稿，经批准后向配置的测试仓库创建 Issue。 | [backend/internal/app/actions.go](../backend/internal/app/actions.go) | `smoke.py` | EXTERNAL BLOCK | 本地桩通过；真实 GitHub 仓库/token 未提供；[smoke.json](evidence/smoke.json) |
| FR-06 | 工具执行阶段校验权限；对建单动作处理幂等与结果未知状态。 | [backend/internal/app/actions.go](../backend/internal/app/actions.go) | `security_regression.py` | PASS | 实时权限、审批、幂等、unknown 核对；[security-regression.json](evidence/security-regression.json) |
| FR-07 | 展示审计事件，保存可用于离线回归的执行记录。 | [backend/internal/app/governance.go](../backend/internal/app/governance.go) | `replay.py docs/evidence/recording.json` | PASS | 当前授权导出、离线无写入；[replay.txt](evidence/replay.txt) |
| FR-08 | 提供一个能注入故障的演示服务和固定评估样本。 | [demo/server.py](../demo/server.py) | `demo_faults.py` | PASS | 真实故障与24固定变体分别保存；[demo-faults.json](evidence/demo-faults.json) |
| FR-09 | 实现 API 与 Worker 分离部署、持久任务队列、并发控制、SSE 断线续传和连接超时治理。 | [backend/internal/app/queue.go](../backend/internal/app/queue.go) | `k8s_reliability.py` | PASS | API/Worker分离、全局上限与SSE；[k8s-reliability.json](evidence/k8s-reliability.json) |
| FR-10 | 提供 Helm 部署，在本地 Kubernetes 验证多副本、滚动发布、Pod 故障恢复及扩缩容。 | [deploy/helm/incidentdesk](../deploy/helm/incidentdesk) | `k8s_hpa.py` | PASS | 多副本、滚动版本升级、Pod故障、HPA；[k8s-hpa.json](evidence/k8s-hpa.json) |
| FR-11 | 交付数据库备份恢复演练、监控看板、CI 校验与后端负载测试报告。 | [.github/workflows/ci.yaml](../.github/workflows/ci.yaml) | `backup_restore.py` | EXTERNAL BLOCK | 负载/备份/监控本地通过；无远端仓库，远端CI未运行；[backup.json](evidence/backup.json) |
| FR-12 | 实现研发对象 Ontology、来源语义映射、受约束查询计划、跨源事实组装和可追溯的 ContextBundle。 | [worker/incident_worker/context.py](../worker/incident_worker/context.py) | `evaluate.py` | PASS | 有限Ontology、约束计划、跨源关系与引用；[evaluation.json](evidence/evaluation.json) |
| FR-13 | 提供统一 Connector 契约；处理增量同步、删除、版本、访问范围和数据时效；至少跑通结构化表、文档、Git、日志 API 四种适配器。 | [worker/incident_worker/connectors.py](../worker/incident_worker/connectors.py) | `source_lifecycle.py` | PASS | 四适配器、版本/删除/水位/索引与缓存；[source-lifecycle.json](evidence/source-lifecycle.json) |
| FR-14 | 提供应用自有的 Runtime SDK 契约、有限 Skill / MCP Gateway 和受限分析沙箱路径，业务权限不能被框架默认行为绕过。 | [worker/incident_worker/runtime.py](../worker/incident_worker/runtime.py) | `sandbox_gateway.py` | PASS | 实际MCP与K8s固定沙箱、普通Context API；[gateway-integration.json](evidence/gateway-integration.json) |
| FR-15 | 实现完整 trace、无副作用离线回放、evaluation hooks、失败样本审核入库与版本回归；积累可审核的企业记忆。 | [worker/incident_worker/evaluation.py](../worker/incident_worker/evaluation.py) | `evaluate.py` | EXTERNAL BLOCK | trace/回放/Hook/审核接口/记忆已测；独立人工badcase与试用未提供；[evaluation.json](evidence/evaluation.json) |
| AC-01 | 业务闭环 | [backend/internal/app/actions.go](../backend/internal/app/actions.go) | `smoke.py` | EXTERNAL BLOCK | 本地闭环通过；真实Issue待授权仓库/token；[smoke.json](evidence/smoke.json) |
| AC-02 | 证据完整性 | [worker/incident_worker/context.py](../worker/incident_worker/context.py) | `evaluate.py` | PASS | 48次规则引用检查，范围/截断/缺口显式；[evaluation.json](evidence/evaluation.json) |
| AC-03 | 结论质量 | [evaluation/RUBRIC.md](../evaluation/RUBRIC.md) | `evaluate.py` | EXTERNAL BLOCK | 人工评分0；Mistral 已接通但尚无独立人工评分，不宣称80%；[evaluation.json](evidence/evaluation.json) |
| AC-04 | 越权访问 | [backend/internal/app/app.go](../backend/internal/app/app.go) | `security_regression.py` | PASS | 跨团队、报告、缓存、工具拒绝；Python负向补充；[security-regression.json](evidence/security-regression.json) |
| AC-05 | 审批边界 | [backend/internal/app/actions.go](../backend/internal/app/actions.go) | `security_regression.py` | PASS | 未批/无权/旧版本/来源失效均拒绝；[go-tests.txt](evidence/go-tests.txt) |
| AC-06 | 幂等与未知结果 | [backend/internal/app/actions.go](../backend/internal/app/actions.go) | `smoke.py` | PASS | 8并发批准、超时unknown、marker核对唯一原Issue；[smoke.json](evidence/smoke.json) |
| AC-07 | 恢复 | [worker/incident_worker/main.py](../worker/incident_worker/main.py) | `recovery_matrix.py` | PASS | 查询后、待审批、丢响应后终止Worker；不盲目重做；[recovery-matrix.json](evidence/recovery-matrix.json) |
| AC-08 | 取消 | [backend/internal/app/app.go](../backend/internal/app/app.go) | `security_regression.py` | PASS | 取消使待执行审批失效，外部已发生写入保留核对；[security-regression.json](evidence/security-regression.json) |
| AC-09 | 可观测性 | [backend/internal/app/telemetry.go](../backend/internal/app/telemetry.go) | `smoke.py` | PASS | 任务/工具/审批/动作可关联；脱敏单测通过；[recording.json](evidence/recording.json) |
| AC-10 | 可复现性 | [README.md](../README.md) | `deploy-local.sh` | PASS | 实际Compose/Helm及浏览器复验；新环境仍依赖镜像下载；[deployment.json](evidence/deployment.json) |
| AC-11 | 后端负载 | [scripts/load.py](../scripts/load.py) | `load.py` | PASS | 20RPS/600秒/12000请求；p95 9.71ms，非成功0；[load.json](evidence/load.json) |
| AC-12 | 任务承载 | [backend/internal/app/queue.go](../backend/internal/app/queue.go) | `k8s_reliability.py` | PASS | 100受理全部completed；峰值9；race测试全局10；[k8s-reliability.json](evidence/k8s-reliability.json) |
| AC-13 | 队列故障 | [backend/internal/app/queue.go](../backend/internal/app/queue.go) | `recovery_matrix.py` | PASS | 提交后、领取后、检查点后Worker故障；[recovery-matrix.json](evidence/recovery-matrix.json) |
| AC-14 | 租约接管 | [worker/entrypoint.sh](../worker/entrypoint.sh) | `lease_takeover.py` | PASS | SIGSTOP超租约→新代接管→SIGCONT旧进程；[lease-takeover.json](evidence/lease-takeover.json) |
| AC-15 | SSE | [backend/internal/app/queue.go](../backend/internal/app/queue.go) | `k8s_sse.py` | PASS | 跨API副本补发、客户端去重；异常游标快照补充验证；[k8s-sse.json](evidence/k8s-sse.json) |
| AC-16 | K8s 故障与发布 | [deploy/helm/incidentdesk](../deploy/helm/incidentdesk) | `k8s_demo_faults.py` | PASS | 真实探针/OOM与报告关联；Worker删除和多次滚动升级；[k8s-demo-faults.json](evidence/k8s-demo-faults.json) |
| AC-17 | 扩容效果 | [scripts/k8s_reliability.py](../scripts/k8s_reliability.py) | `k8s_hpa.py` | PASS | 1/3Worker排队和吞吐实测、HPA2→4→2；模型配额未知；[k8s-reliability.json](evidence/k8s-reliability.json) |
| AC-18 | 数据恢复 | [scripts/backup_restore.py](../scripts/backup_restore.py) | `backup_restore.py` | PASS | 独立恢复、关联核对、RTO1.75秒；快照后写入不纳入；[backup.json](evidence/backup.json) |
| AC-19 | 网络与集群权限 | [deploy/helm/incidentdesk/templates/network.yaml](../deploy/helm/incidentdesk/templates/network.yaml) | `k8s_network.py` | PASS | 真实网络拒绝和SA越权拒绝；[k8s-network.json](evidence/k8s-network.json) |
| AC-20 | Ontology 与映射 | [worker/incident_worker/context.py](../worker/incident_worker/context.py) | `evaluate.py` | PASS | 别名、歧义、非法关系和范围检查；[python-tests.txt](evidence/python-tests.txt) |
| AC-21 | 联邦查询与上下文 | [worker/incident_worker/context.py](../worker/incident_worker/context.py) | `context_api.py` | PASS | 四源/集群、独立源时间、计算关系、冲突并存；[context-api.json](evidence/context-api.json) |
| AC-22 | 增量与权限 | [backend/internal/app/sources.go](../backend/internal/app/sources.go) | `source_lifecycle.py` | PASS | 修改/删除/撤权；报告、索引、缓存、回放和记忆失效；[source-lifecycle.json](evidence/source-lifecycle.json) |
| AC-23 | 企业记忆 | [backend/internal/app/governance.go](../backend/internal/app/governance.go) | `source_lifecycle.py` | PASS | 候选不返回、确认、过期、撤销和团队过滤；[source-lifecycle.json](evidence/source-lifecycle.json) |
| AC-24 | Gateway 与沙箱 | [worker/incident_worker/gateway.py](../worker/incident_worker/gateway.py) | `sandbox_gateway.py` | PASS | 普通API/MCP授权；Skill负向；只读/禁网/超时/内存；[gateway-integration.json](evidence/gateway-integration.json) |
| AC-25 | 回放与评估 | [scripts/replay.py](../scripts/replay.py) | `replay.py docs/evidence/recording.json --reevaluate` | PASS | 离线无写入、缺失录制失败；6Hook正反例；[replay-new-version.txt](evidence/replay-new-version.txt) |
| AC-26 | Badcase 回归 | [backend/internal/app/governance.go](../backend/internal/app/governance.go) | `evaluate.py` | EXTERNAL BLOCK | 自动分类/审核接口和预置退化门禁已测；独立人工确认未提供；[evaluation.json](evidence/evaluation.json) |
| AC-27 | 框架边界与 DX | [worker/incident_worker/context_api.py](../worker/incident_worker/context_api.py) | `context_api.py` | PASS | 实际普通API；基线/框架隔离；样例Connector契约通过；[python-tests.txt](evidence/python-tests.txt) |
| AC-28 | Go / Python 边界 | [db/migrations/001_init.sql](../db/migrations/001_init.sql) | `db_boundary.py` | PASS | Python无业务写权限/Issue凭据；回调代次与取消已测；[db-boundary.json](evidence/db-boundary.json) |
| AC-29 | Go 工程验证 | [backend/internal/app/queue_test.go](../backend/internal/app/queue_test.go) | `test-go.sh` | PASS | race、goroutine收敛、pprof/SQL实测瓶颈报告；[go-tests.txt](evidence/go-tests.txt) |

## 外部复验入口

- **真实模型质量**：Mistral 接入及小规模真实调用已通过（见 SEARCH_V2.md）；仍需 12 保留例×3、固定预算基线对比/消融和独立人工评分，记录 Token、耗时及价格。
- **GitHub**：指定演示来源/测试 Issue 仓库及最低必要权限 token；审批真实草稿后保存真实 URL/回读。当前无 Git remote，故未推送也未执行远端 CI。
- **人工参与**：按固定 RUBRIC 评分与确认 badcase；未见样本一旦用于修复须移出保留集，不虚构独立评分和试用反馈。

所有其他可在本机执行的实现和验收均继续完成；外部项目保持阻塞，不以降低门槛或修改 PRD 关闭。


2026-09-24 v1.1：自然语言入口、Mistral、大数据索引/分页/稀有模式与历史来源匹配的最新实测见 [SEARCH_V2.md](SEARCH_V2.md)。以上旧性能、K8s 与确定性模型证据保持原始范围，不自动外推到新版。


## v1.1 自然语言检索增补

| ID | 状态 | 本次验收范围 |
|---|---|---|
| NL-01 | PASS | 中文日期/相对时间/服务/block，澄清与最终范围；见 SEARCH_V2.md |
| NL-02 | PASS（小规模真实调用） | Mistral 解析和回答、Token/耗时、密钥隔离与引用检查；独立人工质量仍未验收 |
| NL-03 | PASS（本机固定开发回归集） | 1592万行，18窗口统计、8/8标注窗口覆盖、4并发24任务及健康探测 |
| NL-04 | PASS | 5项历史关联专项，公开来源不混用演示材料 |
| NL-05 | PASS | 幂等重复/冲突、跨团队拒绝、零命中和引用跳转；Go/Python回归 |
