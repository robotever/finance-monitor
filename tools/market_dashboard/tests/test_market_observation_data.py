import unittest
from tools.market_dashboard.market_observation_data import derive_observation, ObservationError

class ObservationDataTests(unittest.TestCase):
    def snapshot(self, rows):
        return {'timestamp':1795674575000,'total':len(rows),'item':rows}
    def stock(self, code, change, amount=1e8, volume=100):
        return {'thscode':code,'last_price':10,'prev_price':10,'price_change_ratio_pct':change,'turnover':amount,'volume':volume}
    def calendar(self):
        from datetime import date,timedelta
        return [(date(2026,11,25)-timedelta(days=79-i)).isoformat() for i in range(80)]
    def build(self, rows, history=(), calendar=None):
        return derive_observation(self.snapshot(rows), list(history), {'trade_date':'2026-11-26','timestamp':1795674575000,'seal_rate':.6,'limit_up_stock_count':6,'open_stock_count':4,'touched_limit_up_stock_count':10,'exact_boards':[]}, [], [], {'trade_date':'2026-11-25','timestamp':1795536000000,'stock_items':[]}, {'item':[]}, calendar_days=self.calendar() if calendar is None else calendar,previous_date='2026-11-25',observed_at='2026-11-26T06:30:00+00:00')
    def metrics(self,payload):
        return {m['id']:m for g in payload['groups'] for m in g['metrics']}
    def test_denominator_units_and_zeros(self):
        p=self.build([self.stock('000001.SZ',1),self.stock('000002.SZ',0),self.stock('000003.SZ',-1),self.stock('000004.SZ',2,volume=0)])
        m=self.metrics(p)
        self.assertAlmostEqual(m['upShare']['value'],100/3)
        self.assertEqual(p['scope']['excluded'],1)
        self.assertEqual(m['turnoverCny']['value'],3)
        self.assertEqual(p['details']['distribution'][3]['count'],1)
    def test_missing_history_is_null_not_zero(self):
        p=self.build([self.stock('000001.SZ',1)])
        m=self.metrics(p)
        self.assertIsNone(m['ma60Share']['value'])
        self.assertIsNone(m['dailyVolumeRatio20']['value'])
        self.assertTrue(m['ma60Share']['reason'])
    def test_breakout_uses_prior_window_and_daily_date(self):
        from datetime import date,timedelta
        hist=[{'thscode':'000001.SZ','date':(date(2026,11,25)-timedelta(days=60-i)).isoformat(),'close':float(i+1),'turnover':1e8,'volume':100} for i in range(61)]
        p=self.build([self.stock('000001.SZ',1)],hist)
        m=self.metrics(p)
        self.assertEqual(m['high60Share']['value'],100)
        self.assertEqual(m['ma60Share']['date'],'2026-11-25')
        self.assertEqual(m['ma60Share']['sample'],1)
        self.assertEqual(m['dailyVolumeRatio20']['value'],1)
    def test_incomplete_universe_rejected(self):
        s=self.snapshot([self.stock('000001.SZ',1)]);s['total']=2
        with self.assertRaises(ObservationError):
            derive_observation(s,[],{},[],[],{}, {},calendar_days=self.calendar(),previous_date='2026-11-25',observed_at='2026-11-26T06:30:00+00:00')
    def test_duplicate_identity_rejected(self):
        r=self.stock('000001.SZ',1)
        with self.assertRaises(ObservationError): self.build([r,r])
    def test_missing_session_excluded_from_trend_sample(self):
        from datetime import date,timedelta
        hist=[]
        for i in range(61):
            d=(date(2026,11,25)-timedelta(days=60-i)).isoformat()
            for code in ['000001.SZ','000002.SZ']:
                if code=='000002.SZ' and i==59:continue
                hist.append({'thscode':code,'date':d,'close':float(i+1),'turnover':1e8})
        m=self.metrics(self.build([self.stock('000001.SZ',1),self.stock('000002.SZ',1)],hist))
        self.assertEqual(m['ma20Share']['sample'],1)
        self.assertEqual(m['dailyVolumeRatio20']['sample'],1)
    def test_pool_overlap_does_not_change_statistics(self):
        p=self.build([self.stock('000001.SZ',1)])
        self.assertEqual(p['details']['relay']['touchedCount'],10)
        self.assertEqual(self.metrics(p)['sealRate']['value'],60)
    def test_dragon_org_net_is_not_overall_net(self):
        # The public aggregate must never call the whole-board net an institutional net.
        from tools.market_dashboard.market_observation_data import derive_observation
        p=derive_observation(self.snapshot([self.stock('000001.SZ',1)]),[],{'trade_date':'2026-11-26','timestamp':1795674575000},[],[],{'trade_date':'2026-11-25','timestamp':1795536000000,'stock_items':[{'thscode':'000001.SZ','name':'证券','net_value':1000,'org_net_value':-20,'buy_value':2000,'sell_value':1000,'range_days':3}]},{'item':[]},calendar_days=self.calendar(),previous_date='2026-11-25',observed_at='2026-11-26T06:30:00+00:00')
        self.assertEqual(p['details']['dragonTiger']['rows'][0]['netCny'],-20)
        self.assertEqual(p['details']['dragonTiger']['rows'][0]['rangeDays'],3)
    def test_empty_market_retains_missing_values(self):
        p=self.build([])
        for g in p['groups'][:3]:
            for m in g['metrics']:
                self.assertIsNone(m['value'])
                self.assertTrue(m['reason'])
        self.assertEqual(p['scope']['active'],0)
    def test_stale_last_security_close_is_excluded(self):
        from datetime import date,timedelta
        hist=[{'thscode':'000001.SZ','date':(date(2026,11,24)-timedelta(days=60-i)).isoformat(),'close':float(i+1),'turnover':1e8} for i in range(61)]
        p=self.build([self.stock('000001.SZ',1)],hist)
        self.assertEqual(p['scope']['historyMatched'],0)
        self.assertIsNone(self.metrics(p)['ma20Share']['value'])

    def test_authoritative_calendar_detects_session_missing_for_every_stock(self):
        hist=[{'thscode':'000001.SZ','date':d,'close':1.0,'turnover':1e8} for d in self.calendar() if d != self.calendar()[-2]]
        m=self.metrics(self.build([self.stock('000001.SZ',1)],hist))
        self.assertIsNone(m['ma20Share']['value'])
        self.assertEqual(m['high60Share']['sample'],0)
        self.assertIsNone(m['dailyVolumePercentile']['value'])
    def test_different_missing_days_never_create_zero_sample_percentile(self):
        hist=[]
        for code,missing in [('000001.SZ',-2),('000002.SZ',-3)]:
            for d in self.calendar()[-62:]:
                if d != self.calendar()[missing]:
                    hist.append({'thscode':code,'date':d,'close':1.0,'turnover':1e8})
        m=self.metrics(self.build([self.stock('000001.SZ',1),self.stock('000002.SZ',1)],hist))
        self.assertEqual(m['dailyVolumePercentile']['sample'],0)
        self.assertIsNone(m['dailyVolumePercentile']['value'])
        self.assertTrue(m['dailyVolumePercentile']['reason'])
    def test_calendar_is_required(self):
        with self.assertRaises(ObservationError): self.build([],calendar=[])
    def test_holiday_fetches_calendar_before_any_quotes(self):
        from unittest.mock import patch,MagicMock
        from datetime import datetime,timezone
        from pathlib import Path
        from tools.market_dashboard.market_observation_data import collect_observation
        client=MagicMock();client.get.return_value={'item':[{'date_ms':1795536000000}]}
        with patch('tools.market_dashboard.market_observation_data.Rest',return_value=client):
            with self.assertRaisesRegex(ObservationError,'NON_TRADING_DAY'):
                collect_observation(state_root=Path('/tmp'),project_root=Path('/tmp'),now=datetime(2026,11,28,tzinfo=timezone.utc))
        client.get.assert_called_once_with('calendar/trading-days')

    def test_no_touched_limit_has_no_seal_rate(self):
        p=derive_observation(self.snapshot([self.stock('000001.SZ',1)]),[],{'trade_date':'2026-11-26','timestamp':1795674575000,'seal_rate':0,'limit_up_stock_count':0,'open_stock_count':0,'touched_limit_up_stock_count':0},[],[],{'trade_date':'2026-11-25','stock_items':[]},{'item':[]},calendar_days=self.calendar(),previous_date='2026-11-25',observed_at='2026-11-26T06:30:00+00:00')
        self.assertEqual(p['details']['relay']['upCount'],0)
        self.assertIsNone(self.metrics(p)['sealRate']['value'])
