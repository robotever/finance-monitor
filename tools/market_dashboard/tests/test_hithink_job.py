"""Scheduling, private state and completeness contracts for the Hithink producer."""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from tools.market_dashboard import hithink_job as job
from tools.market_dashboard.hithink_cli import SHANGHAI, HithinkError

class HithinkJobTests(unittest.TestCase):
    def test_official_close_persists_all_480_breadth_rows_with_store_bound(self):
        from unittest.mock import patch
        observed=[]
        def bounded(store,rows):
            if len(rows)>250:raise ValueError('BACKFILL_TRANSACTION_TOO_LARGE')
            observed.extend(rows)
        with patch.object(job,'upsert_breadth_daily',side_effect=bounded) as write:
            job.upsert_close_breadth(object(),list(range(480)))
            self.assertEqual([len(call.args[1]) for call in write.call_args_list],[250,230])
        self.assertEqual(observed,list(range(480)))

    def test_reconstruction_syncs_missing_daily_panel_and_rejects_persistent_gap(self):
        from unittest.mock import patch
        row=SimpleNamespace(stock_id='000001.SZ',market_date='2026-11-16',close=10,previous_close=9)
        budget=SimpleNamespace(runner=lambda argv:SimpleNamespace(returncode=0,stdout='{"ok":true}'))
        client=SimpleNamespace(cli_path='/provider/cli')
        with patch('tools.market_dashboard.hithink_breadth.load_stock_panel',side_effect=[[],[row]]) as load:
            self.assertEqual(job.load_complete_close_panel(budget,client,Path('/db'),{'000001.SZ'},'2026-11-01','2026-11-16',Path('/panel')),[row])
            self.assertEqual(load.call_count,2)
        with patch('tools.market_dashboard.hithink_breadth.load_stock_panel',return_value=[]):
            with self.assertRaisesRegex(ValueError,'STOCK_DAILY_INCOMPLETE'):
                job.load_complete_close_panel(budget,client,Path('/db'),{'000001.SZ'},'2026-11-01','2026-11-16',Path('/panel'))

    def test_completed_dates_include_today_only_after_market_close(self):
        dates=['2026-11-13','2026-11-16']
        self.assertEqual(job.completed_market_dates(dates,self.stamp('14:59')),['2026-11-13'])
        self.assertEqual(job.completed_market_dates(dates,self.stamp('16:00')),dates)

    def test_official_close_batches_preserve_exact_coverage(self):
        from tools.market_dashboard.hithink_cli import IndexDailyBar
        codes=[f'881{i:03}.TI' for i in range(23)]
        class Client:
            calls=[]
            def index_history_batch(self,batch,start,end):
                self.calls.append(list(batch))
                return [IndexDailyBar(code,'2026-11-16',1,1,1,1,1,1) for code in batch]
        client=Client();rows=job.official_close_bars(client,codes,'2026-11-16')
        self.assertEqual(len(rows),23);self.assertEqual([len(x) for x in client.calls],[10,10,3])
        client.index_history_batch=lambda *a: []
        with self.assertRaisesRegex(HithinkError,'OFFICIAL_CLOSE_UNVERIFIED'):
            job.official_close_bars(client,codes,'2026-11-16')

    def public_row(self,market_date='2026-11-16'):
        return dict(id='881001.TI',name='fixture',universe='industry',strength=55,opportunity=44,risk=33,
            completeness=80,ranks={'strength':1,'opportunity':1,'risk':1},heatState=None,coldStart=False,
            validCloses=250,improvementEvidence=2,membershipMode='point_in_time_snapshot',missing=[],
            marketDate=market_date,**job._VERSIONS)

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

    def test_unavailable_quote_does_not_abort_shared_snapshot_or_count_as_decline(self):
        from tools.market_dashboard.hithink_cli import UnavailableStockSnapshot, Membership
        class Client:
            def stock_snapshots(self,codes):
                return [SimpleNamespace(code='000001.SZ', timestamp_ms=1000,last_price=11,prev_price=10,volume=10,turnover=100),
                    UnavailableStockSnapshot('000002.SZ',1000,('last_price',))]
        shared=job.collect_stock_snapshot(Client(),['000001.SZ','000002.SZ'])
        self.assertEqual(set(shared),{'000001.SZ'})
        members=[Membership('881001.TI',c,1000) for c in ('000001.SZ','000002.SZ')]
        breadth=job._live_breadth(members,shared,'2026-11-17','2026-11-17',1000)
        self.assertEqual(breadth['total_count'],2)
        self.assertEqual(breadth['valid_count'],1)
        self.assertEqual(breadth['declining_count'],0)

    def test_one_success_per_bucket_and_failed_cycle_does_not_advance(self):
        with tempfile.TemporaryDirectory() as directory:
            args=SimpleNamespace(state_root=Path(directory).resolve(),now=self.stamp('10:00'))
            calls=[]
            deps={'calendar':['2026-11-16'],'produce':lambda *a: calls.append(1) or {'rows':[self.public_row()]}}
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
            with patch.object(job,'build_universe',return_value=universe),patch.object(job.time,'time',return_value=(stamp-60000)/1000):
                result=job.run_hithink_cycle(args,{'calendar':['2026-11-13','2026-11-16'],'client':client})
            self.assertEqual(result.status,'success')
            self.assertEqual(client.stock_calls,1)
            import json
            payload=json.loads((root/'hithink-live/latest.json').read_text())
            self.assertEqual(len(payload['rows']),2)
            self.assertEqual(payload['unsupportedStockCount'],1)
            self.assertFalse(payload['officialClose'])
            self.assertEqual(payload['rows'][0]['session'],'intraday')
            self.assertGreaterEqual(datetime.fromisoformat(payload['rows'][0]['observedAt']).timestamp()*1000,stamp)
            self.assertEqual(set(payload['rows'][0]['ranks']),{'strength','opportunity','risk'})
            store=open_store(root/'sector-history.sqlite3')
            self.assertEqual(store.execute('select count(*) from sector_features_intraday').fetchone()[0],2)
            self.assertEqual(store.execute('select count(*) from stock_market_snapshot').fetchone()[0],1)
            self.assertEqual(store.execute('select count(*) from sector_index_intraday').fetchone()[0],2)
            store.close()
            for stale_time in ('14:00','15:05'):
                args.now=self.stamp(stale_time)
                with patch.object(job,'build_universe',return_value=universe):
                    stale=job.run_hithink_cycle(args,{'calendar':['2026-11-13','2026-11-16'],'client':client})
                self.assertEqual(stale.status,'failed')
            self.assertEqual(json.loads((root/'hithink-live/state.json').read_text())['completed'],['2026-11-16:10:00'])


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
            deps={'calendar':['2026-11-13','2026-11-16'],'produce':lambda *a:{'rows':[self.public_row('2026-11-13')],'officialClose':True,'marketDate':'2026-11-13'}}
            self.assertEqual(job.run_hithink_cycle(args,deps).status,'success')
            args.now=self.stamp('10:00');deps['produce']=lambda *a:{'rows':[self.public_row()],'officialClose':False,'marketDate':'2026-11-16'}
            self.assertEqual(job.run_hithink_cycle(args,deps).status,'success')
            history=json.loads((root/'hithink-live/close-history.json').read_text())
            self.assertEqual(history[0]['marketDate'],'2026-11-13')


    def test_stale_afternoon_and_morning_close_sources_fail_without_marker(self):
        for collection,source in [('14:00','09:30'),('15:05','09:30'),('15:01','14:59')]:
            with self.subTest(collection=collection,source=source),tempfile.TemporaryDirectory() as directory:
                now=self.stamp(collection); bucket=job.cycle_bucket(now,['2026-11-16'])
                def produce(*a):
                    job.validate_snapshot_freshness([int(self.stamp(source).timestamp()*1000)],bucket,now)
                    return {'rows':[],'officialClose':bucket.official_close}
                root=Path(directory).resolve()
                result=job.run_hithink_cycle(SimpleNamespace(state_root=root,now=now),{'calendar':['2026-11-16'],'produce':produce})
                self.assertEqual(result.status,'failed')
                self.assertFalse((root/'hithink-live/state.json').exists())
                self.assertFalse((root/'hithink-live/latest.json').exists())

    def test_snapshot_freshness_bucket_and_close_cutoff_boundaries(self):
        now=self.stamp('14:05');bucket=job.cycle_bucket(now,['2026-11-16'])
        job.validate_snapshot_freshness([int(self.stamp('14:03').timestamp()*1000)],bucket,now)
        for value in ['14:02:59','13:59:59']:
            with self.assertRaises(ValueError):job.validate_snapshot_freshness([int(self.stamp(value).timestamp()*1000)],bucket,now)
        bucket=job.cycle_bucket(self.stamp('15:29'),['2026-11-16'])
        with self.assertRaises(ValueError):job.validate_snapshot_freshness([int(self.stamp('15:29').timestamp()*1000)],bucket,self.stamp('15:30'))


    def test_sixteen_real_scoring_cycles_reuse_close_history_without_future_leak(self):
        from tools.market_dashboard.tests.test_rotation_v4 import panel,config
        from tools.market_dashboard.rotation_v4 import build_v4_features,rank_v4_universe
        import json
        indexes,breadth=panel()
        dates=[r['market_date'] for r in indexes[-16:]]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();local=root/'hithink-live'
            for day in dates:
                now=datetime.fromisoformat(day+'T15:05').replace(tzinfo=SHANGHAI)
                args=SimpleNamespace(state_root=root,now=now)
                def produce(args,bucket,budget,client,root):
                    history=job._read(local/'close-history.json',[])
                    prior=job.prior_close_rows(history,day)
                    feature=build_v4_features(indexes,breadth,market_date=day,prior_scores=prior)
                    scored=job.score_cycle_features([feature],prior,bucket,config(),historical=True)
                    future={**scored[0],'marketDate':'2099-01-01','strength':100,'metrics':{'participation':999999}}
                    self.assertEqual(scored,job.score_cycle_features([feature],prior+[future],bucket,config(),historical=True))
                    for axis in ('strength','opportunity','risk'): scored=rank_v4_universe(scored,axis)
                    for row in scored: row['name']='fixture'
                    return {'rows':scored,'marketDate':day,'bucket':bucket.key,'historicalReconstruction':True,'officialClose':False}
                result=job.run_hithink_cycle(args,{'calendar':dates,'produce':produce})
                self.assertEqual(result.status,'success')
            row=json.loads((local/'latest.json').read_text())['rows'][0]
            self.assertEqual(row['session'],'close');self.assertFalse(row['officialClose'])
            self.assertTrue(row['historicalReconstruction']);self.assertIsNone(row['availableAt'])
            self.assertIsNotNone(row['metrics']['participationDelta5d'])
            self.assertIsNotNone(row['metrics']['strengthSlope5d'])
            self.assertEqual(row['metrics']['topDecileStreak'],15)
            self.assertEqual(row['components']['persistence']['coverage'],1)
            self.assertIsNotNone(row['components']['persistence']['value'])

    def test_legacy_close_session_recovery_preserves_arrival_and_reconstruction(self):
        row={'id':'881001.TI','marketDate':'2026-11-13','availableAt':None,'officialClose':False}
        payload={'historicalReconstruction':True,'officialClose':False,'rows':[row]}
        result=job.prior_close_rows([payload],'2026-11-16')
        self.assertEqual(result,[{**row,'session':'close','historicalReconstruction':True}])
        self.assertEqual(row,{'id':'881001.TI','marketDate':'2026-11-13','availableAt':None,'officialClose':False})
        self.assertEqual(job.prior_close_rows([payload],'2026-11-13'),[])


    def test_successful_cycle_saves_480_matching_projected_rows_and_versions(self):
        import json,hashlib
        from tools.market_dashboard.hithink_universe import load_catalog_fixture
        sectors=[*load_catalog_fixture(Path(job.__file__).parent/'fixtures/hithink/catalog-industry.json'),
                 *load_catalog_fixture(Path(job.__file__).parent/'fixtures/hithink/catalog-concept.json')]
        sectors=[s for s in sectors if s.tag!='industry' or s.code.startswith('881')]
        rows=[{**self.public_row(),'id':s.code,'name':s.name,'universe':'industry' if s.tag=='industry' else 'concept'} for s in sectors]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();args=SimpleNamespace(state_root=root,now=self.stamp('10:00'))
            result=job.run_hithink_cycle(args,{'calendar':['2026-11-16'],'produce':lambda *a:{'rows':rows}})
            self.assertEqual(result.status,'success')
            local=root/'hithink-live';chunks=json.loads((local/'publish-chunks.json').read_text())
            saved=json.loads((local/'latest.json').read_text())['rows']
            self.assertEqual(len(saved),480);self.assertEqual(len(chunks),10)
            projected=[r for c in chunks for r in json.loads(c['rowsJson'])]
            self.assertEqual(projected,[job.public_v4_row(r) for r in saved])
            self.assertTrue(all(all(r[k]==v for k,v in job._VERSIONS.items()) for r in saved))
            self.assertTrue(all(hashlib.sha256(c['rowsJson'].encode()).hexdigest()==c['digest'] for c in chunks))
            self.assertEqual(json.loads((local/'state.json').read_text())['completed'],['2026-11-16:10:00'])

    def test_failed_projection_preserves_previous_chunks_and_success_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();args=SimpleNamespace(state_root=root,now=self.stamp('10:00'))
            deps={'calendar':['2026-11-16'],'produce':lambda *a:{'rows':[self.public_row()]}}
            self.assertEqual(job.run_hithink_cycle(args,deps).status,'success')
            local=root/'hithink-live';before={name:(local/name).read_bytes() for name in ('latest.json','publish-chunks.json','state.json')}
            args.now=self.stamp('10:15');deps['produce']=lambda *a:{'rows':[{**self.public_row(),'featureVersion':'invalid'}]}
            self.assertEqual(job.run_hithink_cycle(args,deps).status,'failed')
            self.assertEqual(before,{name:(local/name).read_bytes() for name in before})


    def test_every_artifact_write_failure_keeps_committed_bundle_and_retry_recovers(self):
        from unittest.mock import patch
        import json
        # All mutation steps, including generation allocation and final visibility.
        stages=['generation','10-15.json','10-15.chunks.json','publish-chunks.json','latest.json',
                'close-history.json','health.json','state.json','current-snapshot.json']
        for stage in stages:
            with self.subTest(stage=stage),tempfile.TemporaryDirectory() as directory:
                root=Path(directory).resolve();local=root/'hithink-live'
                args=SimpleNamespace(state_root=root,now=self.stamp('10:00'))
                deps={'calendar':['2026-11-16'],'produce':lambda *a:{'rows':[self.public_row()]}}
                self.assertEqual(job.run_hithink_cycle(args,deps).status,'success')
                prior=job.read_committed_snapshot(local)
                args.now=self.stamp('10:15');deps['produce']=lambda *a:{'rows':[{**self.public_row(),'strength':88}]}
                original=job._atomic;failed=[]
                def injected(path,value):
                    match=path.name.startswith('generation-') if stage=='generation' else path.name.endswith(stage)
                    if match and not failed:
                        failed.append(1);raise OSError('injected write failure')
                    return original(path,value)
                with patch.object(job,'_atomic',side_effect=injected):
                    result=job.run_hithink_cycle(args,deps)
                self.assertEqual(result.status,'failed');self.assertTrue(failed)
                self.assertEqual(job.read_committed_snapshot(local),prior)
                self.assertEqual(job.run_hithink_cycle(args,deps).status,'success')
                after=job.read_committed_snapshot(local)
                self.assertEqual(after['payload']['rows'][0]['strength'],88)
                self.assertEqual(json.loads(after['chunks'][0]['rowsJson'])[0]['strength'],88)
                self.assertIn('2026-11-16:10:15',after['state']['completed'])
                self.assertEqual(job.run_hithink_cycle(args,deps).status,'already_complete')
                self.assertEqual(job.read_committed_snapshot(local),after)


    def test_interrupted_alias_write_cannot_mix_authoritative_rows_or_block_retry(self):
        from unittest.mock import patch
        import json
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();local=root/'hithink-live'
            args=SimpleNamespace(state_root=root,now=self.stamp('10:00'))
            deps={'calendar':['2026-11-16'],'produce':lambda *a:{'rows':[self.public_row()]}}
            self.assertEqual(job.run_hithink_cycle(args,deps).status,'success')
            before=job.read_committed_snapshot(local)
            args.now=self.stamp('10:15');deps['produce']=lambda *a:{'rows':[{**self.public_row(),'strength':88}]}
            atomic=job._atomic
            def interrupted(path,value):
                if path.name=='latest.json': raise KeyboardInterrupt()
                return atomic(path,value)
            with patch.object(job,'_atomic',side_effect=interrupted),self.assertRaises(KeyboardInterrupt):
                job.run_hithink_cycle(args,deps)
            # The uncommitted aliases disagree; readers must use the bundle.
            self.assertEqual(json.loads((local/'latest.json').read_text())['rows'][0]['strength'],55)
            self.assertEqual(json.loads(json.loads((local/'publish-chunks.json').read_text())[0]['rowsJson'])[0]['strength'],88)
            self.assertEqual(job.read_committed_snapshot(local),before)
            self.assertEqual(job.run_hithink_cycle(args,deps).status,'success')
            self.assertEqual(job.read_committed_snapshot(local)['payload']['rows'][0]['strength'],88)

if __name__=='__main__': unittest.main()
