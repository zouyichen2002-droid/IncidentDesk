# 掌柜问数完整能力对照与学习记录

核查日期：2026-09-25。范围为本任务一直参考的「掌柜问数 / 电商问数」项目；其他课程项目（归因分析、营销、医疗、通用助手等）单独归类，不自动视作同一个项目。本文件区分来源介绍、读到的实现、我们的实现与测试证据。阅读源码和完成能力对照，不等于所有功能已实现。

## 1. 先纠正参考基线

我们此前合入的是 didilili 整理的教学实现，不能称为尚硅谷官方完整源码。当前官方页面介绍的能力比该教学实现更广。以后用以下三个层次共同对照：

| 层次 | 核查来源 | 用途与限制 |
|---|---|---|
| 尚硅谷当前项目介绍 | [官网 Agent 课程页](https://www.atguigu.com/agent/)，点击“掌柜问数” | 定义公开介绍的目标能力；网页有六项特性及架构图，不是官方源码或验收报告 |
| 可运行教学实现及18章教程 | [shopkeeper-agent](https://github.com/didilili/shopkeeper-agent/tree/8045fa4d61608f58df551fda6cd1a70529bb5b67)；[电商问数教程](https://github.com/didilili/ai-agents-from-zero/tree/ea7f28ffe0b2c2650e3936f3bb591560225702b3/实战项目-电商问数) | 教学代码来源为 didilili，MIT；已合入 `query/`，保留许可证及来源。核查时其远端HEAD仍为该提交 |
| 官网提及的京东开源架构 | [JoyDataAgent README](https://github.com/jd-opensource/joyagent-jdgenie/blob/2417e0b8b636d941ad5fb14c59b20dddfef5375d/README_DataAgent.md)；[NL2SQL](https://github.com/jd-opensource/joyagent-jdgenie/blob/2417e0b8b636d941ad5fb14c59b20dddfef5375d/genie-tool/genie_tool/tool/nl2sql.py)；[TableRAG](https://github.com/jd-opensource/joyagent-jdgenie/tree/2417e0b8b636d941ad5fb14c59b20dddfef5375d/genie-tool/genie_tool/tool/table_rag) | 核查了查询改写、独立生成前分析、并发召回、排序、两阶段过滤的代码；不等于拿到了尚硅谷对它的定制源码。没有移植整套京东平台，也不继承其性能或榜单成绩 |

资料保存在忽略目录 `.local/atguigu-tutorial`、`.local/jd-data-agent` 供本机复查。正式文档以固定提交链接为准，不依赖这些临时副本。没有观看全套视频、没有获取私有课件，不能宣称已验证未公开的全部课程内容。

官网 `ai/` 页还把问数与 AttributionAgent 组合成“智数归因平台”。它是更宽的组合项目，不能据此声称当前115条订单已经支持营销归因。

## 2. 官方公开能力逐项核查

| 官网描述的能力 | 学到的实现方法 | 当前项目状态 | 验收/缺口 |
|---|---|---|---|
| 京东 DataAgent 架构 | TableRAG 与 NL2SQL 分层；数据治理在问数之前 | **参考设计，未整体移植京东内核** | 保留当前Go权限/队列与Python查询层；不声称具有京东生产规模稳定性 |
| 重写—思考—生成 | JD `run` 并发执行 rewrite 与字段筛选，再进入分析和SQL生成 | **部分实现**：已有追问改写、检索扩词、SQL生成/纠错；没有独立结构化查询计划节点 | 后续应补指标、过滤、分组、排序、关联的可检查计划；不能把现有12个节点改个名字当作完成三阶段 |
| 混合多路召回 | 字段/指标走向量库，实际值走ES，按字段ID补齐上下文 | **已实现教学规模主链路** | 新增品牌、品类、会员测试；本次对同一路不同检索词采用RRF排序。尚未做跨Qdrant/ES统一字段评分，也无千表规模证据 |
| 动态Schema剪枝 | 模型选择已有表/字段；JD在大Schema时先粗筛表再逐表筛列 | **部分实现**：有字段裁剪、指标筛选、主外键保护 | 目前仅5表；缺少大Schema两阶段筛选、召回率与上下文预算的联合评测 |
| 异步并发 | 各路独立运行；检索请求有并发上限；失败结束后释放剩余请求 | **已实现有限并发**：三路并行、双过滤并行、后台任务2并发；本次增加批量Embedding及每路4并发检索 | 单次每路最多24检索词、检索30秒超时；不是高并发压测结论。rewrite与ranking独立并行尚未实现 |
| Jieba与HyDE语义对齐 | 先词法切分，再生成可能的字段/取值描述作为召回线索，最终约束必须回到真实元数据 | **Jieba和语义扩词已实现；完整HyDE未验收** | 当前prompt生成假设字段概念，与HyDE方向相似，但没有独立假设文档、开关及消融测试，不能等同宣称完整HyDE |

技术选型按能力迁移：继续使用用户指定的 Mistral。现有模型适配器承担模型调用，未安装LiteLLM；没有为了技术栈名称一致而替换可用组件。浏览器用React，Python到Go采用SSE，Go持久化进度后浏览器轮询；用户能看到阶段进度，但这不是浏览器直连Python的SSE协议复刻。

## 3. 教学版18章全部纳入对照

“已覆盖”指相应核心实现可在当前项目定位；测试范围另列。环境、配置章节不是用户功能数量，不以18/18冒充全产品完成率。

| 章 | 要学习的能力 | 当前实现位置 | 对照结论 |
|---|---|---|---|
| 0 前言 | 问数闭环、教学与生产边界 | 本文、`query/README.md` | 已区分；课程不自带完整生产治理 |
| 1 数仓 | 事实表粒度、维度、指标与口径 | `query/docker/mysql/dw.sql`、`query/conf/meta_config.yaml` | 5表、24字段、GMV/AOV；115条订单。数量不代表大数据测试 |
| 2 架构 | 结构化元数据、向量、取值索引的分工 | `query/app/agent/graph.py`、repositories/services | 三路召回与12节点闭环已保留 |
| 3 环境 | Compose、uv、基础服务准备 | 根`compose.yaml`、`query/Dockerfile`、`query/uv.lock` | MySQL/Qdrant/ES已集成；Embedding换成Mistral，Kibana非必需未部署 |
| 4 配置 | YAML/OmegaConf/dataclass分层 | `query/app/conf/` | 已覆盖，敏感值来自环境变量 |
| 5 检索接入 | Qdrant/ES异步客户端 | `query/app/clients/`、`repositories/qdrant/`、`repositories/es/` | 已覆盖；不向浏览器公开客户端 |
| 6 MySQL/Embedding/日志 | 异步会话、向量生成、日志上下文 | `clients/`、`core/log.py`、`core/context.py` | 已覆盖；本次打通Go查询ID到Python日志 |
| 7 元数据入口 | 配置驱动知识构建、构建职责分层 | `app/scripts/build_meta_knowledge.py`、`initialize.py` | 初始构建可用；重复启动跳过，不清空用户数据。增量更新/版本切换仍缺 |
| 8 表/字段同步 | 类型/样例读取，实体/ORM/Mapper/事务 | `app/services/meta_knowledge_service.py`、`models/`、`repositories/mysql/meta/` | 已覆盖；不把教学全量构建脚本当作生产迁移工具 |
| 9 字段/指标/值索引 | 字段别名向量、指标依赖、真实枚举值同步 | 同上及Qdrant/ES仓储 | 已覆盖；需要受控的索引更新与失效处理才能扩展数据集 |
| 10 工作流 | State与运行Context分离，图状态更新 | `agent/state.py`、`context.py`、`graph.py` | 已覆盖 |
| 11 抽词和召回 | Jieba、模型扩词、三路并行 | `agent/nodes/extract_keywords.py`、`recall_*.py` | 已覆盖；本次补批量向量化、有界并发、稳定排序 |
| 12 合并 | 指标依赖列、真实值、主外键补齐 | `agent/nodes/merge_retrieved_info.py` | 已覆盖；只从真实元数据补齐，不把扩词当作真实列 |
| 13 过滤/补全 | 裁剪表/列、指标，补时间和DB方言 | `filter_table.py`、`filter_metric.py`、`add_extra_context.py` | 已覆盖小Schema；保留关联键及日期字段，防止剪掉必需信息 |
| 14 SQL闭环 | 生成、EXPLAIN、错误修正、执行 | `generate_sql.py`、`validate_sql.py`、`correct_sql.py`、`run_sql.py` | 已覆盖；额外只读检查/白名单/时间/指标/关联规则。只允许一次纠错，不承诺任意SQL语义正确 |
| 15 API/SSE | POST接口、流式响应与终态错误 | `api/routers/query_router.py`、`services/query_service.py` | 已覆盖；internal key保护。流已开始后通过error事件传递失败 |
| 16 依赖/生命周期 | 请求级Session、复用客户端、资源释放 | `api/dependencies.py`、`lifespan.py` | 已保留；测试服务重建后查询可用 |
| 17 前端/追踪 | 进度/结果/错误、request_id | `web/src/QueryWorkbench.tsx`、Go `data_queries.go`、Python `main.py` | 已覆盖并集成权限和历史；新增排错编号、阶段耗时、并发上下文隔离测试 |

## 4. 本次落地的改进

### 检索请求与排序

原先每个词分别请求Embedding，再依次检索，结果按集合遍历和首次命中顺序合并。现在每路先批量Embedding、最多4个并发检索，按不同检索词返回的名次做RRF融合；同一个字段的多个别名向量在同一列表只算一次贡献。相同分数按ID稳定排序。原问题始终作为第一个检索入口。

没有在这一步硬截断候选字段；后续仍执行真实指标依赖和主外键补齐以及模型筛选。检索失败会取消本次剩余请求，避免后台继续占用连接。单元测试验证并发峰值、取消收敛、去重、排序及不完整Embedding响应；正确率与性能提升需要更大评测，不能仅凭实现推断。

### 查询记录与日志关联

Go使用持久查询UUID作为`X-Request-ID`，Python校验UUID格式后写入上下文、返回头以及每个SSE事件。进度带累计耗时和阶段耗时，成功结果及错误带同一编号。非法编号重新生成，并在请求结束时恢复上下文，避免并发请求串号。

页面结果的SQL与来源详情显示排错编号，阶段标签悬停可看耗时。重试共用查询编号，具体重试次数仍看查询记录的attempts。此前保存的旧记录没有阶段计时，页面仍兼容。

## 5. 尚未完成的能力，按依赖顺序推进

| 工作项 | 要交付的结果 | 完成标准 | 来源属性 |
|---|---|---|---|
| A 查询规划 | 独立、结构化的查询计划，保留时间/指标/筛选/分组/排序/输出要求，接SQL生成与校验 | 缺成本不能推算毛利；复合查询、追问保留约束；计划与SQL不一致不得静默返回 | 官网三阶段能力的本项目实现方案 |
| B 检索升级 | HyDE开关、跨来源字段排序、大Schema先选表再筛列 | 在有无扩展/排序/剪枝下比较字段召回率、SQL正确率、耗时和成本；不只测5表 | 官网HyDE/Schema Ranking/剪枝能力 |
| C 元数据更新 | 数据集版本、增量同步、可验证构建、索引切换与恢复 | 新字段/指标可用，旧字段删除不继续召回，构建失败保留上个可用版本 | 教学构建流程的生产扩展，并非声称课程自带 |
| D 数据规模验收 | 较大业务数据和复杂Schema的独立标准答案集 | 记录数据来源/时间/规模、正确率、P95、超时、并发和资源；与15,923,592条日志测试分开 | 本任务已有的大数据测试要求 |
| E 完整会话与交付（部分完成） | [持久会话、可恢复追问已交付](CONVERSATION_MEMORY.md)；查询取消/导出/图表待做 | 不依赖当前页面短期历史；重新登录/刷新后权限和上下文正确 | 我们的产品扩展；不能混算为教学版已有能力 |

学习结论：可复用的是整个问数流程、检索与治理设计，而不是不断给某个词加特殊判断。后续功能统一走上表和PRD验收。网站营销描述中的“企业级”“高并发”“复杂问题准确性”必须由本项目实测支持，不能直接继承。

## 6. 测试与复现

本轮完整跑完 **46/46** 个场景，另有3项链路/数据保全检查通过；查询服务 **21项单元测试**、Go race/vet、Compose镜像构建均通过。页面人工核对“苹果品牌商品件数”为8，阶段耗时、实际SQL及排错编号均正常显示。结果见 [汇总](evidence/atguigu-capabilities/summary.json)。

29个问数场景（包含路由和轮询）耗时3.66–6.24秒，中位数4.68秒；只是一轮本机观测，未进行同条件前后对比，不宣称性能提升比例。

原始证据位于 `evidence/atguigu-capabilities/`。`acceptance.json`保留46个业务/对话/参数测试的实际响应和独立标准SQL；`trace-checks.json`单独记录进度完整性、日志关联与元数据数量。首次失败也保留，不能把目标数写成通过数。

```sh
(cd query && uv run python -m unittest discover -s tests -v)
./scripts/test-go.sh
uv run --project worker python scripts/atguigu_capability_acceptance.py
```

运行时使用本机已授权的Mistral配置，不在报告保存token或API key。不重新导入`dw.sql`，不删除数据卷。
