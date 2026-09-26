# IncidentDesk Query Service

内部只读问数服务，使用 FastAPI、LangGraph、Mistral、MySQL、Qdrant 和 Elasticsearch。

## 查询流程

关键词提取 → 字段、指标与真实取值召回 → 元数据补齐与筛选 → SQL 生成 → 校验与有限纠错 → 只读执行。

请求由 Go 业务层完成身份和权限检查后提交；服务使用内部密钥，不面向浏览器开放未认证查询。结果包含实际 SQL、字段、行数据与阶段信息。

## 运行与验证

在项目根目录使用 `./scripts/deploy-local.sh`。配置与接口见 [架构和使用](../docs/MERGED_V1.md)，范围见 [能力清单](../docs/CAPABILITIES.md)。

```sh
cd query
uv run python -m unittest discover -s tests -v
```

当前电商演示数据为 115 条订单，日期范围 2025 年第一季度；运行账号只读，SQL 有表白名单、行数和超时限制。

许可证见 [LICENSE](LICENSE)；组件版权与来源记录见 [第三方声明](../THIRD_PARTY_NOTICES.md)。
