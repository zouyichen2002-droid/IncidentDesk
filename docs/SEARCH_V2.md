# 自然语言检索与大数据修复验收

2026-09-24。PRD v1.1 增补 NL-01–NL-05；实现见 ADR 0002。以下均为本机开发环境证据，不代表全部 P0 或生产验收。

## 已交付

1. **大数据检索**：索引进入启动/迁移流程；message 全文检索、服务/时间/级别索引、游标分页、低频模式代表与分层取样。重查询转入线程池，避免卡住身份/健康接口。默认日志 20 条/页、最多 3 页；报告显示真实条件匹配总数与证据上限。
2. **历史来源关联**：Git 必须关联该服务部署 SHA；运行手册读取截止时间之前的版本。部署包含窗口前最后一个有效基线版本。BGL/HDFS 不混用本地订单系统 Git、发布和运行手册；缺失明确披露。
3. **一句话 + Mistral**：自然语言主入口、手动历史时间备用入口、真实结构化解析与中文回答、实际模型用量记录、引用跳转。Go 对生成的计划复验权限和范围。大小写级别归一化、服务名不作为关键词、具体 block ID/引号词原样保留；明确时间不被模型改成数据最新时间。

## 测试结果

完整公开库为 BGL **4,747,963** 行 + HDFS **11,175,629** 行，合计 **15,923,592 行**。下载来源、校验和、时区解释和原始实验保留在 [PUBLIC_LOG_BENCHMARK.md](PUBLIC_LOG_BENCHMARK.md)。

| 验证 | 本次结果 | 证据 |
|---|---|---|
| 18 个固定窗口完整数量 | 18/18 与原始导入统计相同 | [corpus.json](evidence/search-v2/corpus.json) |
| BGL 含标注异常的窗口至少返回一条异常 | 原首 50 条方案 1/8；新版 8/8；含 162,695 行中仅 1 条告警窗口 | [corpus.json](evidence/search-v2/corpus.json) |
| 直接来源检索，最多三页 | 中位约 0.08 秒；最大 1.73 秒（18 个窗口，热索引） | 同上 |
| 4 并发、24 个端到端调查 | 24/24 返回日志、数量正确、无来源错误、无缓存命中；p50 1.264 秒、p95 2.725 秒、最大 4.715 秒 | [concurrency.json](evidence/search-v2/concurrency.json) |
| 上述并发期间来源健康接口 | 60 次探测，0 失败；p95 35ms，最大 51ms | 同上 |
| 真实 Mistral 自然语言验收 | BGL 稀有异常、HDFS block、空命中、无权限、超过 7 天；最终均符合自动检查 | [natural-acceptance.json](evidence/search-v2/natural-acceptance.json) |
| 历史关联 | 5/5：历史手册、部署 SHA 非 HEAD、无未来手册、其他服务不混用、公开库不混用 | [source-association.json](evidence/search-v2/source-association.json) |
| 回归 | Python 32 项；Go race/vet（含真实独立测试数据库）；前端构建；Helm lint/render | [Python](evidence/search-v2/python-tests.txt)、[Go](evidence/search-v2/go-tests.txt)、[Web](evidence/search-v2/web-build.txt) |
| 浏览器 | Alice 登录 → 中文查询 → 自动完成 → 点击证据引用 → 显示原始记录/时间/hash；测试任务 `b7f60adf-eef8-4c16-8e77-8ed79434905a` | 本次 CUA UI 验证；浏览器使用 America/New_York，故数量不同于 UTC 固定窗口 |

并发实验使用确定性 LangGraph 报告，**不包含模型延迟**。真实 Mistral 调查速度见自然语言 JSON 中的 `elapsed_s`，模型耗时与 Token 在 `model` 和任务 `model_usage` 事件中；不把来源检索耗时当作完整回答耗时。

模型初轮 HDFS 回答曾失败，已保存 [natural-before-budget-fix.json](evidence/search-v2/natural-before-budget-fix.json)。后续收紧输入/输出、校验引用并复测。真实模型仍可能产生被拒绝的引用或无效结构，任务按既有策略重试；实际端到端时间包含这些重试。引用检查仅证明来源 ID 有效，不能替代人工判断推理是否正确。

## 使用与复现

- 四源演示：[localhost:8088](http://localhost:8088/)。Alice：`查一下订单服务最近24小时的超时，核对发布与代码变更`。
- 完整公共日志：[localhost:28088](http://localhost:28088/)。Alice/Bob 查 BGL；Carol 查 HDFS。密码 `demo-password`。
- Alice：`查BGL在2005年11月3日的异常日志`。
- Carol：`查HDFS在2008年11月9日 blk_-1608999687919862906 的日志`。
- Web 日期按浏览器时区；API 可传 `timezone: UTC`，单次最多 7 天。无时间的历史归档使用来源末尾 24 小时；最终执行范围展示在结果顶部。

```sh
# 小规模真实模型（有 API 调用）
BENCH_HARNESS=mistral docker compose -f compose.benchmark.yaml up -d --scale worker=3
uv run --project worker python scripts/search_v2_acceptance.py
# 来源查询；标签只在返回记录之后用于评估
docker compose -f compose.benchmark.yaml exec -T demo python /bench-scripts/search_v2_corpus.py
# 并发性能，排除模型因素；跑完恢复真实模型
BENCH_HARNESS=langgraph docker compose -f compose.benchmark.yaml up -d --scale worker=3 worker
uv run --project worker python scripts/search_v2_load.py
BENCH_HARNESS=mistral docker compose -f compose.benchmark.yaml up -d --scale worker=3 worker
# 历史关联：隔离临时数据库/Git，模拟部署查询，不改实时资料
docker compose -f compose.benchmark.yaml exec -T demo python /bench-scripts/check_source_association.py
```

## 限制与剩余 P0

- 8/8 是固定开发窗口的异常覆盖，不是全日志异常召回率或独立根因准确率。异常级别本身会有假阳性；HDFS 没有在本次验证中提供可比的逐行标签。该数据已用于调优，不进入独立保留集。
- “一句话找到东西”当前覆盖已接入、已授权的研发日志与关联资料；不是任意文件/网站搜索。关键词 OR + FTS 和有限模式抽样不保证任意同义词及每一条稀有事件都召回；超过 10,000 条异常候选时跳过低频模式扫描，保留分层分页。首版不含向量检索。
- 原始日志与索引全量保留，但单份报告最多展示 60 条日志，Mistral 根据 Token 预算读取更小子集。界面统计来自 SQL，不能把模型看到的子集数量当作命中总量。
- 缺少公开库配套来源时为 `partial`，零命中为 `waiting_information`；这两种状态不是权限绕过或伪造完整调查。
- 本次更新已部署 Compose 两个环境。Helm 已同步模型 Secret/网络选项与迁移并渲染校验；没有用旧 Kubernetes 证据声称新版实测通过。
- 全部 P0 仍剩：真实 GitHub 来源/Issue 闭环与远端 CI、独立保留集模型比较/消融和人工质量评分/试用。保留 PRD v1.0 的所有原始门槛。


补充：真实四源订单测试中曾出现模型把已命中日志写成“未检索到”的矛盾回答。现已添加统计一致性保护：保留真实模型调用用量，拒绝展示这类错误摘要，改为 SQL 统计与原始代表证据，页面明确标记纠正原因。该保护不等于通用事实校验；其它推断仍需人工验证。对应负例已加入 Python 回归，主入口结果见 [main-natural.json](evidence/search-v2/main-natural.json)。

已同时修正别名呈现：`checkout-api → svc-17` 的映射由后端/上下文校验，模型输入使用统一服务 ID，避免把合法命中当成其他服务。模型回答与候选的证据 ID 通过 JSON Schema 枚举限制，落库仍复验。校正错误回答时，同步替换其候选与下一步建议，避免保留矛盾推断。

最终小规模真实模型复验：BGL 9.611 秒、HDFS block 9.179 秒、空命中 3.721 秒；权限/跨度澄清通过。主入口四源查询完成，32 项 Python 与 Go race/vet 回归通过。这些数值不是模型生产 SLO。
