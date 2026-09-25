"""Reject joins that are syntactically valid but violate the known warehouse keys."""

import sqlglot
from sqlglot import exp

KEYS = {
    "dim_region": "region_id",
    "dim_customer": "customer_id",
    "dim_product": "product_id",
    "dim_date": "date_id",
}


def validate_relations(sql: str):
    tree = sqlglot.parse_one(sql, read="mysql")
    for select in tree.find_all(exp.Select):
        aliases = {t.alias_or_name: t.name for t in select.find_all(exp.Table)}
        for join in select.args.get("joins", []):
            on = join.args.get("on")
            using = join.args.get("using")
            if on is None and not using:
                raise ValueError("业务表关联必须使用显式外键，不能使用笛卡尔积。")
            if on is None:
                table = join.this
                if (
                    isinstance(table, exp.Table)
                    and table.name in KEYS
                    and [x.name for x in using] != [KEYS[table.name]]
                ):
                    raise ValueError("维度表必须按对应 ID 外键关联。")
                continue
            for eq in on.find_all(exp.EQ):
                a, b = eq.this, eq.expression
                if not isinstance(a, exp.Column) or not isinstance(b, exp.Column):
                    continue
                ta, tb = aliases.get(a.table), aliases.get(b.table)
                if ta == "fact_order" and tb in KEYS:
                    key = KEYS[tb]
                elif tb == "fact_order" and ta in KEYS:
                    key = KEYS[ta]
                else:
                    continue
                if a.name != key or b.name != key:
                    raise ValueError(
                        f"关联错误：fact_order 与维度表必须使用 {key} = {key}，不能用名称代替 ID。"
                    )
