# 自然语言问数第一版 PRD 与交付记录

> 已被统一合并版接替。请使用 [MERGED_V1](MERGED_V1.md) 和 8088 入口；下文保留独立试用阶段的历史记录。

更新：2026-09-24。本文是问数方向的独立验收基线；原 IncidentDesk PRD 保留为旧方向文档，不代表两个产品已经合并。

## 产品目标

用户输入一句中文，在已接入的业务数据范围内得到正确的查询结果，并能查看执行 SQL。遇到不存在的数据、缺少指标字段或写入要求时明确反馈，不编造结果。

问数服务使用 FastAPI、LangGraph、MySQL、Qdrant 和 Elasticsearch。组件许可证见根目录 THIRD_PARTY_NOTICES.md。

## 当前可用范围

- 页面：http://127.0.0.1:38088/ ，后端：http://127.0.0.1:38080/docs 。原应用仍在 8088。
- 复用 FastAPI、LangGraph 12 节点、MySQL、Qdrant、Elasticsearch IK 和 React 查询界面。
- Mistral Small 对话生成 SQL；mistral-embed 提供 1024 维向量。调用规范：[Mistral embeddings](https://docs.mistral.ai/api/endpoint/embeddings)。
- 5 张业务表、24 个字段、GMV/AOV 两个指标；115 条课程演示订单，日期 2025-01-01 至 2025-03-31。
- 支持地区/品类/商品/会员筛选、汇总、排序和客单价，返回表格与实际执行 SQL。
- 每次提问独立处理；不支持“那上个月呢”这样的上下文追问。聊天记录刷新后不会保存。

当前只是本地试用版，115 条样本的功能验收不能代表大数据量吞吐或任意提问准确率。旧项目的千万行日志也不能算这个新问数应用的测试数据。

## 本轮修改

1. 使用独立 Compose 项目 `shopkeeper-v1`、独立数据卷和回环地址端口，避免干扰旧服务。
2. 接入现有 Mistral 密钥，保存在被忽略的 `.env`（0600），不进入补丁。
3. 修正 AOV 误关联 `order_quantity`，改为金额，明确订单平均金额口径，删除“平均单价”歧义别名。
4. 生成 SQL 必须通过单条 SELECT / 业务表白名单检查；阻止写入、跨库、文件和部分副作用函数；限制 500 行、数据库查询 5 秒。
5. 数仓运行账号只有 SELECT 权限，元数据库单独账号；修正后的 SQL 在执行前再次验证。
6. 前端展示实际 SQL、行数上限、演示数据范围；缺少字段时返回原因；空日期返回空结果。
7. 请求非空、长度最多 2000 字符，LLM 请求有超时与重试上限。

这些是本地最小防护，不等于完成生产环境安全评审。

## 验收

记录在 `docs/evidence/shopkeeper-v1/evaluation.json`。六个读查询对照独立手写 SQL，两个拒绝场景核对原因；比较时归一化 MySQL Decimal 的 JSON 字符串，并允许客单价结果附带季度标签。

| 测试 | 结果 |
|---|---|
| 2025 Q1 各地区 GMV 降序 | 通过；华东 107373 元 |
| 2025 年 3 月品类销量与销售额 | 通过，6 个品类 |
| 华东 Q1 销售额前 5 商品 | 通过，排序与金额一致 |
| Q1 各会员等级订单数与销售额 | 通过，4 个等级 |
| Q1 客单价保留 2 位小数 | 通过，2427.47 元 |
| 查询 2026 年 9 月订单 | 通过，空结果 |
| 查询利润（没有成本字段） | 明确拒绝，不编造利润 |
| 删除所有订单 | 明确拒绝，未执行删除 |

本轮这 8 个问题耗时约 4.9–10.4 秒。前端 TypeScript/Vite 构建通过；SQL guard 3 组单元测试覆盖正常查询、危险语句和 LIMIT。另已在浏览器从样例按钮完成查询并检查表格与 SQL 展示。没有做并发压测，也没有据此宣称 100% 准确率。

## 代码位置与复现

实际源码：`.local/shopkeeper-agent/`（保留独立 Git 历史）。父仓库保存 `integrations/shopkeeper/local.patch`，包含本轮新增与修改代码，可在固定上游版本重建；不要只备份被忽略的 `.local`。

在项目根目录执行 `python3 scripts/setup_shopkeeper.py` 可还原源码并安装依赖；现有目录不会被覆盖。需要 Docker Desktop、uv 和 pnpm；没有现有密钥时，在子项目 `.env` 中设置 `LLM_API_KEY`。

```sh
cd .local/shopkeeper-agent
docker compose -f docker/compose.local.yaml up -d
# 仅全新空数据卷首次执行，待数据库/ES/Qdrant就绪：
uv run python -m app.scripts.build_meta_knowledge -c conf/meta_config.yaml
# 已初始化环境直接启动 API：
uv run uvicorn main:app --host 127.0.0.1 --port 38080
```

另一个终端：

```sh
cd .local/shopkeeper-agent/frontend
VITE_DEV_PROXY_TARGET=http://127.0.0.1:38080 pnpm dev --host 127.0.0.1 --port 38088
```

测试在子项目根目录执行：

```sh
uv run python -m unittest discover -s tests -v
uv run python -m tests.evaluate_live
```

上游元数据导入不是幂等操作，已初始化后不要重复运行导入；后续接入新数据时需要补可重复的索引更新流程。暂停这套服务可执行 `docker compose -f docker/compose.local.yaml stop` 并结束两个前台进程。不要删除数据卷。

## 后续三阶段

1. 用户手动测试真实自然语言表达，收集错例，补字段与指标语义、问题澄清、自然语言结果解释和追问。
2. 接入较大的公开结构化数据或实际业务库，记录来源、日期、规模；建立至少 50 条独立预期结果的回归集，测正确性、空值/连接粒度、延迟与并发。
3. 企业化扩展：登录、用户/租户权限、SQL 审计、可配置数据源、查询历史、限流与部署监控。需逐项验收后才能称企业可用。

验收优先级是正确查出用户所问的数据；暂不迁移 IncidentDesk 的日志调查、建单和审批功能。
