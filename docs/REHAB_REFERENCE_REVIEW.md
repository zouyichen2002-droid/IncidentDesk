# 学长康复 Agent 项目的技术借鉴评审

日期：2026-09-25。用户提供仓库：[AI-Powered-Rehabilitation-Coaching-System](https://github.com/DS5500-Team-11-AI-Powered-Rehab/AI-Powered-Rehabilitation-Coaching-System)。本次阅读基于 main 提交 `e52364476daa1ecde95b4596a6477b20d5b40a6a`。这是工程设计阅读及有限测试；没有调用其付费模型、运行摄像头、下载模型权重或验证康复效果。没有修改当前产品实现或将下面建议视为已经完成。

## 结论

最有价值的参考是：把即时执行、长期总结和知识检索拆开；使用结构化结果进行模块交接；通过状态和事件决定执行时机；按复杂度分流；把评测材料作为工程交付物。建议与掌柜问数互补：掌柜问数继续提供NL2SQL/Schema检索设计，这个项目提供会话记忆、事件管理和分层处理设计。

我们继续沿用Go + Python/FastAPI + LangGraph + React + PostgreSQL + Qdrant/ES + Mistral。已有的技术职责清晰，不需要为学习该项目再增加一套ChromaDB、Streamlit或Ollama运行栈。

## 1. 核查到的技术栈与入口

| 部分 | 实际代码/配置 | 说明 |
|---|---|---|
| 页面与视频 | `frontend/streamlit_app.py`、`requirements_full_local_mvp.txt` | Streamlit、streamlit-webrtc、PyAV；`app_wrapper.py`连接推理事件与Agent图 |
| 动作识别 | `src/cv/` | MediaPipe、OpenCV、PyTorch时序模型；是康复业务特有的输入处理，我们的问数项目暂不需要 |
| 工作流 | `src/integration/graph.py:create_coaching_graph` | 真正的LangGraph StateGraph：上下文、3档处理、反馈整理、质量检查、格式化和记录节点 |
| 事件处理 | `src/integration/integration_layer.py` | 时间窗口聚合、持续性/置信度过滤、去重、冷却时间、重复失败升级处理 |
| 会话状态 | `src/agents/coaching_agent/session_manager.py` | ExerciseBuffer、后台线程检查超时、阶段总结、JSON导出；独立于LangGraph图的另一层状态管理 |
| RAG | `src/agents/progress_tracker_agent/rag_retriever.py` | LangChain、ChromaDB、HuggingFace all-MiniLM-L6-v2；TXT/HTML清洗、切块、top-k和来源文件名 |
| 模型 | `src/integration/graph.py`、progress tracker | 有Anthropic调用和Ollama Gemma3:4b。README提到Sonnet4.5，但实时图默认字符串为`claude-sonnet-4-20250514`，不能只按README认定全部入口使用同一版本 |
| 缓存/测试 | `ResponseCache`、`tests/unit/`、notebook评测 | diskcache可选；包含真实的纯逻辑测试和模型比较材料。部分依赖仅在frontend requirements中列出 |

[固定版本工作流](https://github.com/DS5500-Team-11-AI-Powered-Rehab/AI-Powered-Rehabilitation-Coaching-System/blob/e52364476daa1ecde95b4596a6477b20d5b40a6a/src/integration/graph.py)

## 2. 截图中的三项描述，如何理解

### 多Agent与跨session记忆

存在分工不同的反馈和进度模块。`SessionManager._export_json`导出阶段基本信息、动作记录、质量汇总、错误、下阶段关注点和报告；`progress_tracker.py:load_phase_jsons`读取阶段文件并按时间排序，后续先通过普通Python函数计算趋势，再让模型组织语言。

可借鉴点是“传结构化事实和摘要”，而不是不断传整段聊天。它属于显式文件记忆和应用编排，不表示模型权重会记住用户，也不表示Agent自主讨论或协商。

需要区分入口：当前主页面的`frontend/app_wrapper.py`直接调用LangGraph，并把当前会话事件构造成PatientContext生成报告；没有直接使用上述SessionManager或读取全部Phase JSON。因此，不能仅凭两个模块都存在，就称主页面已经完整串起所有跨session记忆功能。

[导出代码](https://github.com/DS5500-Team-11-AI-Powered-Rehab/AI-Powered-Rehabilitation-Coaching-System/blob/e52364476daa1ecde95b4596a6477b20d5b40a6a/src/agents/coaching_agent/session_manager.py) · [历史汇总代码](https://github.com/DS5500-Team-11-AI-Powered-Rehab/AI-Powered-Rehabilitation-Coaching-System/blob/e52364476daa1ecde95b4596a6477b20d5b40a6a/src/agents/progress_tracker_agent/progress_tracker.py)

### RAG与评测

真实存在文档检索、上下文注入和来源列表。评测notebook包含事实覆盖、语义覆盖、完整性、检索相似度、时延与费用等指标，并有保存的比较结果。

本次检查的源码、README、JSON及notebook代码中，没有定位到与截图“专业一致性提升15%+”直接对应的有/无RAG对照实验，也没有定位到同名Precision@K/Source Coverage实现。不能据此断言学长没做过；可能是其他版本或未公开实验，但现阶段不能把这些数字作为已复现证据。

此外，notebook中的`evaluate_retrieval_quality`计算检索文本与参考答案的余弦相似度，和Precision@K不是一回事；`medical_accuracy`来自关键词规则的安全分数，不是独立专家逐条判断的临床正确率。对我们而言，关键是指标名称、计算方法和声称的结论一致。

[评测notebook](https://github.com/DS5500-Team-11-AI-Powered-Rehab/AI-Powered-Rehabilitation-Coaching-System/blob/e52364476daa1ecde95b4596a6477b20d5b40a6a/notebooks/llm_comprehensive_evaluation-v2.ipynb) · [已保存结果](https://github.com/DS5500-Team-11-AI-Powered-Rehab/AI-Powered-Rehabilitation-Coaching-System/blob/e52364476daa1ecde95b4596a6477b20d5b40a6a/notebooks/evaluation_results/EVALUATION_SUMMARY.md)

### Session Manager与LangGraph

代码有30秒动作结束与120秒阶段结束常量，但二者并不简单共用“最后事件时间”：动作检查用`last_event_ts`，阶段检查用`last_ex_end_ts`，且刷新动作时会重置后者。直接连续静默时，阶段结束可能约在最后事件150秒之后，而不是截图给人的统一120秒截止。

截图所说“模拟LangGraph”可能描述更早阶段；当前仓库已经有`StateGraph(...).compile()`，主页面调用`graph.invoke`。图中的`progress_tracking_node`注释称后台异步，但实现是同步函数和普通顺序边，没有独立后台调度。我们应以调用路径和实现判断能力。

## 3. 借鉴到IncidentDesk的具体方案

| 优先级 | 借鉴设计 | 我们的落地方式 | 验收标准 |
|---|---|---|---|
| P0 | 结构化跨会话记忆 | PostgreSQL保存conversation/turn/summary，关联查询ID、用户、数据集版本、已确认条件、SQL和证据引用 | 刷新/重登后追问仍保留条件；改年份不保留旧年；账号切换不能读他人上下文；历史数字标注时间，不当作当前结果 |
| P0 | 即时执行与长期总结分工 | 查询规划、执行、校验、总结职责独立；先用当前LangGraph节点实现，仍共用Mistral | 每个模块有输入输出契约；总结不能修改数据库数值；失败及缺数据能回到澄清 |
| P0 | 分层评测 | 标注字段/指标/值的相关集合，计算Precision@K、Recall@K；再检查SQL结果正确率、约束保留与来源引用正确率 | 保存检索候选和标准答案；区分检索正确、SQL正确、回答正确；有无HyDE/排序做相同题集比较 |
| P1 | 分档处理 | 常见帮助/经审核的定义走轻路径；普通问数走现有链路；复杂比较/组合问题走独立计划与校验 | 记录路由理由、耗时和成功率；缓存区分用户范围与数据版本；业务数值默认重新查询 |
| P1 | 状态驱动生命周期 | 会话、查询任务、总结任务分开；复用Go持久队列、租约、幂等和取消，不直接复制后台线程定时器 | 并发、重启、重复事件和迟到结果不导致丢任务或重复总结 |
| P1 | 质量检查与降级 | 用Schema、SQL AST、真实执行值与来源校验；资料不足返回具体缺口或澄清 | 不把拒答一律判坏，不把模板内容伪装成检索证据，不用关键词重叠代替业务正确性 |

会话摘要的建议字段：`schema_version`、`conversation_id`、`owner_subject`、`dataset_id`、`dataset_version`、`resolved_intent`、`confirmed_filters`、`query_ids`、`evidence_refs`、`unresolved_questions`、`updated_at`。摘要是导航和上下文，不是绕过权限或数据新鲜度检查的依据。

## 4. 不直接照搬的部分

- Phase JSON适合课设模块交换；我们已有持久数据库和多用户权限，应存数据库中的版本化结构，不让散落文件成为生产记忆来源。
- ChromaDB和Streamlit是该项目的实现选择；当前Qdrant/ES和React已承担对应职责。更换库本身不能解决问数准确率。
- `enrich_context_node`当前覆盖为固定测试用户档案；缺文档的部分分支构造通用文本后仍作为guidelines上下文使用。这些是我们迁移前要改造的演示处理，不作为可靠来源模式采用。
- 质量检查主要靠长度、词重叠、拒答短语，适合检查输出形式，不足以证明事实正确。
- 模块分工可以先在单个流程中完成；是否分多个模型或独立服务，要依据效果和成本实验。继续使用用户指定的Mistral。

## 5. 本轮验证边界

命令：

```sh
uv run --project query --with pytest python -m pytest .local/rehab-reference/tests/unit -q -p no:cacheprovider
```

结果：**59 passed in 0.11s**，使用本机Python3.14.6临时测试环境，非仓库推荐的完整Python3.11环境。测试内容为事件过滤/路由、ExerciseBuffer和趋势/适配等纯逻辑，测试代码明确排除真实LLM调用。输出见 [unit.txt](evidence/rehab-reference/unit.txt)。

没有运行完整Streamlit/WebRTC/MediaPipe/Chroma/Anthropic/Ollama链路，不据此声称项目开箱即用、各入口已打通或简历效果指标已复现。此次只新增阅读报告和测试证据；现有应用保持原实现。
