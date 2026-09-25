"""Re-run all extended cases, plus tutorial value/metric examples and trace checks."""
import asyncio
import json
from pathlib import Path

import httpx
import extended_acceptance as suite

OUT = Path(__file__).resolve().parents[1] / "docs/evidence/atguigu-capabilities"


async def main():
    suite.OUT = OUT
    suite.CASES.extend([
        ("品牌真实取值", "2025年第一季度苹果品牌商品的销售额是多少？只返回金额。", "SELECT SUM(f.order_amount) FROM fact_order f JOIN dim_product p ON f.product_id=p.product_id WHERE f.date_id BETWEEN 20250101 AND 20250331 AND p.brand='苹果'"),
        ("会员指标口径", "2025年第一季度黄金会员客单价是多少？只返回客单价，保留两位小数。", "SELECT ROUND(AVG(f.order_amount),2) FROM fact_order f JOIN dim_customer c ON f.customer_id=c.customer_id WHERE f.date_id BETWEEN 20250101 AND 20250331 AND c.member_level='黄金'"),
        ("品类真实取值", "2025年第一季度手机数码品类GMV是多少？只返回金额。", "SELECT SUM(f.order_amount) FROM fact_order f JOIN dim_product p ON f.product_id=p.product_id WHERE f.date_id BETWEEN 20250101 AND 20250331 AND p.category='手机数码'"),
        ("商品件数区别订单数", "2025年第一季度苹果品牌的商品一共卖了多少件？只返回商品件数。", "SELECT SUM(f.order_quantity) FROM fact_order f JOIN dim_product p ON f.product_id=p.product_id WHERE f.date_id BETWEEN 20250101 AND 20250331 AND p.brand='苹果'"),
    ])
    records = await suite.main()
    successful = [r["detail"] for r in records if r.get("passed") and (r.get("detail") or {}).get("status") == "completed"]
    required = {"抽取关键词", "召回字段信息", "召回指标信息", "召回字段取值", "合并召回信息", "过滤表信息", "过滤指标信息", "添加额外上下文", "生成SQL", "校验SQL", "执行SQL"}
    trace_ok = bool(successful)
    for record in successful:
        events = record["progress"]
        trace_ok &= all(e.get("request_id") == record["id"] and e.get("elapsed_ms", -1) >= 0 for e in [*events, record["result"]])
        trace_ok &= required <= {e["step"] for e in events if e["status"] == "success"}
        trace_ok &= all(e.get("duration_ms", -1) >= 0 for e in events if e["status"] == "success")
    # Check correlation against actual logs without persisting prompts or full logs.
    proc = await asyncio.create_subprocess_exec("docker", "compose", "logs", "--no-color", "--since", "30m", "query", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=suite.ROOT)
    logs, _ = await proc.communicate()
    correlation = bool(successful) and proc.returncode == 0 and all(r["id"].encode() in logs for r in successful)
    counts = await suite.gold("SELECT (SELECT COUNT(*) FROM meta.table_info),(SELECT COUNT(*) FROM meta.column_info),(SELECT COUNT(*) FROM meta.metric_info),(SELECT COUNT(*) FROM dw.fact_order)")
    checks = [
        {"name": "workflow_progress_and_timing", "passed": bool(trace_ok), "queries": len(successful), "required_steps": sorted(required)},
        {"name": "query_id_in_python_logs", "passed": bool(correlation)},
        {"name": "teaching_metadata_and_data_preserved", "passed": counts == [["5", "24", "2", "115"]], "counts_tables_columns_metrics_orders": counts},
    ]
    (OUT / "trace-checks.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2))
    (OUT / "acceptance.json").write_text(json.dumps(records, ensure_ascii=False, indent=2))
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return all(r["passed"] for r in records + checks)


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(main()) else 1)
