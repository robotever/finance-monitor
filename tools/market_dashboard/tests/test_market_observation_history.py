import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.market_dashboard import market_observation_history as history


class HistoryTests(unittest.TestCase):
    def test_cash_event_and_future_event_do_not_mix_price_bases(self):
        bars=[{'thscode':'000001.SZ','date':d,'close':p,'turnover':100} for d,p in [('2026-11-23',10),('2026-11-24',12),('2026-11-25',11)]]
        events=[{'thscode':'000001.SZ','date':'2026-11-25','dividend_per_share':1,'per_share_bonus':0,'allotment_ratio':0,'allotment_price':0}, {'thscode':'000001.SZ','date':'2026-11-26','dividend_per_share':8,'per_share_bonus':0,'allotment_ratio':0,'allotment_price':0}]
        adjusted,meta=history.adjust_bars(bars,events,'2026-11-25')
        self.assertAlmostEqual(adjusted[0]['close'],10*11/12)
        self.assertEqual(adjusted[1]['close'],11)
        self.assertEqual(adjusted[2]['close'],11)
        self.assertEqual(meta['appliedEvents'],1)
        self.assertEqual([r['turnover'] for r in adjusted],[100]*3)

    def test_bad_event_fails_instead_of_silent_factor_one(self):
        bars=[{'thscode':'000001.SZ','date':d,'close':10,'turnover':100} for d in ['2026-11-24','2026-11-25']]
        event={'thscode':'000001.SZ','date':'2026-11-25','dividend_per_share':20,'per_share_bonus':0,'allotment_ratio':0,'allotment_price':0}
        with self.assertRaisesRegex(history.HistoryError,'EVENT_RATIO_INVALID'):
            history.adjust_bars(bars,[event],'2026-11-25')

    def test_cache_requires_same_database_date_and_daily_event_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);db=root/'data/hithink/market.duckdb';db.parent.mkdir(parents=True);db.write_bytes(b'unchanged')
            bars=[{'thscode':'000001.SZ','date':'2026-11-25','close':10,'turnover':100}]
            with patch.object(history,'_export_raw',return_value=bars) as export,patch.object(history,'_fetch_events',return_value=([],{'sha256':'eventhash'})) as fetch:
                first=history.ensure_history(root/'state',root,'2026-11-25')
                second=history.ensure_history(root/'state',root,'2026-11-25')
                self.assertEqual(first,second);self.assertEqual(export.call_count,1);self.assertEqual(fetch.call_count,1)
                self.assertEqual(first.stat().st_mode & 0o777,0o600)
                self.assertEqual(db.read_bytes(),b'unchanged')
                meta=json.loads(first.with_suffix('.meta.json').read_text())
                self.assertTrue(meta['adjustmentVerified']);self.assertEqual(meta['historyAsOf'],'2026-11-25')
                db.write_bytes(b'new source revision')
                history.ensure_history(root/'state',root,'2026-11-25')
                self.assertEqual(fetch.call_count,2)

    def test_stale_source_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);db=root/'data/hithink/market.duckdb';db.parent.mkdir(parents=True);db.write_bytes(b'unchanged')
            with patch.object(history,'_export_raw',return_value=[{'thscode':'000001.SZ','date':'2026-11-24','close':10,'turnover':100}]):
                with self.assertRaisesRegex(history.HistoryError,'HISTORY_DATE_MISMATCH'):
                    history.ensure_history(root/'state',root,'2026-11-25')
