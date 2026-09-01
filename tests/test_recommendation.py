import unittest
from recommendation.engine import recommend


class RecommendationTests(unittest.TestCase):
    def test_positive_setup(self):
        payload = {
            "success": True, "symbol": "HPG", "return_5d": 6.0,
            "relative_strength_vnindex": 4.5, "relative_strength_vn30": 3.0,
            "technical_score_change": 8.0, "rsi_end": 60,
            "macd_end": 1.2, "macd_signal_end": 0.8,
            "max_drawdown_5d": -1.0, "final_score": 84,
        }
        result = recommend(payload)
        self.assertEqual(result["system_action"], "ACCUMULATE_ON_PULLBACK")
        self.assertIn(result["confidence"], {"MEDIUM", "HIGH"})

    def test_negative_setup(self):
        payload = {
            "success": True, "symbol": "XYZ", "return_5d": -8.0,
            "relative_strength_vnindex": -7.0, "relative_strength_vn30": -6.0,
            "technical_score_change": -12.0, "rsi_end": 28,
            "macd_end": -1.0, "macd_signal_end": -0.2,
            "max_drawdown_5d": -9.0, "final_score": 45,
        }
        self.assertEqual(recommend(payload)["system_action"], "REDUCE_OR_EXIT_REVIEW")


if __name__ == "__main__":
    unittest.main()
