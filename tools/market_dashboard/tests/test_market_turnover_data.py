import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path
import json
import hashlib
import os
from datetime import datetime
from tools.market_dashboard import market_turnover_data as t


class TurnoverTests(unittest.TestCase):
    @staticmethod
    def native_fixture():
        names=['全部A股(板块)','上证A股(板块)','深证A股(板块)','全部创业板(板块)','科创板(板块)']
        values=[['300','310'],['100','110'],['150','150'],['40','41'],['30','31']]
        raw={name:value for name,value in zip(names,values)};raw['headName']=['2026-11-25','2026-11-24']
        field=dict(returnSourceCode='TVAL',returnSourceName='成交额(合计)_板块',dateGranularity='DAY',unit='1',
                   startDate='2026-11-24 00:00:00',endDate='2026-11-25 00:00:00')
        return {'dataTableDTOList':[dict(field=field,rawTable=raw)]}

    def test_native_market_totals_use_exact_raw_cny_and_derive_beijing(self):
        rows=t.parse_mx_history(self.native_fixture(),'2026-11-24','2026-11-25',['2026-11-24','2026-11-25'])
        self.assertEqual([r['date'] for r in rows],['2026-11-24','2026-11-25'])
        self.assertEqual(rows[-1],dict(date='2026-11-25',all=300,sh=100,sz=150,chinext=40,star=30,bj=50))

    def test_native_history_rejects_wrong_indicator_frequency_unit_or_missing_market(self):
        for key,value in [('returnSourceCode','OTHER'),('returnSourceName','个股成交额'),('dateGranularity','MONTH'),('unit','100000000')]:
            raw=self.native_fixture();raw['dataTableDTOList'][0]['field'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                t.parse_mx_history(raw,'2026-11-24','2026-11-25',['2026-11-24','2026-11-25'])
        raw=self.native_fixture();del raw['dataTableDTOList'][0]['rawTable']['科创板(板块)']
        with self.assertRaises(ValueError):t.parse_mx_history(raw,'2026-11-24','2026-11-25',['2026-11-24','2026-11-25'])

    def test_native_history_rejects_duplicate_unordered_missing_calendar_or_nonfinite_values(self):
        for dates in [['2026-11-25','2026-11-25'],['2026-11-24','2026-11-25'],['2026-11-25']]:
            raw=self.native_fixture();raw['dataTableDTOList'][0]['rawTable']['headName']=dates
            with self.subTest(dates=dates),self.assertRaises(ValueError):
                t.parse_mx_history(raw,'2026-11-24','2026-11-25',['2026-11-24','2026-11-25'])
        raw=self.native_fixture();raw['dataTableDTOList'][0]['rawTable']['全部A股(板块)'][0]='NaN'
        with self.assertRaises(ValueError):t.parse_mx_history(raw,'2026-11-24','2026-11-25',['2026-11-24','2026-11-25'])

    def test_native_completed_window_cache_preserves_capture_and_avoids_credentials(self):
        with TemporaryDirectory() as directory:
            cache=Path(directory);rawcache=cache/'mx-raw';rawcache.mkdir()
            question=t.mx_history_question('2026-11-24','2026-11-25')
            path=rawcache/(hashlib.sha256(('query'+question).encode()).hexdigest()+'.json')
            path.write_text(json.dumps(self.native_fixture(),ensure_ascii=False))
            captured=datetime.fromisoformat('2026-11-26T18:15:12+08:00').timestamp();os.utime(path,(captured,captured))
            with patch.object(t,'credential',side_effect=AssertionError('credential should not be needed')):
                first=t._history_native(Path(directory),cache,'2026-11-24','2026-11-25',['2026-11-24','2026-11-25'])
                path.unlink()
                second=t._history_native(Path(directory),cache,'2026-11-24','2026-11-25',['2026-11-24','2026-11-25'])
            self.assertEqual(first,second)
            self.assertEqual(first[1],'2026-11-26T18:15:12+08:00')

    def test_network_failure_can_reuse_real_private_capture(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);(root/'test.json').write_text(json.dumps({'real':'capture'}))
            with patch.object(t.urllib.request,'urlopen',side_effect=OSError('offline')):
                self.assertEqual(t._fetch('https://example.test/',root,'test'),{'real':'capture'})

    def test_snapshot_includes_st_bj_and_cdr_and_subsets(self):
        rows=[{'thscode':s,'turnover':v} for s,v in [('600001.SH',10),('689009.SH',20),('300001.SZ',30),('000001.SZ',40),('920001.BJ',50)]]
        self.assertEqual(t.snapshot_totals(rows),dict(all=150,sh=30,sz=70,chinext=30,star=20,bj=50))
        rows[0]['turnover']=None
        self.assertIsNone(t.snapshot_totals(rows)['sh'])

    def test_unquoted_identity_does_not_invalidate_real_traded_total(self):
        rows=[{'thscode':'600001.SH','turnover':10},
              {'thscode':'301661.SZ','turnover':None,'last_price':None,'prev_price':97.53,'volume':None}]
        self.assertEqual(t.snapshot_totals(rows)['all'],10)

    def test_tencent_parser_uses_cumulative_cny_and_last_duplicate(self):
        p={'data':{'x':{'data':[{'date':'20261125','data':['0930 1 2 3','1500 1 2 100','1500 1 2 101']} ]}}}
        self.assertEqual(t.parse_tencent(p,'x')['2026-11-25'],{'09:30':3,'15:00':101})
        p['data']['x']['data'][0]['data']=['0930 1 2 3','0931 1 2 2']
        with self.assertRaises(ValueError):t.parse_tencent(p,'x')

    def test_irrelevant_old_minute_corruption_does_not_invalidate_current_pair(self):
        raw={'data':{'x':{'data':[{'date':'20261124','data':['0930 1 2 9','0931 1 2 2']},
                                  {'date':'20261125','data':['1500 1 2 100']}]}}}
        self.assertEqual(t.parse_tencent(raw,'x',dates={'2026-11-25'}),{'2026-11-25':{'15:00':100}})

    def test_eastmoney_parser_sums_minute_amount_not_price_or_volume(self):
        p={'data':{'trends':['2026-11-25 09:30,1,2,3,4,5,6,7','2026-11-25 09:31,1,2,3,4,5,8,7']}}
        self.assertEqual(t.parse_eastmoney(p)['2026-11-25']['09:31'],14)

    def test_eastmoney_missing_minute_fails_instead_of_partial_cumulative_sum(self):
        raw={'data':{'trends':['2026-11-25 09:30,1,2,3,4,5,6,7','2026-11-25 09:32,1,2,3,4,5,8,7']}}
        with self.assertRaises(ValueError):t.parse_eastmoney(raw)

    def test_no_shared_cutoff_keeps_all_changes_empty(self):
        history=[dict(date='2026-11-25',sh=100,sz=100)]
        curves={g:{'2026-11-25':{tm:10,'15:00':100},'2026-11-26':{tm:20}} for g,tm in [('sh','09:30'),('sz','09:31')]}
        p=t.build_turnover([], '2026-11-26T14:00:00+08:00','2026-11-25',['2026-11-25'],history,curves)
        self.assertIsNone(p['comparisonTime'])
        self.assertTrue(all(r['changePct'] is None and r['reason'] for r in p['rows']))

    def test_compare_requires_previous_complete_verified_day_and_exact_common_time(self):
        curve={'2026-11-25':{'09:30':10,'14:59':90,'15:00':100},'2026-11-26':{'09:30':20,'14:59':110}}
        result=t.same_time(curve,'2026-11-26','2026-11-25',100,'14:59')
        self.assertEqual(result,(110,90,'14:59'))
        with self.assertRaisesRegex(ValueError,'范围'):
            t.same_time(curve,'2026-11-26','2026-11-25',110,'14:59')
        del curve['2026-11-25']['15:00']
        with self.assertRaises(ValueError):t.same_time(curve,'2026-11-26','2026-11-25',100,'14:59')

    def test_common_curve_sum_requires_every_supplement(self):
        a={'2026-11-26':{'09:30':1,'09:31':2}}
        b={'2026-11-26':{'09:31':3}}
        self.assertEqual(t.sum_curves([a,b]),{'2026-11-26':{'09:31':5}})
        self.assertEqual(t.sum_curves([a,{}]),{})

    def test_build_keeps_real_snapshot_when_same_time_is_unavailable(self):
        rows=[{'thscode':s,'turnover':v} for s,v in [('600001.SH',10),('688001.SH',20),('300001.SZ',30),('000001.SZ',40),('920001.BJ',50)]]
        p=t.build_turnover(rows,'2026-11-26T14:59:22+08:00','2026-11-25',['2026-11-24','2026-11-25'],[],{})
        self.assertEqual(p['rows'][0]['currentCny'],150)
        self.assertIsNone(p['rows'][0]['changePct'])
        self.assertTrue(p['rows'][0]['reason'])
        self.assertTrue(all(x['all'] is None for x in p['history']['points']))

    def test_after_close_collection_does_not_need_minute_network_or_credentials(self):
        with TemporaryDirectory() as directory:
            with patch.object(t,'_history_native',return_value=([dict(date='2026-11-25',all=100,sh=100)],'2026-11-26T15:40:00+08:00')), \
                 patch.object(t,'_fetch',side_effect=AssertionError('unnecessary minute request')):
                p=t.collect_turnover(snapshot_rows=[{'thscode':'600001.SH','turnover':120}],
                   snapshot_at='2026-11-26T16:00:00+08:00',previous_date='2026-11-25',calendar_days=['2026-11-25'],
                   state_root=Path(directory),project_root=Path(directory))
            self.assertEqual(len(p['sources']),2)
            self.assertEqual(p['rows'][0]['comparisonMode'],'daily-close')

    def test_after_close_uses_complete_daily_reference_with_honest_date(self):
        history=[dict(date='2026-11-25',all=100,sh=100,sz=None,chinext=None,star=None)]
        rows=[{'thscode':'600001.SH','turnover':120}]
        p=t.build_turnover(rows,'2026-11-26T15:30:00+08:00','2026-11-25',['2026-11-25'],history,{})
        row=p['rows'][0]
        self.assertEqual(row['comparisonMode'],'daily-close')
        self.assertEqual(row['currentAsOf'],'2026-11-26T15:30:00+08:00')
        self.assertEqual(row['comparisonAsOf'],'2026-11-25')
        self.assertEqual(row['previousSameTimeCny'],100)
        self.assertEqual(row['changePct'],20)
        self.assertIsNone(p['comparisonTime'])
        self.assertIsNone(p['rows'][2]['changePct'])

    def test_intraday_and_1529_never_use_previous_full_day_as_same_time(self):
        for clock in ['14:30','15:29']:
            p=t.build_turnover([{'thscode':'600001.SH','turnover':120}],f'2026-11-26T{clock}:00+08:00',
                 '2026-11-25',['2026-11-25'],[dict(date='2026-11-25',all=100,sh=100)],{})
            self.assertIsNone(p['rows'][0]['changePct'])
            self.assertEqual(p['rows'][0]['comparisonMode'],'unavailable')

    def test_build_uses_same_cutoff_for_total_and_never_snapshot_for_change(self):
        days=['2026-11-25','2026-11-26']; curves={}
        totals=dict(all=300,sh=100,sz=100,bj=100,chinext=100,star=100)
        history=[dict(date=days[0],**totals)]
        for group in ['sh','sz','bj','chinext','star']:
            curves[group]={days[0]:{'14:59':80,'15:00':100},days[1]:{'14:59':90,'15:00':120}}
        rows=[{'thscode':'600001.SH','turnover':999}]
        p=t.build_turnover(rows,days[1]+'T14:59:22+08:00',days[0],days,history,curves)
        self.assertEqual(p['comparisonTime'],'14:59')
        self.assertEqual(p['rows'][0]['currentCny'],270)
        self.assertEqual(p['rows'][0]['previousSameTimeCny'],240)
        self.assertAlmostEqual(p['rows'][0]['changePct'],12.5)
        self.assertEqual(p['rows'][0]['currentAsOf'],days[1]+'T14:59:00+08:00')

if __name__=='__main__':unittest.main()
