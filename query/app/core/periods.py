"""Protect explicit year and single-month constraints from being dropped."""

import calendar
import re
from datetime import date

import sqlglot
from sqlglot import exp


def _validate_year(question: str, sql: str, today: date | None = None):
    today = today or date.today()
    years = re.findall(r"(20\d{2})\s*(?:年|[-/])", question)
    if years:
        if len(set(years)) != 1:
            return  # Multi-year ranges are outside this narrow invariant.
        year = int(years[0])
    elif "今年" in question or "本年" in question:
        year = today.year
    elif "去年" in question:
        year = today.year - 1
    else:
        return
    tree = sqlglot.parse_one(sql, read="mysql")
    for where in tree.find_all(exp.Where):
        for predicate in where.find_all(exp.Predicate):
            columns = list(predicate.find_all(exp.Column))
            if not any(c.name in ("year", "date_id") for c in columns):
                continue
            values = [str(n.this) for n in predicate.find_all(exp.Literal)]
            if any(
                v == str(year) or v.startswith(str(year)) and len(v) in (8, 10)
                for v in values
            ):
                return
        if (
            year == today.year
            and "YEAR(CURRENT_DATE)" in where.sql(dialect="mysql").upper()
        ):
            return
    raise ValueError(
        f"问题指定了 {year} 年，SQL 必须保留 year={year} 或该年 date_id 范围，不能改查全部历史订单。"
    )


def validate_period(question: str, sql: str, today: date | None = None):
    _validate_year(question, sql, today)
    # Multi-month comparisons/ranges need a different contract; do not mistake
    # the first endpoint for a single-month query.
    chinese = {str(i): i for i in range(1, 13)}
    chinese.update(dict(zip("一 二 三 四 五 六 七 八 九 十 十一 十二".split(), range(1, 13))))
    months = {chinese.get(m.lstrip("0")) for m in re.findall(r"(\d{1,2}|十一|十二|[一二三四五六七八九十])\s*月", question)}
    if len(months) != 1 or None in months:
        return
    month = months.pop()
    years = set(re.findall(r"(20\d{2})\s*(?:年|[-/])", question))
    year = int(next(iter(years))) if len(years) == 1 else None
    if not years and any(word in question for word in ("今年", "本年", "去年")):
        year = (today or date.today()).year - ("去年" in question)

    def date_value(expression):
        if not isinstance(expression, exp.Literal):
            return None
        raw = str(expression.this).replace("-", "").replace("/", "")
        try:
            return date(int(raw[:4]), int(raw[4:6]), int(raw[6:])) if len(raw) == 8 else None
        except ValueError:
            return None

    def requested(value):
        return value and value.month == month and (year is None or value.year == year)

    tree = sqlglot.parse_one(sql, read="mysql")
    for where in tree.find_all(exp.Where):
        lowers, uppers = [], []
        for predicate in where.find_all(exp.Predicate):
            if isinstance(predicate, (exp.EQ, exp.In)):
                left = predicate.this
                is_month = isinstance(left, exp.Column) and left.name == "month" or isinstance(left, exp.Month)
                values = predicate.expressions if isinstance(predicate, exp.In) else [predicate.expression]
                if is_month and values and all(isinstance(v, exp.Literal) and str(v.this) == str(month) for v in values):
                    return
            if not any(c.name == "date_id" for c in predicate.this.find_all(exp.Column)):
                continue
            if isinstance(predicate, exp.Between):
                if requested(date_value(predicate.args["low"])) and requested(date_value(predicate.args["high"])):
                    return
            if isinstance(predicate, exp.EQ) and requested(date_value(predicate.expression)):
                return
            if isinstance(predicate, exp.GTE):
                value = date_value(predicate.expression)
                if requested(value):
                    lowers.append(value)
            if isinstance(predicate, (exp.LTE, exp.LT)):
                value = date_value(predicate.expression)
                if value:
                    uppers.append((value, isinstance(predicate, exp.LT)))
        for low in lowers:
            last = date(low.year, month, calendar.monthrange(low.year, month)[1])
            following = date(low.year + (month == 12), month % 12 + 1, 1)
            if any(low <= high <= last or exclusive and high == following for high, exclusive in uppers):
                return
    raise ValueError(f"问题指定了 {month} 月，SQL 必须保留 month={month} 或该月 date_id 的上下界，不能只按年份查询。")
