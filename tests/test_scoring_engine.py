import unittest

from screening.scoring_engine import score_stock, score_fundamental_quality, score_valuation, score_technical, score_risk


class ScoringEngineTest(unittest.TestCase):
    def setUp(self):
        self.technical_good = {
            "last_price": 120,
            "trend": "TĂNG",
            "indicators": {
                "rsi": 58,
                "macd": 2.2,
                "macd_signal": 1.8,
                "macd_hist": 0.4,
                "ema20": 115,
                "ema50": 108,
                "ema200": 95,
                "bb_upper": 125,
                "bb_mid": 115,
                "bb_lower": 105,
            },
            "signals": {
                "price_above_ema20": {"active": True},
                "macd_bullish_cross": {"active": True},
                "golden_cross": {"active": False},
                "volume_spike": {"active": True},
                "macd_bearish_cross": {"active": False},
                "death_cross": {"active": False},
            },
        }
        self.fundamental_good = {
            "ratios": [{
                "pe": 10.5,
                "pb": 1.8,
                "roe": 19,
                "roa": 9,
                "debt_equity": 0.7,
                "eps": 4200,
                "net_margin": 15,
            }],
            "income": [{
                "revenue": 1000,
                "net_income": 180,
                "revenue_growth_yoy": 18,
                "profit_growth_yoy": 26,
            }],
            "balance": {
                "total_assets": 10000,
                "total_debt": 4200,
                "equity": 5800,
                "cash": 1500,
            },
        }

    def test_component_scores_are_bounded(self):
        for result in (
            score_fundamental_quality(self.fundamental_good),
            score_valuation("FPT", self.fundamental_good),
            score_technical(self.technical_good),
            score_risk(self.technical_good, self.fundamental_good),
        ):
            self.assertGreaterEqual(result["score"], 0)
            self.assertLessEqual(result["score"], 100)

    def test_full_score_is_explainable(self):
        result = score_stock("FPT", self.technical_good, self.fundamental_good)
        self.assertIn("components", result)
        self.assertIn("explanation", result)
        self.assertTrue(result["eligible"])
        self.assertGreater(result["final_score"], 60)

    def test_negative_eps_fails_hard_filter(self):
        bad = {**self.fundamental_good, "ratios": [{**self.fundamental_good["ratios"][0], "eps": -100}]}
        result = score_stock("FPT", self.technical_good, bad)
        self.assertFalse(result["eligible"])
        self.assertTrue(any("EPS" in x for x in result["filters"]["reasons"]))

    def test_bank_uses_bank_profile(self):
        result = score_valuation("MBB", self.fundamental_good)
        self.assertEqual(result["industry_profile"], "BANK")
        self.assertGreater(result["weights"]["pb"], result["weights"]["pe"])


if __name__ == "__main__":
    unittest.main()
