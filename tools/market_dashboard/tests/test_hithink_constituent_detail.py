import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.market_dashboard.hithink_constituent_detail import constituent_history


class ConstituentDetailTests(unittest.TestCase):
    def test_membership_sorting_missing_and_future_quotes(self):
        c = sqlite3.connect(':memory:')
        c.executescript('''
          CREATE TABLE sector_membership_snapshot(sector_id,stock_id,membership_date,membership_version);
          CREATE TABLE stock_market_snapshot(stock_id,market_date,observed_at,last_price,prev_price,price_change_ratio_pct,turnover,volume);
          INSERT INTO sector_membership_snapshot VALUES
          ('885001.TI','000001.SZ','2026-11-16','sector-membership-ths-v1'),
          ('885001.TI','000002.SZ','2026-11-16','sector-membership-ths-v1'),
          ('885001.TI','000003.SZ','2026-11-16','sector-membership-ths-v1'),
          ('885001.TI','000004.SZ','2026-11-18','sector-membership-ths-v1');
          INSERT INTO stock_market_snapshot VALUES
          ('000001.SZ','2026-11-17',1000,11,10,10,100,10),
          ('000002.SZ','2026-11-17',1000,10,10,0,200,20),
          ('000001.SZ','2026-11-17',3000,8,10,-20,300,30);
        ''')
        with tempfile.TemporaryDirectory() as tmp:
            panel = Path(tmp)/'panel.csv'
            with panel.open('w') as f:
                w=csv.writer(f);w.writerow(['thscode','date','close','prev_close','volume','turnover','prev_date'])
                w.writerow(['000002.SZ','2026-11-16',9,10,20,180,'2026-11-13'])
                w.writerow(['000001.SZ','2026-11-16',10,10,0,0,'2026-11-13'])
            result=constituent_history(c,'885001.TI',{'2026-11-17':2000,'2026-11-16':2000},'2026-11-17',panel,{'000001.SZ':'平安银行'})
        live=result['2026-11-17']
        self.assertEqual([r['code'] for r in live['rows']],['000001.SZ','000002.SZ','000003.SZ'])
        self.assertEqual(live['rows'][0]['return1d'],10)
        self.assertEqual(live['rows'][0]['name'],'平安银行')
        self.assertIsNone(live['rows'][-1]['rank'])
        self.assertEqual((live['total'],live['validCount']),(3,2))
        historical=result['2026-11-16']
        self.assertEqual(historical['rows'][0]['code'],'000002.SZ')
        self.assertAlmostEqual(historical['rows'][0]['return1d'],-10)
        self.assertEqual(historical['priceBasis'],'forward_adjusted')


if __name__ == '__main__':
    unittest.main()
