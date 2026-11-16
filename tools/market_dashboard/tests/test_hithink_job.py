"""Scheduling, private state and completeness contracts for the Hithink producer."""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from tools.market_dashboard import hithink_job as job
from tools.market_dashboard.hithink_cli import SHANGHAI, HithinkError

class HithinkJobTests(unittest.TestCase):
    def stamp(self, time, day='2026-11-16'):
        return datetime.fromisoformat(day+'T'+time).replace(tzinfo=SHANGHAI)

    def test_sessions_holidays_lunch_close_and_timezone(self):
        days=['2026-11-13','2026-11-16']
        for t in ['09:29','11:31','12:30','15:31']:
            self.assertIsNone(job.cycle_bucket(self.stamp(t),days))
        self.assertEqual(job.cycle_bucket(self.stamp('10:07'),days).key,'2026-11-16:10:00')
        self.assertEqual(job.cycle_bucket(self.stamp('15:29'),days).key,'2026-11-16:close')
        self.assertIsNone(job.cycle_bucket(self.stamp('10:00','2026-11-15'),days))
        self.assertTrue(job.cycle_bucket(self.stamp('15:00'),days).official_close)

    def test_calendar_is_required_and_never_weekday_guessed(self):
        with self.assertRaises(ValueError): job.cycle_bucket(self.stamp('10:00'),[])
        self.assertIsNone(job.cycle_bucket(self.stamp('10:00'),['2026-11-13']))

    def test_snapshot_chunks_are_exact_and_reused(self):
        class Client:
            calls=[]
            def stock_snapshots(self,codes):
                self.calls.append(codes)
                return [SimpleNamespace(code=c,timestamp_ms=1000) for c in codes]
        c=Client(); rows=job.collect_stock_snapshot(c,['000001.SZ']*3+['000002.SZ'],2)
        self.assertEqual(set(rows),{'000001.SZ','000002.SZ'})
        self.assertEqual(len(c.calls),1)
        c.stock_snapshots=lambda codes: [SimpleNamespace(code=codes[0],timestamp_ms=1000)]
        with self.assertRaises(HithinkError): job.collect_stock_snapshot(c,['000001.SZ','000002.SZ'],2)

    def test_budget_stops_before_deadline(self):
        now=[0.0]; b=job.CycleBudget(2,10,clock=lambda:now[0])
        b.before_call(); b.before_call()
        with self.assertRaises(TimeoutError): b.before_call()
        b=job.CycleBudget(4,10,clock=lambda:now[0]); now[0]=10
        with self.assertRaises(TimeoutError): b.before_call()

    def test_one_success_per_bucket_and_failed_cycle_does_not_advance(self):
        with tempfile.TemporaryDirectory() as directory:
            args=SimpleNamespace(state_root=Path(directory).resolve(),now=self.stamp('10:00'))
            calls=[]
            deps={'calendar':['2026-11-16'],'produce':lambda *a: calls.append(1) or {'rows':[{'id':'x'}]}}
            first=job.run_hithink_cycle(args,deps)
            self.assertEqual(first.status,'success'); self.assertFalse(first.published)
            self.assertEqual(job.run_hithink_cycle(args,deps).status,'already_complete')
            self.assertEqual(len(calls),1)
            args.now=self.stamp('10:15')
            deps['produce']=lambda *a: (_ for _ in ()).throw(ValueError('secret provider token'))
            result=job.run_hithink_cycle(args,deps)
            self.assertEqual(result.status,'failed')
            self.assertNotIn('secret', (Path(directory).resolve()/'hithink-live'/'health.json').read_text())
            self.assertNotIn('10:15',(Path(directory).resolve()/'hithink-live'/'state.json').read_text())
            self.assertFalse((Path(directory).resolve()/'hithink-live-priority').exists())

    def test_shared_writer_busy_and_priority_lifecycle(self):
        from tools.market_dashboard.hithink_store import store_write_lock
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve(); args=SimpleNamespace(state_root=root,now=self.stamp('10:00'))
            def produce(*a):
                self.assertTrue((root/'hithink-live-priority').exists())
                return {'rows':[]}
            with store_write_lock(root):
                result=job.run_hithink_cycle(args,{'calendar':['2026-11-16'],'produce':produce})
            self.assertEqual(result.status,'failed')
            self.assertFalse((root/'hithink-live'/'state.json').exists())

    def test_expired_cycle_cannot_write_success(self):
        with tempfile.TemporaryDirectory() as directory:
            ticks=[0.]
            def produce(*a): ticks[0]=901.; return {'rows':[]}
            result=job.run_hithink_cycle(SimpleNamespace(state_root=Path(directory).resolve(),now=self.stamp('10:00')),
                {'calendar':['2026-11-16'],'produce':produce,'clock':lambda:ticks[0]})
            self.assertEqual(result.status,'failed')
            self.assertFalse((Path(directory).resolve()/'hithink-live'/'state.json').exists())


    def test_live_ratio_breadth_keeps_missing_volume_baseline(self):
        from tools.market_dashboard.hithink_cli import Membership
        members=[Membership('881001.TI','000001.SZ',1),Membership('881001.TI','000002.SZ',1)]
        snapshot={'000001.SZ':SimpleNamespace(last_price=103,prev_price=100,volume=100,turnover=1000),
                  '000002.SZ':SimpleNamespace(last_price=99,prev_price=100,volume=200,turnover=500)}
        row=job._live_breadth(members,snapshot,'2026-11-16','2026-11-16',1)
        self.assertEqual(row['advancing_count'],1)
        self.assertEqual(row['declining_count'],1)
        self.assertAlmostEqual(row['median_return'],.01)
        self.assertIsNone(row['volume_expansion_share'])

    def test_atomic_rewrite_removes_old_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory).resolve()/'value.json'
            (path.parent/'value.json.tmp').write_text('X'*500)
            job._atomic(path,{'ok':True})
            import json
            self.assertEqual(json.loads(path.read_text()),{'ok':True})


    def test_real_calendar_date_ms_shape(self):
        class Client:
            def _call(self,*a):
                return {'item':[{'date':'20261116','date_ms':1794758400000}], 'timestamp':1794800000000}
        self.assertEqual(job._official_calendar(Client()),['2026-11-16'])


    def test_fixture_full_live_cycle_scores_and_persists_intraday_features(self):
        from unittest.mock import patch
        from datetime import timedelta
        from tools.market_dashboard.hithink_cli import SectorDefinition,Membership,IndexDailyBar,IndexSnapshot,StockSnapshot
        from tools.market_dashboard.hithink_store import open_store,migrate_store,replace_catalog,upsert_index_daily
        industry=SectorDefinition('881001.TI','fixture industry','industry')
        concept=SectorDefinition('885001.TI','fixture concept','cn_concept')
        universe=SimpleNamespace(industries=(industry,),concepts=(concept,),core_ids=(),catalog_digest='fixture')
        stamp=int(self.stamp('10:00').timestamp()*1000)
        class Client:
            cli_path=job.CLI
            stock_calls=0
            def catalog(self,tag): return (industry,) if tag=='industry' else (concept,)
            def constituents(self,code): return (Membership(code,'000001.SZ',stamp),Membership(code,'430001.NQ',stamp))
            def index_snapshots(self,codes):
                return [IndexSnapshot(c,stamp,125,1,.8,124,126,123,124,1000,10000) for c in codes]
            def stock_snapshots(self,codes):
                self.stock_calls+=1
                return [StockSnapshot(c,stamp,101,1,1,100,102,99,100,100,1000) for c in codes]
            def index_history(self,code,start,end):
                return [IndexDailyBar(code,'2026-11-13',100,100,100,100,100,1000)]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();store=open_store(root/'sector-history.sqlite3');migrate_store(store)
            replace_catalog(store,[industry,concept],observed_at_ms=stamp)
            rows=[]
            for i in range(60):
                day=(self.stamp('10:00').date()-timedelta(days=90-i)).isoformat()
                for sector in (industry,concept): rows.append(IndexDailyBar(sector.code,day,100+i,100+i,100+i,100+i,100,1000))
            upsert_index_daily(store,rows,observed_at_ms=stamp);store.close()
            args=SimpleNamespace(state_root=root,now=self.stamp('10:00'));client=Client()
            with patch.object(job,'build_universe',return_value=universe):
                result=job.run_hithink_cycle(args,{'calendar':['2026-11-13','2026-11-16'],'client':client})
            self.assertEqual(result.status,'success')
            self.assertEqual(client.stock_calls,1)
            import json
            payload=json.loads((root/'hithink-live/latest.json').read_text())
            self.assertEqual(len(payload['rows']),2)
            self.assertEqual(payload['unsupportedStockCount'],1)
            self.assertFalse(payload['officialClose'])
            self.assertEqual(set(payload['rows'][0]['ranks']),{'strength','opportunity','risk'})
            store=open_store(root/'sector-history.sqlite3')
            self.assertEqual(store.execute('select count(*) from sector_features_intraday').fetchone()[0],2)
            self.assertEqual(store.execute('select count(*) from stock_market_snapshot').fetchone()[0],1)
            store.close()


    def test_shadow_installer_requires_its_producer_and_prepares_separate_label(self):
        from tools.market_dashboard.tests.test_operations import OperationsTests,LABEL
        import plistlib
        fixture=OperationsTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.copy_ops();fixture.make_checkout();fixture.trap_launchctl()
        failed=fixture.execute('install-market-dashboard-service.sh','--hithink-shadow','--prepare')
        self.assertNotEqual(failed.returncode,0)
        (fixture.repo/'tools/market_dashboard/hithink_job.py').touch()
        ready=fixture.execute('install-market-dashboard-service.sh','--hithink-shadow','--prepare')
        self.assertEqual(ready.returncode,0,ready.stderr)
        agents=Path(fixture.env['HOME'])/'Library/LaunchAgents'
        plist=plistlib.loads((agents/(LABEL+'.hithink-shadow.plist')).read_bytes())
        self.assertEqual(plist['Label'],LABEL+'.hithink-shadow')
        self.assertEqual(plist['ProgramArguments'][-1],'--hithink-shadow')
        self.assertFalse((agents/(LABEL+'.plist')).exists())
        self.assertFalse((Path(fixture.env['HOME'])/'launchctl-calls').exists())


    def test_daily_close_history_survives_subsequent_intraday_payload(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();args=SimpleNamespace(state_root=root,now=self.stamp('15:05','2026-11-13'))
            deps={'calendar':['2026-11-13','2026-11-16'],'produce':lambda *a:{'rows':[{'id':'one','marketDate':'2026-11-13'}],'officialClose':True,'marketDate':'2026-11-13'}}
            self.assertEqual(job.run_hithink_cycle(args,deps).status,'success')
            args.now=self.stamp('10:00');deps['produce']=lambda *a:{'rows':[{'id':'two'}],'officialClose':False,'marketDate':'2026-11-16'}
            self.assertEqual(job.run_hithink_cycle(args,deps).status,'success')
            history=json.loads((root/'hithink-live/close-history.json').read_text())
            self.assertEqual(history[0]['marketDate'],'2026-11-13')

if __name__=='__main__': unittest.main()
