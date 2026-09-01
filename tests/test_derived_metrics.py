from __future__ import annotations

import unittest
from services.derived_financial_metrics_safe import enrich_fundamental_summary_safe


class TestDerivedMetrics(unittest.TestCase):
    def test_derived_financial_metrics(self):
        sample = {
            "symbol": "TEST",
            "income": [
                {"period": "2026-Q2", "revenue": 14.66, "net_income": 9.03, "gross_profit": 10.0},
                {"period": "2026-Q1", "revenue": 16.17, "net_income": 8.63, "gross_profit": 11.0},
                {"period": "2025-Q4", "revenue": 13.69, "net_income": 8.70, "gross_profit": 9.0},
                {"period": "2025-Q3", "revenue": 19.14, "net_income": 14.55, "gross_profit": 12.0},
                {"period": "2025-Q2", "revenue": 13.00, "net_income": 7.50, "gross_profit": 8.0},
            ],
            "balance": [
                {
                    "period": "2026-Q2",
                    "total_liabilities": 2217.72,
                    "equity": 224.56,
                    "current_assets": 100.0,
                    "current_liabilities": 80.0,
                }
            ],
            "cash_flow": [
                {"period": "2026-Q2", "cfo": 10.0, "capex": -2.0}
            ],
        }

        out = enrich_fundamental_summary_safe(sample)

        self.assertEqual(round(out["debt_equity"], 2), 9.88)
        self.assertEqual(round(out["net_margin"], 2), 61.60)
        self.assertEqual(round(out["revenue_qoq"], 2), -9.34)
        self.assertEqual(round(out["profit_qoq"], 2), 4.63)
        self.assertEqual(round(out["revenue_yoy"], 2), 12.77)
        self.assertEqual(round(out["profit_yoy"], 2), 20.40)
        self.assertEqual(round(out["free_cash_flow"], 2), 8.00)


if __name__ == "__main__":
    unittest.main()
