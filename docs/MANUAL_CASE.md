# 可复核的手工调查样例

来源为本机自建演示服务与无敏感数据的测试仓库。`scripts/demo_faults.py` 注入 `pool_exhaustion`：持有唯一 semaphore 槽位，业务请求实际等待并超时；SQLite 记录错误类、服务、发布标签与时间。不是只打印一条预设 ERROR。

1. 以 Alice 调查 svc-17 最近24小时，读取日志中的 pool exhausted、pool active/max 与对应时间。定位器、采集时间、版本/hash 保存到报告 Evidence。
2. 对照结构化 deployments 的版本和 commit_sha。Git 读取真实提交与配置变更，运行手册提供明确标记的演示排查步骤。
3. commit 相等只能证明发布对应的代码变更；日志与发布版本冲突必须保留，不能用时间接近直接证明因果。
4. 候选解释为池耗尽导致等待；还需活跃连接、池上限与等待时间证据。输出下一步检查，不宣称已确定应用根因。
5. 修改草稿后由 approver 批准版本；未审批、Bob（investigator）、旧版本或来源已变化的批准均拒绝。成功必须读取原 Issue；响应丢失则按 marker 核对。

实际记录：[核心调查与审批](evidence/smoke.json)、[录制快照](evidence/recording.json)、[故障运行输出](evidence/demo-faults.json)。这是可人工复查的演示，不是独立真人质量评分。

| 身份 | 订单调查/证据 | 支付调查/证据 | 订单批准 | 配置管理 |
|---|---|---|---|---|
| Alice | 是 | 否 | 是 | 否 |
| Bob | 是 | 否 | 否 | 否 |
| Carol | 否 | 是 | 否 | 否 |
| Admin | 无隐式权限 | 无隐式权限 | 否 | 是 |
