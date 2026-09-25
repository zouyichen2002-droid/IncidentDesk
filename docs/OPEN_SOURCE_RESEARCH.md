# 企业查询 Agent 开源底座调研（含小红书核验）

> 最新决定（2026-09-24）：用户选择基于 didilili/shopkeeper-agent 直接修改，已完成本地 Mistral 问数试用版。当前实施与验收以 [NL2SQL_V1.md](NL2SQL_V1.md) 为准；下文保留选型过程，原优先级不再是当前实施顺序。

核验日期：2026-09-24。当前任务先研究现成项目，再决定扩展方式；尚未替换或修改 IncidentDesk 的应用代码。

## 日期条件与完成范围

“7月之后发布”按2026年7月之后的小红书帖子筛选。用户登录后，已在站内使用原词“开源企业级数据查询agent项目”找到并打开以下三篇。网页只显示月日，年份按当前会话2026年理解；这是帖子日期筛选，不是项目首次开源日期筛选。正文与 GitHub 独立核对，没有点赞、收藏或发评论。

## 小红书核验结果与更新后的优先级

| 帖子（原文链接） | 页面日期 / 作者 | 对应 GitHub | 选型用途 |
|---|---|---|---|
| [阿里开源UnifiedModel：让Agent读懂企业数据](https://www.xiaohongshu.com/explore/6aa6c2de0000000012025782) | 09-13 / Annn | [alibaba/UnifiedModel](https://github.com/alibaba/UnifiedModel) | 当前服务、配置、发布、日志、Runbook 场景的首选概念验证底座 |
| [开源项目Utopia：不会失忆的知识底座](https://www.xiaohongshu.com/explore/6a98bd7a000000002a025ba1) | 详情09-02、搜索卡09-03 / Levi AI | [deeplethe/utopia](https://github.com/deeplethe/utopia) | 学习文档接入、历史事实、来源追踪、人工复核；时间差不影响7月之后的筛选 |
| [给企业Agent做一次多数据源查询上岗考试](https://www.xiaohongshu.com/explore/6a8827c3000000002202cb9b) | 08-21 / PKU-DCAI | [haolpku/WorkSurface-Bench](https://github.com/haolpku/WorkSurface-Bench) | 评测框架，不是完整产品底座；用来检验工具选择、证据和回答 |

小红书使用笔记公开标识链接，打开可能仍需登录。UnifiedModel、Utopia 的仓库通过项目名、定位和技术内容交叉匹配；WorkSurface-Bench 帖子直接给出了仓库名。

**更新判断：当前项目优先做 UnifiedModel 概念验证，Onyx 保留为文档检索产品候选，Utopia 作为知识治理参考，WorkSurface-Bench 作为评测参考。** 这取代上一轮仅查 GitHub 时“先验证 Onyx”的暂定顺序。理由是 UnifiedModel 已有与 IncidentDesk 场景直接匹配的模型包和故障排查示例，而不只是一般文档聊天能力。仍未部署或实测这些底座，不能声称已达到企业生产可用。

### UnifiedModel：最贴合现有领域，但不是一键替代成品

已读版本：`1b54ddc4dd89ae2b0255da095d00d01e46d687b5`；Apache-2.0。GitHub 仓库创建时间2026-05-06，因此**不满足“项目必须7月之后首次创建”的另一种解释**，但帖子满足当前筛选。

已核对：

- [AgentGateway 实现](https://github.com/alibaba/UnifiedModel/blob/1b54ddc4dd89ae2b0255da095d00d01e46d687b5/internal/agentgateway/service.go)：发现工具、执行/解释 SPL、读取资源；写工具由显式开关控制。
- [外部存储查询计划接口](https://github.com/alibaba/UnifiedModel/blob/1b54ddc4dd89ae2b0255da095d00d01e46d687b5/internal/query/planrender/planrender.go)：日志/指标方法生成存储查询计划，渲染器不执行外部存储 I/O。不能把示例“拉日志”理解为已经支持任意数据库连接和执行。
- [故障排查示例](https://github.com/alibaba/UnifiedModel/blob/1b54ddc4dd89ae2b0255da095d00d01e46d687b5/examples/incident-investigation/README.zh-CN.md)：包含配置、服务、部署、跨域关系和 Runbook；是受控演示，不是生产准确率证据。
- [服务定位示例](https://github.com/alibaba/UnifiedModel/blob/1b54ddc4dd89ae2b0255da095d00d01e46d687b5/examples/service-localization/README.zh-CN.md)：沿 API→服务→数据库→基础设施定位连接池瓶颈，与当前问题接近。
- [公开核心范围](https://github.com/alibaba/UnifiedModel/blob/main/README.md)：不含云控制面和多租户授权，不能把 workspace 字段直接当作完善的权限隔离。

具体扩展方向：先定义 Service、ConfigFile、Deployment、Runbook 与它们的关系；ConfigFile 保留真实路径、仓库、commit 和内容摘要。复用 UModel 对象查询和关系查询，接入现有的受限日志执行器；在现有 Go 服务中保留认证、授权、预算和审计。Mistral 负责选择查询工具及组织说明，文件路径从对象结果取得。自然语言对话、Mistral 工具适配、结果卡片仍需实现和验收。

### Utopia：有价值的历史知识设计，当前仍处早期

已读版本：`8857be5bd316b9592e197d8bf873854bd46ceec4`，默认分支 `dev`；Apache-2.0；仓库创建于2026-08-07。

[中文 README](https://github.com/deeplethe/utopia/blob/8857be5bd316b9592e197d8bf873854bd46ceec4/README.zh-CN.md) 明确仍是 v0.1，数据库迁移只前滚。它适合学习双时态、事实来源、冲突处理和人工审核，现阶段不直接作为当前项目的全部基础。

[MCP 实现](https://github.com/deeplethe/utopia/blob/8857be5bd316b9592e197d8bf873854bd46ceec4/crates/utopia-server/src/api/mcp.rs) 对搜索、读文档、事实、邻居、时间线等工具有明确白名单；权限同时约束 token 范围和知识库角色；`remember` 需写权限。**`query_data` 未对 MCP 暴露**，因此小红书“能查挂载数据库、通过 MCP 暴露只读工具”的描述不能推导出外部 Agent 可经 MCP 任意查数据库。已读代码支持这一限制。

### WorkSurface-Bench：补齐验收设计，不只判断接口通了

已读版本：`3189f3307f62b5efee3b77cce550f1686ad56aa1`；Apache-2.0；仓库创建于2026-07-08。官方说明提供1,151条任务，将 RAG、Table、Graph 选择、证据获取、回答正确性和效率分开评估。本轮未运行其完整基准。

[route_evidence.py](https://github.com/haolpku/WorkSurface-Bench/blob/3189f3307f62b5efee3b77cce550f1686ad56aa1/scoring/route_evidence.py) 明确分离路由分数和证据分数。[answer.py](https://github.com/haolpku/WorkSurface-Bench/blob/3189f3307f62b5efee3b77cce550f1686ad56aa1/scoring/answer.py) 独立评分答案。注意默认 RAG evidence scorer 在缺少文件标注时较宽松，引用命中文档也不能自动证明每句话成立；我们仍要增加路径/字段精确校验以及错误候选检测。

对当前失败样例，应分别验收：选配置工具、找到真实 config.json、回答真实路径、禁止用连接池错误日志支持虚构的 application.yml 路径、首屏呈现答案、完成任务不能取消。不能只看HTTP成功和引用ID存在。

## 第一轮 GitHub 独立候选（不是已核验小红书来源）

下面日期是 GitHub release 发布时间，**不是小红书帖子发布日期，也不是项目首次开源日期**。已核对官方 README、许可证、仓库 API 与部分核心代码；没有部署或跑项目测试，稳定性和 Mistral 适配仍需实测。

## 候选比较

| 项目 | 已核验近期发布 | 用途与判断 | 开源范围 |
|---|---|---|---|
| [Onyx](https://github.com/onyx-dot-app/onyx) | [v4.8.1，2026-09-24](https://github.com/onyx-dot-app/onyx/releases/tag/v4.8.1) | 最贴近一句话找企业资料；有检索、文档来源、引用和现成界面。建议优先作为资料搜索底座做验证 | CE 为 MIT；ee 目录另用企业许可证，不能把企业权限同步当成 MIT 功能 |
| [SQLBot](https://github.com/dataease/SQLBot) | [v1.10.2，2026-09-23](https://github.com/dataease/SQLBot/releases/tag/v1.10.2) | 更贴近一句话查数据库、数据分析和图表；如果目标改为 ChatBI，这是优先体验对象 | 修改版 GPLv3，附前端 LOGO 和版权信息保留条件 |
| [Datus Agent](https://github.com/Datus-ai/Datus-agent) | [v0.4.0，2026-08-27](https://github.com/Datus-ai/Datus-agent/releases/tag/v0.4.0) | 适合研究可扩展的数据 Agent：先检索业务上下文、指标和参考 SQL，再执行数据任务；不是现成的配置文件搜索产品 | 仓库 LICENSE 为 Apache-2.0；团队版权限/SSO不能只凭官网宣传推定在开源内核中 |
| [WrenAI](https://github.com/Canner/WrenAI) | [wren-v0.15.0，2026-09-21](https://github.com/Canner/WrenAI/releases/tag/wren-v0.15.0) | 适合学习受语义层约束的查询：指标定义、关联、单位与示例进入受版本管理的上下文；当前主分支定位为引擎/SDK/CLI，不应按旧教程当成完整聊天界面 | README 标注核心、SDK、skills 为 Apache-2.0，采用前按实际使用目录核对 |

许可证来源：[Onyx](https://github.com/onyx-dot-app/onyx/blob/main/LICENSE)、[SQLBot](https://github.com/dataease/SQLBot/blob/main/LICENSE)、[Datus](https://github.com/Datus-ai/Datus-agent/blob/main/LICENSE)。[WrenAI 当前定位](https://github.com/Canner/WrenAI/blob/main/README.md)。

## 已读代码与学到的设计

### Onyx：检索和引用是一套独立的产品能力

固定阅读版本 `0c6a8e3bcf8c9f6ec967da649ef604aa38e60381`。

- [search_tool.py](https://github.com/onyx-dot-app/onyx/blob/0c6a8e3bcf8c9f6ec967da649ef604aa38e60381/backend/onyx/tools/tool_implementations/search/search_tool.py)：来源、时间、访问过滤进入检索流程；不是取几条日志后让模型自由补全。
- [citation_processor.py](https://github.com/onyx-dot-app/onyx/blob/0c6a8e3bcf8c9f6ec967da649ef604aa38e60381/backend/onyx/chat/citation_processor.py)：模型流中的引用标号映射到检索文档并形成链接。它解决引用呈现，不等于自动证明每句话语义正确。
- [GitHub connector](https://github.com/onyx-dot-app/onyx/blob/0c6a8e3bcf8c9f6ec967da649ef604aa38e60381/backend/onyx/connectors/github/connector.py#L73)：白名单以 Markdown、文本等文档为主，明确排除 JSON、YAML、SQL、日志和代码。直接部署不能保证找到 config.json。
- GitHub 等外部权限同步代码位于 `backend/ee/onyx/external_permissions/`，需要与 CE 的功能范围分开评估。

可扩展点：新增配置文件读取/索引适配器，保留仓库、文件路径、commit、服务归属；先展示可核验的文件结果卡片，再按需生成说明。大体量日志保留专门的结构化查询通道，不把1592万条原始日志全部当作普通文档塞进索引。

### SQLBot：数据源选择、选表、生成和执行各有入口

固定阅读版本 `e02f7175e50bd60a4976dd9c267befb02ec944d5`。

[backend/apps/chat/task/llm.py](https://github.com/dataease/SQLBot/blob/e02f7175e50bd60a4976dd9c267befb02ec944d5/backend/apps/chat/task/llm.py) 中存在 `select_datasource`、`choose_table_schema`、术语及训练示例筛选、`generate_sql`、`check_sql`、行权限过滤等步骤。适合学习数据库问数流程；代码中存在检查步骤不代表已证明所有权限和 SQL 安全边界正确，本次没有进行安全审计。

可扩展点：将订单、发布、日志元数据作为只读数据源，用真实业务术语和已验证查询做基准；不要把 SQL 查询产品硬改成任意文件搜索器。

### Datus：业务含义要进入可检索上下文

固定阅读版本 `dab2383a03826c178b96f8ae47ae7d09f7556d63`。

- [context_search.py](https://github.com/Datus-ai/Datus-agent/blob/dab2383a03826c178b96f8ae47ae7d09f7556d63/datus/tools/func_tool/context_search.py)：区分指标、参考 SQL、语义对象等；提供相似搜索和按标识读取的不同工具。
- [schema_linking_node.py](https://github.com/Datus-ai/Datus-agent/blob/dab2383a03826c178b96f8ae47ae7d09f7556d63/datus/agent/node/schema_linking_node.py)：用独立节点确定相关表结构和样本值，并保存到工作流上下文。
- [2026-08-17 官方说明](https://datus.ai/blog/introducing-datus-knowledge/)：介绍 schema、语义模型、业务指标、参考 SQL、模板和平台文档组成的知识层。此日期符合近期材料要求，但来源是官方博客，不是小红书。

可学习点：先确定问题对象，读取对应资料，再回答；“查文件”“查指标”“查日志”需要不同工具和输出。无需让每个问题都进入故障原因报告模板。

## 建议的采用方式（尚未实施）

第一轮仅 GitHub 初筛曾建议 **Onyx CE + 配置/日志适配器**；本轮小红书及源码核验后，当前故障领域改为优先验证 **UnifiedModel + 配置实体和日志执行适配器**。如果用户最终要的是“本月订单量、销售额、错误比例”等表格分析，则优先验证 SQLBot，并研究 Datus/Wren 的上下文和语义约束。

1. 固定上游版本，在独立目录和端口启动；使用相同 Mistral 与同一批资料。
2. 先体验原版，再记录原版找不到配置文件的具体原因，扩展文件适配器；不先改品牌或重写页面。
3. 使用至少20条不同问法评测找到/不存在/歧义/越权/历史版本，并逐条核对答案与来源。
4. 以“目标文件是否真的找到、引用是否支持说法、能否打开来源、耗时”比较当前版和扩展版。通过后再迁移业务流程。

这些是待验证的实施建议，不是已经证明开源底座优于当前项目的性能结论。本轮已完成上述三篇帖子与仓库的交叉核验；上游实际运行和扩展效果待下一阶段验证。
