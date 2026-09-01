import os
import tempfile
import unittest

from database import add_watchlist, get_watchlist, init_db, remove_watchlist, upsert_holding, get_holdings


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["STOCK_ANALYZE_DB"] = os.path.join(self.tmp.name, "test.db")
        init_db()

    def tearDown(self):
        os.environ.pop("STOCK_ANALYZE_DB", None)
        self.tmp.cleanup()

    def test_watchlist_crud(self):
        add_watchlist("hpg", "test")
        self.assertEqual(get_watchlist()[0]["symbol"], "HPG")
        self.assertTrue(remove_watchlist("HPG"))
        self.assertEqual(get_watchlist(), [])

    def test_portfolio_upsert(self):
        upsert_holding("FPT", 100, 88.5)
        row = get_holdings()[0]
        self.assertEqual(row["symbol"], "FPT")
        self.assertEqual(row["quantity"], 100)


if __name__ == "__main__":
    unittest.main()
