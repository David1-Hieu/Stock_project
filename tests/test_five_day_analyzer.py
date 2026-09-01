import os
import tempfile
import unittest

from database import init_db, upsert_snapshot
from monitoring.five_day_analyzer import analyze_symbol


class FiveDayAnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ['STOCK_ANALYZE_DB'] = os.path.join(self.tmp.name, 'test.db')
        init_db()
        dates = ['2026-08-24','2026-08-25','2026-08-26','2026-08-27','2026-08-28']
        stock = [25,25.5,25.3,26,26.5]
        idx = [1000,1002,1005,1008,1010]
        vn30 = [1200,1203,1204,1208,1212]
        for i,d in enumerate(dates):
            base = {'trade_date':d,'open':stock[i],'high':stock[i],'low':stock[i],'close':stock[i],'volume':1000,'rsi':50+i*2,'macd':0.1+i*.05,'macd_signal':0.08+i*.03,'ema20':24,'ema50':23,'ema200':20,'technical_score':70+i*2,'fundamental_score':80,'valuation_score':75,'risk_score':72,'final_score':80,'is_benchmark':0,'captured_at':d+'T15:30:00+07:00'}
            upsert_snapshot({'symbol':'HPG',**base})
            b={**base,'symbol':'VNINDEX','open':idx[i],'high':idx[i],'low':idx[i],'close':idx[i],'is_benchmark':1,'technical_score':None,'fundamental_score':None,'valuation_score':None,'risk_score':None,'final_score':None}
            upsert_snapshot(b)
            c={**b,'symbol':'VN30','open':vn30[i],'high':vn30[i],'low':vn30[i],'close':vn30[i]}
            upsert_snapshot(c)

    def tearDown(self):
        os.environ.pop('STOCK_ANALYZE_DB',None)
        self.tmp.cleanup()

    def test_analysis_has_relative_strength(self):
        r=analyze_symbol('HPG',5)
        self.assertTrue(r['success'])
        self.assertGreater(r['return_5d'], r['vnindex_return_5d'])
        self.assertGreater(r['relative_strength_vnindex'],0)
        self.assertEqual(r['technical_score_change'],8.0)
        self.assertAlmostEqual(r['average_close_5d'], 25.66, places=2)

if __name__=='__main__':
    unittest.main()
