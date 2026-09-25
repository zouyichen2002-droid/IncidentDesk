# 公开大规模日志实测

实测日期：2026-09-24。被测应用基线提交：`51779fa13dc861e496726ff17f5592eaf3737288`。结论：完整数据可以入库，调查链路可运行；原始检索在并发下出现超时，且前 50 条截断会漏掉大量异常。仅在独立测试库增加索引后，性能显著改善，异常覆盖不足仍然存在。

## 数据来源与规模

使用 [Loghub 官方仓库](https://github.com/logpai/loghub) / [Zenodo 固定版本 v8](https://zenodo.org/records/8196385) 的完整压缩包，没有复制日志放大条数。

| 数据集 | 实际导入行数 | 原始日志字节数 | 标签 |
|---|---:|---:|---|
| BGL | 4,747,963 | 743,185,031 | 348,460 条告警；其余为非告警 |
| HDFS_v1 | 11,175,629 | 1,577,982,906 | 575,061 个 block：558,223 Normal、16,838 Anomaly |
| 合计 | **15,923,592** | **2,321,167,937（约 2.32 GB）** | HDFS 标签按 block，不按日志行 |

两个压缩包的 MD5 均与 Zenodo 公布值一致，另保存 SHA-256；日志逐行计算原始 SHA-256。完整入库及数据库完整性检查用时 **102.391 秒**，不含下载和压缩包校验。无丢弃行，SQLite `quick_check=ok`。无索引数据库约 4.76 GB，添加索引后约 5.50 GB。导入进程峰值 RSS 约 39.3 MiB，不代表整个系统内存。

数据适配：BGL 的 Unix 秒时间转为 UTC；HDFS 未注明时区，回放时假定 UTC，原始文本保留。没有平移到今天。为适配应用固定映射，BGL 使用 `svc-17 / checkout-api`，HDFS 使用 `svc-23 / payment-api`。BGL 首列告警标签移入独立评测表，不进入日志 payload；HDFS 标签只用于统计，不进入调查上下文。

数据质量：BGL 有 **34,470 行无正文**，以及 **316 行非标准 level 字段**。均原样保留；level 是位置提取，不能把该字段当作经过清洗的分类真值。BGL 告警判定严格使用官方首列标签。详见 [BGL 说明](https://github.com/logpai/loghub/blob/master/BGL/README.md) 和 [HDFS 说明](https://github.com/logpai/loghub/blob/master/HDFS/README.md)。

## 测试方法

独立 Compose 项目 `incidentdesk-public-logs`，独立 PostgreSQL、SQLite 和对象存储 volumes。原工作台 `8088` 的应用和数据未修改。Mac ARM64、10 核、32 GiB 主机；Docker VM 实际约 7.75 GiB。原 Compose 和本机 k3d 同时保留运行，因此这是一轮共享本机实测，不是独占机器或生产 SLA。镜像完整 ID 见 [environment.json](evidence/public-logs/environment.json)。

- 每种数据库配置各测 18 个时间窗口，每窗口直接执行应用实际 SQL 3 次，共 **108 次 SQL 查询**。包含 BGL 9 个日期窗口、HDFS 7 个小时窗口、2 个空窗口。
- 每种配置各测 **18 次串行调查 + 24 次四并发调查**，总计 **84 次真实 API → 持久队列 → Worker → 来源 → 报告调查**。3 个 Worker，每个 3 slots。
- 时间范围略微错开微秒以避免 ContextCache 命中，全部 84 次事件均确认无缓存命中。日志以秒为单位，错开不改变预期第一页。
- 使用现有 LangGraph 确定性报告逻辑，无真实模型调用。模型 token、准确率和成本不在此次测试范围。
- 核对完整第一页的记录 ID、日志时间和数据集范围、证据引用、截断提示、跨团队拒绝、空窗口语义；36 个串行调查额外验证回放导出，并保存完整报告/事件。
- API 每 0.5 秒轮询一次，因此端到端耗时包含轮询误差。SQL 计时为多次查询的混合/热缓存结果，未声称冷磁盘性能；P95 使用 nearest-rank。

## 实测结果

| 指标 | 原始实现：无复合索引 | 测试库索引对照 |
|---|---:|---:|
| SQL 样本数 | 54 | 54 |
| SQL P50 | 447.762 ms | 1.801 ms |
| SQL P95 | 1,888.952 ms | 51.664 ms |
| 串行调查 P95（18 次） | 2.524 s | 0.523 s |
| 四并发调查 P95（24 次） | **12.155 s** | **1.039 s** |
| 四并发日志获取符合预期 | **22/24** | **24/24** |
| 四并发日志读取超时 | **2/24** | **0/24** |
| 上下文缓存命中 | 0 | 0 |

索引为 `logs(service,event_time,id)`，创建和 ANALYZE 合计 8.883 秒，**只加在独立测试库**。原始查询计划只按主键扫描并过滤服务/时间；HDFS 后段以及空窗口需要扫描大量不匹配行。添加索引后，18 个窗口的第一页 ID 和分页游标与原始结果完全一致。

全部 84 次任务都返回终态报告；并非全部完成了有效调查。无索引时有 2 次真实来源 `ReadTimeout`，应用正确显示 `waiting_information` 和日志缺口，没有伪造结果。两个配置各有 2 个预设空窗口也为 `waiting_information`。其余为 `partial`，原因包括日志截断、缺少历史发布记录。

全部跨团队读取均拒绝；返回的日志均未越过数据集/时间范围；证据引用可解析；无日志时缺口明确；有分页时截断明确。无索引的两次超时使“预期第一页一致”检查失败，其余上述检查通过。原始检查把超时也要求显示分页截断，后按保留结果修正为“返回日志页时才检查截断；无日志时检查缺口”，未改动任何实测耗时、状态或数据。

## 发现的问题

1. **日志来源缺少适配服务与时间的索引，且同步 SQLite 查询位于 async HTTP handler 中。** 单次扫描在约 2 秒以内，但四并发时阻塞叠加，超过 HTTPSource 的 3 秒超时；本轮 2/24 调查没有读到日志。索引对照验证了改善方向，尚未修改主应用。
2. **默认只取最早 50 条日志，不继续翻页或筛选异常。** 8 个含异常的 BGL 测试窗口，仅 1 个窗口的第一页包含告警；另 7 个完全漏掉异常。例：2005-11-11 有 16,958 行、1,031 条告警，返回的前 50 条中告警为 0。所选正例窗口共 154,288 条告警，仅 50 条进入第一页。窗口选择包含时间分散点、最高告警量日和最低非零告警比例日，**这不是随机样本的分类准确率，也不是模型根因召回率**。索引没有改变此问题。
3. **确定性报告不具备通用系统故障诊断能力。** 18 个串行历史窗口均无根因候选。现有规则针对演示连接池、超时、配置关键词，不能据此宣称能诊断 BGL 硬件或 HDFS block 故障。
4. **演示 Git/runbook 与公开历史日志没有真实关联。** 18 个串行报告仍包含当前本地 fixture 的 Git 与运行手册，缺少相应历史部署资料。它们只是运行链路的接口桩，不是 BGL/HDFS 的真实关联证据；当前输出未充分区分这种资料来源。不能用这轮数据验收真实四源因果分析。

优先改进顺序：日志来源索引与非阻塞查询 → 服务/时间范围内的异常过滤、聚合、分层抽样与预算内分页 → 来源真实性和历史关联校验 → 接入真实模型后设计独立的质量评测。HDFS 的 block 标签需要先构建 block trace，不能套用逐行异常评分。

## 查看与复现

[测试工作台](http://localhost:28088/)：Alice 查看 BGL，Carol 查看 HDFS，密码均为 `demo-password`。调查标题以 `[Loghub ...]` 开头；直接打开已有历史调查。页面“最近 24 小时”是当前时间，不能覆盖这些 2005/2008 年日志；本次历史时间窗通过 API 提交。

首次从空测试 volumes 运行（当前机器已完成导入，不要再次导入同一库）：

```sh
# 如镜像尚不存在，先按项目 README 构建四个应用镜像。
docker compose -f compose.benchmark.yaml up -d postgres demo api objects web
# 自动下载两个固定版本压缩包、校验、流式导入；拒绝追加到非空日志库。
docker compose -f compose.benchmark.yaml exec -T demo python /bench-scripts/public_log_benchmark.py prepare
docker compose -f compose.benchmark.yaml exec -T demo python /bench-scripts/public_log_benchmark.py source
docker compose -f compose.benchmark.yaml up -d --scale worker=3 worker
uv run --project worker python scripts/public_log_investigations.py
```

原始测试完成后，只在测试库中执行索引对照：

```sh
mkdir -p docs/evidence/public-logs/indexed
cp docs/evidence/public-logs/ingestion.json docs/evidence/public-logs/indexed/ingestion.json
docker compose -f compose.benchmark.yaml exec -T demo python - <<'PY'
import sqlite3
with sqlite3.connect('/data/demo.sqlite') as c:
    c.execute('CREATE INDEX benchmark_logs_service_time_id ON logs(service,event_time,id)')
    c.execute('ANALYZE logs')
PY
docker compose -f compose.benchmark.yaml exec -T demo python /bench-scripts/public_log_benchmark.py source --evidence /evidence/indexed
uv run --project worker python scripts/public_log_investigations.py --evidence docs/evidence/public-logs/indexed --serial-offset 10000
```

当前测试库已经有该索引，直接再跑是“有索引”条件，不能冒充原始基线。再次测量前请把 `docs/evidence/public-logs` 结果复制到新的运行目录；脚本会写同名文件。停止测试实例并保留数据：`docker compose -f compose.benchmark.yaml down`。重新打开：`docker compose -f compose.benchmark.yaml up -d --scale worker=3`。

下载包在 `.local/public-log-benchmark/downloads`，原始大文件不进入 Git。数据使用条款和论文引用保留于下载目录与 [LOGHUB_LICENSE.txt](evidence/public-logs/LOGHUB_LICENSE.txt)。

可检查证据：[汇总](evidence/public-logs/summary.json)、[完整导入](evidence/public-logs/ingestion.json)、[原始 SQL](evidence/public-logs/source.json)、[原始调查](evidence/public-logs/investigations.json)、[索引后 SQL](evidence/public-logs/indexed/source.json)、[索引后调查](evidence/public-logs/indexed/investigations.json)、[异常覆盖](evidence/public-logs/coverage.json)、[来源质量限制](evidence/public-logs/quality-limitations.json)。
