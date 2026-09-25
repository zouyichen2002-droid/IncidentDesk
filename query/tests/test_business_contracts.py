import unittest
from datetime import date

from app.core.metrics import validate_metrics
from app.core.periods import validate_period
from app.core.relations import validate_relations


class BusinessContractTests(unittest.TestCase):
    def test_explicit_month_cannot_disappear_when_changing_metrics(self):
        question = "查询2025年1月华东地区的订单数"
        with self.assertRaisesRegex(ValueError, "1 月"):
            validate_period(question, "SELECT COUNT(*) FROM fact_order f JOIN dim_date d ON f.date_id=d.date_id WHERE d.year=2025")
        validate_period(question, "SELECT COUNT(*) FROM fact_order f JOIN dim_date d ON f.date_id=d.date_id WHERE d.year=2025 AND d.month=1")
        validate_period(question, "SELECT COUNT(*) FROM fact_order WHERE date_id BETWEEN 20250101 AND 20250131")
        validate_period(question, "SELECT COUNT(*) FROM fact_order WHERE date_id>=20250101 AND date_id<20250201")
        with self.assertRaises(ValueError):
            validate_period(question, "SELECT COUNT(*) FROM fact_order WHERE date_id BETWEEN 20250101 AND 20251231")
        validate_period("2025年1月15日至2月15日销售额", "SELECT SUM(order_amount) FROM fact_order WHERE date_id BETWEEN 20250115 AND 20250215")

    def test_customer_count_can_coexist_with_aov(self):
        validate_metrics(
            "订单数、去重客户数和客单价",
            "SELECT COUNT(DISTINCT order_id) AS 订单数, COUNT(DISTINCT customer_id) AS 客户数, ROUND(AVG(order_amount),2) AS 客单价 FROM fact_order",
        )
        validate_metrics(
            "客单价与客户数",
            "SELECT COUNT(DISTINCT customer_id) AS 客户数, SUM(order_amount)/NULLIF(COUNT(DISTINCT order_id),0) AS aov FROM fact_order",
        )
        with self.assertRaises(ValueError):
            validate_metrics(
                "客单价",
                "SELECT AVG(order_amount) AS other, SUM(order_amount)/COUNT(DISTINCT customer_id) AS 客单价 FROM fact_order",
            )

    def test_requested_year_cannot_be_silently_ignored(self):
        with self.assertRaises(ValueError):
            validate_period(
                "今年卖了多少",
                "SELECT SUM(order_amount) FROM fact_order",
                date(2026, 9, 24),
            )
        with self.assertRaises(ValueError):
            validate_period(
                "今年卖了多少",
                "SELECT SUM(order_amount) FROM fact_order WHERE date_id BETWEEN 20250101 AND 20251231",
                date(2026, 9, 24),
            )
        validate_period(
            "今年卖了多少",
            "SELECT SUM(order_amount) FROM fact_order WHERE date_id BETWEEN 20260101 AND 20261231",
            date(2026, 9, 24),
        )

    def test_wrong_aov_denominator_is_not_a_valid_answer(self):
        with self.assertRaises(ValueError):
            validate_metrics(
                "客单价",
                "SELECT SUM(order_amount)/COUNT(DISTINCT date_id) FROM fact_order",
            )
        with self.assertRaises(ValueError):
            validate_metrics("AOV", "SELECT AVG(order_quantity) FROM fact_order")
        validate_metrics("客单价", "SELECT ROUND(AVG(order_amount),2) FROM fact_order")
        validate_metrics(
            "客单价",
            "SELECT SUM(order_amount)/COUNT(DISTINCT order_id) FROM fact_order",
        )

    def test_name_in_place_of_foreign_key_cannot_be_reported_as_empty(self):
        with self.assertRaises(ValueError):
            validate_relations(
                "SELECT p.product_name FROM fact_order o JOIN dim_product p ON o.product_id=p.product_name"
            )
        validate_relations(
            "SELECT p.product_name FROM fact_order o JOIN dim_product p ON o.product_id=p.product_id"
        )
        with self.assertRaises(ValueError):
            validate_relations("SELECT * FROM fact_order CROSS JOIN dim_product")
        with self.assertRaises(ValueError):
            validate_relations(
                "SELECT * FROM fact_order JOIN dim_product USING(product_name)"
            )


if __name__ == "__main__":
    unittest.main()
