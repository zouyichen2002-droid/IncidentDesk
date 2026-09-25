import unittest

from app.core.sql_guard import safe_sql


class SQLGuardTests(unittest.TestCase):
    def test_read_only_business_queries(self):
        for query in [
            "SELECT SUM(order_amount) AS GMV FROM fact_order",
            "SELECT r.region_name, SUM(o.order_amount) FROM fact_order o JOIN dim_region r ON o.region_id=r.region_id GROUP BY r.region_name",
            "WITH totals AS (SELECT SUM(order_amount) AS gmv FROM fact_order) SELECT * FROM totals",
            "SELECT order_id FROM fact_order UNION SELECT order_id FROM fact_order",
        ]:
            with self.subTest(query=query):
                self.assertIn("LIMIT 500", safe_sql(query))

    def test_rejects_mutation_and_external_access(self):
        for query in [
            "DELETE FROM fact_order",
            "DROP TABLE fact_order",
            "SELECT * FROM fact_order; DELETE FROM fact_order",
            "SELECT * FROM mysql.user",
            "SELECT * FROM information_schema.tables",
            "SELECT * FROM fact_order INTO OUTFILE '/tmp/orders'",
            "SELECT * FROM fact_order FOR UPDATE",
            "SELECT SLEEP(100) FROM fact_order",
            "SELECT LOAD_FILE('/etc/passwd')",
            "SELECT @@version",
            "SELECT * FROM unknown_table",
            "WITH secret AS (SELECT * FROM mysql.user) SELECT * FROM secret",
        ]:
            with self.subTest(query=query), self.assertRaises(ValueError):
                safe_sql(query)

    def test_caps_rows_without_expanding_explicit_limit(self):
        self.assertIn("LIMIT 5", safe_sql("SELECT * FROM fact_order LIMIT 5"))
        self.assertIn("LIMIT 500", safe_sql("SELECT * FROM fact_order LIMIT 999999"))


if __name__ == "__main__":
    unittest.main()
