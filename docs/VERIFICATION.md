# 本地验收报告 — 2026-09-24

代码、部署和证据已落盘。外部模型、真实 GitHub 与人工质量评分尚未验收，因此不声明全部 P0 完成。逐项对应见 [ACCEPTANCE.md](ACCEPTANCE.md)。

## 环境与复现

macOS 15.6 / arm64，10 logical CPUs、32 GiB RAM；Docker Desktop 29.6.1；Go 1.27.1、Node 24.18.0；Python 3.12 镜像，uv 本机 0.11.26 / 镜像 0.10.12；k3d 5.9.0、k3s v1.34.1、Helm 4.3.0。版本和完整配置见 evidence/toolchain.txt、docker-environment.json、kubernetes-version.json、helm-render.yaml 及锁文件。

Compose：3 Worker × 3 slots；K8s：API 2–4 副本、Worker 1/3 对比，持久 Postgres/S3。全局运行上限 10、租约 15 秒、心跳 3 秒。生成的演示故障包含实际 semaphore 等待超时、HTTP 依赖超时、错误配置、探针重启和内存 OOM；固定评估 fixtures 与实际故障实验分别记录。

## 实测结果

| 实验 | 结果 | 原始证据 |
|---|---|---|
| 核心闭环、并发审批、丢响应核对 | 本地 Issue 桩闭环通过 | smoke.json |
| Go race detector | 100 并发领取仅 10 个有效租约；代次/重复回调/审批失效/权限撤销；goroutine 3→3 | go-tests.txt |
| Python | 20 测试通过，含真实 MCP SDK、录制模型 Deep Agents、Ontology/预算/Hook | python-tests.txt |
| 20 RPS × 600 秒 | 12,000 请求；6,000 列表 + 6,000 创建；p50 5.62 ms、p95 9.71 ms、最大 131.76 ms；0 非成功请求 | load.json |
| 100 个延迟任务 | 100 completed；采样峰值 9 ≤ 全局上限 10 | k8s-reliability.json |
| 1 Worker / 30 任务 | 31.83 秒，0.942 tasks/s，平均排队 16.01 秒 | k8s-reliability.json |
| 3 Worker / 30 任务 | 10.34 秒，2.901 tasks/s，平均排队 3.03 秒 | k8s-reliability.json |
| 恢复矩阵 | 提交后/领取后/待审批/丢响应后终止Worker，唯一原Issue核对成功 | recovery-matrix.json |
| 租约接管 | 暂停原进程，新 Worker 以 generation 2 接管；恢复旧进程，唯一最终结果 | lease-takeover.json |
| SSE 跨 API 副本 | 断线游标 5 后切换副本，完整重建 35 事件且无重复 | k8s-sse.json |
| HPA | 实际负载下 2→4，撤载后→2 | k8s-hpa.json |
| K8s 故障 | 探针失败导致重启；64 MiB 限制下申请 256 MiB 实际 OOMKilled | k8s-demo-faults.json |
| 网络/RBAC | 未授权 Pod 网络请求拒绝，可信应用请求成功；跨命名空间/secret 权限拒绝 | k8s-network.json |
| 沙箱/MCP/S3 串联 | 固定 Job、MCP schema 发现与调用、S3 hash 记录成功 | gateway-integration.json、artifacts.json |
| 沙箱负向 | 写只读挂载、禁网、内存限制、超时均正确拒绝/终止 | sandbox.json |
| 普通 Context API | 实际 5 来源；无服务身份 401、跨服务 403、取消租约 409 | context-api.json |
| 生命周期/权限 | 修改、删除、索引 tombstone、缓存失效、记忆过期；有效 JWT 下撤权立即拒绝 | source-lifecycle.json、security-regression.json |
| 保留清理 | 新建测试样例模拟31天龄，报告脱敏、checkpoint与S3对象清理通过 | retention.json |
| 监控与游标 | Prometheus实际up、Grafana4面板存在、异常游标snapshot重载 | operational-checks.json |
| OIDC/DB 边界 | 过期/错 issuer/错 audience 401；Worker 无 business 权限及 GitHub token | oidc.json、db-boundary.json |
| 备份/独立恢复 | 1.75 秒；843 调查、2 actions、2 approvals、19,019 events；孤立 action 0 | backup.json |
| 离线回归 | 24 变体：12 开发 + 12 保留×3，共 48/48 规则通过；预置退化被门禁阻止 | evaluation.json |

表中证据均位于 [evidence](evidence/)。备份计数来自当时一致快照，不是最终数据库计数；RPO 为快照后的写入排除，未声称零丢失。评估延迟是离线确定性计算时间，模型 Token/费用为零仅表示没有模型调用。

## 失败、修复与瓶颈

第一次完整负载测试未通过：12,000 请求中 655 次队列配额拒绝、77 次开发重启造成连接错误，总非成功率 6.1%。保留 [原结果](evidence/load-first.json)，没有剔除 429 后冒充通过。单 Worker 的 3 slots 吞吐不能持续承接创建速率；改为 3 Worker 的 9 slots 并在稳定构建上重新运行 10 分钟，达到上表结果。

20 秒 pprof 共 1.72 秒 CPU 样本，syscall 占 40.7%、futex 占 13.37%；没有足够证据认定某个业务函数是 CPU 热点。列表 SQL 在 2,975 条团队数据上使用索引，只需约 0.056 ms。结合队列和扩容实验，本阶段主要限制在 Worker slots、顺序工具 I/O 和固定延迟；不能把增加 slots 的收益归因于 Go CPU 优化。原始 pprof、查询计划和 goroutine 记录随仓库交付。

实际排错还包括：S3 并发初始化 BucketAlreadyExists、跨代 checkpoint 缺失 namespace、旧水位 checkpoint 重用、K3d 导入 Docker provenance 引用缺失、唯一 Worker 被暂停后无接管者、集群录制数据超过旧32KiB回调上限、Compose Web启动先于API DNS就绪。修复后分别复验并保存结果；没有把初始失败脚本算成通过。

## 质量与实验解释

规则评估检查事实/候选数量、引用、冲突、缺口和无写入；不替代人工“调查有效”定义。保留样本虽然重复 3 次，确定性输出不构成模型随机波动实验。当前人工评分数为 0，不能声称有效率 ≥80%。

ablation.json 实际是固定数据的模块扰动检查：未映射别名与无证据候选可被拒绝；固定计划且无已审核记忆的 fixtures 无法测出动态规划和记忆收益。真正的相同模型/预算消融、真实模型成本/端到端时延，需在提供配置后运行。Badcase 标签接口与退化回归门禁已实现；独立人工归类/试用尚缺参与条件。

远端 CI 未运行；本地构建、race、Python、npm audit、Helm lint 和集成结果独立保存，不将配置文件存在等同 CI 成功。

浏览器复验：在已完成调查页面接收 source_invalidated 后，旧事实/候选清除，证据数从12变0并显示过期提示；来源变化也清空待编辑草稿缓存。

最终部署：核心镜像0.7.0、Web0.7.1，Helm记录webImageTag覆盖；Compose同源镜像已更新。Docker VM实分配约7.75GiB，主机32GiB。deployment.json记录各副本就绪与镜像内代码提交；最后的文档/Chart提交不改变该历史镜像提交标识。
