"""Limit generated SQL to the five-table, read-only local warehouse."""

import sqlglot
from sqlglot import exp

TABLES = {"fact_order", "dim_region", "dim_customer", "dim_product", "dim_date"}
MAX_ROWS = 500


def safe_sql(sql: str) -> str:
    try:
        statements = sqlglot.parse(sql, read="mysql")
    except sqlglot.errors.ParseError as exc:
        raise ValueError("SQL 无法解析，请明确查询条件后重试。") from exc
    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union)):
        raise ValueError("只允许一条 SELECT 查询。")
    tree = statements[0]
    forbidden = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Create,
        exp.Drop,
        exp.Command,
        exp.Into,
        exp.Lock,
        exp.Transaction,
        exp.Set,
        exp.Merge,
    )
    if any(isinstance(node, forbidden) for node in tree.walk()):
        raise ValueError("查询不能修改数据、写文件或加锁。")
    ctes = {node.alias_or_name.lower() for node in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        if table.catalog or table.db or table.name.lower() not in TABLES | ctes:
            raise ValueError("查询只能访问当前电商数仓的五张业务表。")
    for node in tree.find_all(exp.Func):
        name = node.name if isinstance(node, exp.Anonymous) else node.sql_name()
        if name.lower() in {
            "sleep",
            "benchmark",
            "load_file",
            "get_lock",
            "release_lock",
            "release_all_locks",
            "master_pos_wait",
            "source_pos_wait",
        }:
            raise ValueError("查询包含不允许的函数。")
    if any(
        isinstance(node, (exp.Parameter, exp.SessionParameter)) for node in tree.walk()
    ):
        raise ValueError("查询不能访问数据库系统变量。")
    limit = tree.args.get("limit")
    if limit is None:
        tree = tree.limit(MAX_ROWS)
    else:
        try:
            count = int(limit.expression.name)
        except ValueError, AttributeError:
            raise ValueError("LIMIT 必须是整数。") from None
        if count < 0 or count > MAX_ROWS:
            tree = tree.limit(MAX_ROWS)
    return tree.sql(dialect="mysql")
