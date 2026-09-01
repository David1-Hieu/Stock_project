from __future__ import annotations

import unittest
from services.derived_financial_metrics_safe import enrich_fundamental_summary_safe


class TestSafeDerivedMetrics(unittest.TestCase):
    def test_safe_derived_metrics_preserves_structure(self):
        # Statement objects intentionally use wrapped dict shapes.
        income = {
            "records": [
                {"period": "2026-Q2", "revenue": 14.66, "net_income": 9.03},
                {"period": "2026-Q1", "revenue": 16.17, "net_income": 8.63},
                {"period": "2025-Q2", "revenue": 13.00, "net_income": 7.50},
            ],
            "meta": {"source": "test"},
        }
        balance = {
            "records": [
                {"period": "2026-Q2", "total_liabilities": 2217.72, "equity": 224.56}
            ],
            "meta": {"source": "test"},
        }
        cash = {
            "records": [
                {"period": "2026-Q2", "cfo": 10.0, "capex": -2.0}
            ],
            "meta": {"source": "test"},
        }

        summary = {
            "symbol": "TEST",
            "income": income,
            "balance": balance,
            "cash_flow": cash,
        }

        out = enrich_fundamental_summary_safe(summary)

        # Critical regression check: shapes are untouched.
        self.assertIs(out["income"], income)
        self.assertIs(out["balance"], balance)
        self.assertIs(out["cash_flow"], cash)
        self.assertIsInstance(out["income"], dict)
        self.assertIsInstance(out["balance"], dict)
        self.assertIsInstance(out["cash_flow"], dict)

        self.assertEqual(round(out["debt_equity"], 2), 9.88)
        self.assertEqual(round(out["net_margin"], 2), 61.60)
        self.assertEqual(round(out["revenue_yoy"], 2), 12.77)
        self.assertEqual(round(out["profit_yoy"], 2), 20.40)


if __name__ == "__main__":
    unittest.main()
