"""
SQL 执行节点

负责执行最终 SQL，并记录查询结果。
它是当前 SQL 闭环的结束节点，执行完成后流程进入 END。
"""

from langgraph.runtime import Runtime
from app.core.metrics import validate_metrics
from app.core.relations import validate_relations
from app.core.periods import validate_period
from app.core.sql_guard import safe_sql, MAX_ROWS

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.log import logger


async def run_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """执行 SQL 并产出最终问数结果"""

    writer = runtime.stream_writer
    step = "执行SQL"
    writer({"type": "progress", "step": step, "status": "running"})

    try:
        # 这里拿到的可能是 generate_sql 直接通过校验的 SQL，也可能是 correct_sql 覆盖后的 SQL
        sql = safe_sql(state["sql"])
        dw_mysql_repository = runtime.context["dw_mysql_repository"]

        # 真实数据库访问统一封装在仓储层，节点只负责从状态取 SQL 并触发执行
        validate_relations(sql)
        validate_metrics(state["query"], sql)
        validate_period(state["query"], sql)
        await dw_mysql_repository.validate(sql)
        result = await dw_mysql_repository.run(sql)
        logger.info(f"SQL返回行数：{len(result)}")
        writer({"type": "progress", "step": step, "status": "success"})
        writer({"type": "result", "data": result, "sql": sql, "row_limit": MAX_ROWS})

    except Exception as e:
        logger.error(f"{step} failed: {e}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise
