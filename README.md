# IncidentDesk

[![Verification](https://github.com/zouyichen2002-droid/IncidentDesk/actions/workflows/ci.yaml/badge.svg)](https://github.com/zouyichen2002-droid/IncidentDesk/actions/workflows/ci.yaml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**用自然语言查询业务数据、追问筛选条件，并查找日志与研发证据。**

IncidentDesk is an open-source natural-language data and incident investigation workbench. It combines a Go control plane, Python / LangGraph query services, Mistral, and a React UI. This is a local development project with reproducible test evidence, not a production availability guarantee.

| 当前能力 | 示例 |
|---|---|
| 只读业务问数、分组与排名 | “2025年第一季度各地区销售额，取前3名” |
| 持久会话、追问与上下文重置 | “换成2月”“那华南呢”“忘掉之前条件” |
| 普通知识问答与缺信息澄清 | “客单价是什么意思？” |
| 日志、发布、Git、运行手册查询 | “查一下订单服务最近24小时的超时日志” |
| 证据、权限与审批 | 查看来源；审阅并批准模拟 Issue 草稿 |

**数据边界：** 业务库是 2025 年第一季度的 115 条教学订单（5表、24字段）。千万行公开日志测试是独立环境，不是当前业务库规模。模型回答与路由可能出错；真实 GitHub Issue 写入尚未完成外部验收。图表、导出、任意数据库自助接入和完整结构化查询规划仍待实现。

最近一轮本机验收：61/61 项接口检查、5/5 项分页断言、15 项 Go 测试及 26 项查询服务测试通过，见 [测试报告](docs/BUGFIX_ROUND3.md)。这些是有限场景的记录，不代表任意问法准确率或生产性能。GitHub CI 单独运行不需要模型密钥的测试。

[需求 PRD](docs/PRD.md) · [合并架构与使用](docs/MERGED_V1.md) · [持久会话](docs/CONVERSATION_MEMORY.md) · [能力对照与路线图](docs/ATGUIGU_CAPABILITIES.md) · [第三方来源](THIRD_PARTY_NOTICES.md) · [参与贡献](CONTRIBUTING.md)

## 启动

需要 Git、Docker Desktop/Compose，以及自己的 Mistral API key。测试环境为 Apple Silicon、10 核、32 GiB；多数据库容器需要充足内存。首次构建需要联网下载镜像、依赖和中文分词插件。

```sh
git clone https://github.com/zouyichen2002-droid/IncidentDesk.git
cd IncidentDesk
cp .env.example .env
# 编辑 .env：设置 HARNESS=mistral 和 MISTRAL_API_KEY=<你的密钥>
./scripts/deploy-local.sh
```

`deploy-local.sh` 会启动服务、应用增量迁移并构建元数据索引。业务问数、聊天和首次向量索引构建需要有效的 Mistral key，调用可能产生供应商费用；不提供或共享项目作者的密钥。无模型密钥可运行 CI 中的离线测试，但不能体验完整自然语言问数。

打开 http://localhost:8088 。演示密码均为 `demo-password`：Alice 是 orders 审批者，Bob 是 orders 调查者，Carol 是 payments 审批者，Admin 只管理配置。演示凭据仅用于本机；端口只绑定 loopback。数据库迁移与演示发布/Git/运行手册在首次启动自动初始化。

```sh
# 产生真实 HTTP 超时日志，再从工作台发起调查
curl -fsS http://localhost:8090/control -H "X-Demo-Key: ${DEMO_KEY:-local-demo-key}" -H 'Content-Type: application/json' -d '{"fault":"dependency_timeout"}'
curl http://localhost:8090/business
```

在工作台输入一句话（如“查一下订单服务最近24小时的超时”），或展开手动服务/历史时间，调查完成后检查证据，保存草稿并由 Alice 批准。默认 Issue 为有持久化和回读的本地 HTTP 桩，页面明确标记。`unknown` 状态只能核对，不能再次建单。

API：8080；普通 Context API：8091（仅可信服务身份）；演示身份/来源：8090；Prometheus：9090；Grafana：3000（admin / local-grafana）；PostgreSQL：55432。S3 的 9000 端口用于本地调试，应用读取必须经过当前范围/水位校验。

停止但保留数据：`docker compose down`。不要在需要保留证据时删除 volumes。迁移位于 `db/migrations`；已有数据库通过部署脚本重复应用幂等增量迁移。

## 本地验证

安装 Go 1.27.1、Node 24.18.0、uv（本机 0.11.26，镜像/CI 固定 0.10.12；Python 3.12）、Helm 4.3.0 后：

```sh
uv sync --project worker --frozen --python 3.12
(cd web && npm ci)
./scripts/test-go.sh
(cd worker && uv run pytest -q)
(cd web && npm run build && npm audit --audit-level=high)
uv run --project worker python scripts/smoke.py
uv run --project worker python scripts/evaluate.py
uv run --project worker python scripts/ablation.py
docker build -t incidentdesk-sandbox:0.1.0 sandbox
uv run --project worker python scripts/test_sandbox.py
uv run --project worker python scripts/backup_restore.py
```

这些脚本会创建演示调查、修改受控故障/权限和测试 Issue，测试异常后应查看日志及恢复状态。仅用于这里的独立开发实例。`scripts/test-go.sh` 使用独立 `incident_test` 数据库。完整 10 分钟负载：`uv run --project worker python scripts/load.py`。证据文件写入 `docs/evidence`，不会把新运行冒充旧运行。

## 公开大规模日志测试

已用 Loghub 的完整 BGL 与 HDFS_v1 日志进行独立测试：15,923,592 行、84 次调查，包含无索引与测试库索引对照。测试发现并发读取超时与前 50 条截断造成的异常遗漏，详见 [公开日志实测报告](docs/PUBLIC_LOG_BENCHMARK.md)。测试工作台为 http://localhost:28088 ，数据与默认工作台隔离；这不代表真实模型或生产质量验收通过。

## Kubernetes

安装 k3d 5.9.0 和与服务端同 minor 的 kubectl 1.34.x；Docker 保持运行。集群为本机 k3s v1.34.1，1 server + 2 agents。

```sh
./scripts/deploy-k8s.sh
kubectl -n incidentdesk port-forward service/api 18080:8080
# 另开终端
kubectl -n incidentdesk port-forward service/demo 18090:8090
kubectl -n incidentdesk port-forward service/context 18091:8091
kubectl -n incidentdesk port-forward service/web 18088:80
```

故障脚本会改 Worker 副本数/测试延迟，必须串行运行：

```sh
uv run --project worker python scripts/k8s_reliability.py
uv run --project worker python scripts/lease_takeover.py
uv run --project worker python scripts/recovery_matrix.py
uv run --project worker python scripts/k8s_sse.py
uv run --project worker python scripts/k8s_hpa.py
uv run --project worker python scripts/k8s_network.py
uv run --project worker python scripts/k8s_demo_faults.py
uv run --project worker python scripts/sandbox_gateway.py
uv run --project worker python scripts/context_api.py
uv run --project worker python scripts/source_lifecycle.py
TEST_API=http://localhost:18080 TEST_SOURCE=http://localhost:18090 uv run --project worker python scripts/security_regression.py
```

测试后检查 Worker 无 `TEST_DELAY_SECONDS` 残留。升级镜像：`./scripts/build-k8s-revision.sh 0.5.0`（采用明确新标签，避免覆盖正在使用的版本）。Helm 开发 Secret 与 SQL 角色密码必须保持一致；生产 Secret、TLS/Ingress、持久存储与高可用配置不属于此开发 Chart 的保证。

## 外部集成验收

1. 提供已授权的测试 `owner/repo`，在 Admin 配置中更新服务仓库；将有最低必要 Issue 写权限的 token 放入本机 `.env` 的 `GITHUB_TOKEN`，设置 `GITHUB_API_URL=https://api.github.com`。只有 Go API 接收该 token。重建 API 后，由审批者审阅草稿并批准；保存真实 Issue URL/回读证据。
2. 将已授权的 OpenAI-compatible 模型配置写入 `.env` 的 `MODEL_NAME`、`MODEL_BASE_URL`、`MODEL_API_KEY`，设置 `HARNESS=deepagents`，重启 Worker。代码使用真实 Deep Agents 状态/工具中间件和 LangGraph Postgres checkpoint；录制模型测试不能替代真实供应商请求。
3. 按 `evaluation/RUBRIC.md` 对 12 个保留用例各 3 次独立评分，公开有效调查分子/分母、失败样本和波动；人工确认 badcase 与试用反馈。未提供模型前不报告 ≥80% 质量或模型吞吐/成本。

## 导航

- [手工复核样例](docs/MANUAL_CASE.md)、[数据字典](docs/DATA_DICTIONARY.md)
- [架构与边界](docs/ARCHITECTURE.md)、[关键决策](docs/adr/0001-boundaries.md)
- [生命周期和故障处理](docs/LIFECYCLE.md)、[Connector/Skill 扩展](docs/CONNECTOR_GUIDE.md)
- [API OpenAPI](contracts/openapi.json)、同目录 Pydantic JSON Schema
- [验收证据](docs/evidence)、[评估规则](evaluation/RUBRIC.md)、[已知限制](docs/KNOWN_LIMITS.md)
- `worker/incident_worker/context.py`：Ontology、映射、QueryPlan、证据组装；`connectors.py`：四类适配器；`runtime.py`：业务自有 SDK
- `backend/internal/app`：OIDC、持久队列、租约、审批、动作、当前权限、审计；`db/migrations`：独立角色/schema


## 一句话找证据（Mistral）

在忽略的 `.env` 设置 `HARNESS=mistral`、`MISTRAL_API_KEY`、`MISTRAL_MODEL=mistral-small-latest`；已有配置无需重写。运行 `./scripts/deploy-local.sh`。模型 key 只注入 context/worker；没有密钥时规则解析明确标记，已配置模型失败不静默冒充成功。

- 演示四源：[localhost:8088](http://localhost:8088/)，Alice 查询订单服务；新日志由演示 HTTP 请求生成。
- 本机完整公开日志库：[localhost:28088](http://localhost:28088/)，Alice/Bob 查 BGL，Carol 查 HDFS，密码均为 `demo-password`。两个环境的数据卷相互独立。
- Alice 示例：`查BGL在2005年11月3日的异常日志`。
- Carol 示例：`查HDFS在2008年11月9日 blk_-1608999687919862906 的日志`。
- 日期默认使用浏览器时区；API 可明确传 `timezone: UTC`。因此同一日期在不同时区的统计不同。范围最多 7 天，未写时间的历史归档查询采用该来源最后 24 小时，并记录解释。
- 公共数据没有配套业务 Git/部署/手册，结果显示“部分完成”是资料缺口；日志证据仍可查看。空命中显示“等待补充”。

公开库真实模型启动：`BENCH_HARNESS=mistral docker compose -f compose.benchmark.yaml up -d --scale worker=3`。
重跑少量真实模型验收：`uv run --project worker python scripts/search_v2_acceptance.py`（会产生 API 调用）。来源全库回归：`docker compose -f compose.benchmark.yaml exec -T demo python /bench-scripts/search_v2_corpus.py`。

新接口为 `POST /api/v1/investigations/natural`，需要 Bearer token 和 `Idempotency-Key`，请求 `{ "text": "查BGL在2005年11月3日的异常日志", "timezone": "UTC" }`；返回 202 调查 ID 或 200 补充问题。手动创建接口兼容新增 `query` 字段。

Helm 默认仍为离线可运行模式。真实模型使用已有 Secret（键 `MISTRAL_API_KEY`），设置 `model.harness=mistral` 与 `model.existingSecret`；chart 不包含真实密钥。现有卷需执行迁移 `003_search.sql`。本次 Helm 只做渲染校验，Kubernetes 历史性能证据不等于新版 Mistral 性能。

详细结果、复现命令和限制见 [SEARCH_V2.md](docs/SEARCH_V2.md)。

2026-09-25：统一入口已扩展普通问答与连续追问，见 [对话入口升级](docs/CONVERSATION_V1.md)。

2026-09-25：新增 [持久会话与可恢复追问](docs/CONVERSATION_MEMORY.md)，历史对话、刷新恢复、账号隔离、幂等与并发验收已完成；PRD 更新为 v1.5。

## 开源与来源

项目原创部分采用 [MIT](LICENSE)；`query/` 来自 didilili/shopkeeper-agent 的 MIT 教学实现，保留原作者许可证和固定提交信息，不能冒称尚硅谷官方源码。第三方依赖、运行服务及数据按各自许可使用，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。公开版本包含脱敏的本机验收记录，不包含 `.env`、模型密钥、运行数据库、下载的完整日志语料或私人开发目录。
