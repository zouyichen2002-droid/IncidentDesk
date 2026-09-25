"""Known business contracts must survive model-selected columns and correction."""

import re

import sqlglot
from sqlglot import exp


AOV = re.compile(r"客单价|\baov\b|平均订单金额|average_order_value|avg_order_value", re.I)


def _valid_aov(tree):
    valid = any(
        isinstance(n.this, exp.Column) and n.this.name == "order_amount"
        for n in tree.find_all(exp.Avg)
    )
    for n in tree.find_all(exp.Div):
        left, right = n.this, n.expression
        while isinstance(left, (exp.Paren, exp.Cast)):
            left = left.this
        while isinstance(right, (exp.Paren, exp.Nullif, exp.Cast)):
            right = right.this
        if (
            isinstance(left, exp.Sum)
            and isinstance(left.this, exp.Column)
            and left.this.name == "order_amount"
            and isinstance(right, exp.Count)
        ):
            arg = right.this
            valid |= isinstance(arg, exp.Star) or (
                isinstance(arg, exp.Column) and arg.name == "order_id"
            ) or (
                isinstance(arg, exp.Distinct)
                and len(arg.expressions) == 1
                and isinstance(arg.expressions[0], exp.Column)
                and arg.expressions[0].name == "order_id"
            )
    return valid


def validate_metrics(question: str, sql: str):
    if not AOV.search(question):
        return
    tree = sqlglot.parse_one(sql, read="mysql")
    # Validate named AOV projections, rather than treating every COUNT in the
    # query as its denominator. Distinct customer counts are independent metrics.
    targets = [n.this for n in tree.find_all(exp.Alias) if AOV.search(n.alias)]
    if not all(_valid_aov(target) for target in (targets or [tree])):
        raise ValueError(
            "客单价必须使用 AVG(order_amount) 或 SUM(order_amount)/COUNT(DISTINCT order_id)，不能用日期数或商品数量作分母。"
        )
