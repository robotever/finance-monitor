from argparse import Namespace
import json
from pathlib import Path
import tempfile
import sqlite3
import os
import fcntl
import unittest
from unittest.mock import patch

from tools.market_dashboard.hithink_job import HithinkJobResult
from tools.market_dashboard.sector_live_service import run_service,archive_stock_close


class LiveServiceTests(unittest.TestCase):
    def test_collector_progresses_while_publisher_lock_is_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fd=os.open(root/'sector-live-service.lock',os.O_RDWR|os.O_CREAT,0o600)
            try:
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                args=Namespace(state_root=root,publish_only=False,collect_only=True)
                with patch('tools.market_dashboard.sector_live_service.read_committed_snapshot',return_value={'generation':'a'*64,'payload':{'historicalReconstruction':True}}):
                    result=run_service(args,collector=lambda args:HithinkJobResult('success',row_count=480),transport=lambda body:self.fail('collector attempted publication'))
                self.assertEqual(result['status'],'success');self.assertEqual(result['collected'],480)
            finally:os.close(fd)

    def test_daily_checkpoint_compares_source_generation_not_public_identifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'hithink-live').mkdir()
            (root/'hithink-live/live-publication-checkpoint.json').write_text(json.dumps({'generation':'b'*64,'sourceGeneration':'a'*64,'storageMode':'daily-v1','activated':True}))
            with patch('tools.market_dashboard.sector_live_service.read_committed_snapshot',return_value={'generation':'a'*64,'payload':{'historicalReconstruction':True}}):
                result=run_service(Namespace(state_root=root,publish_only=True),transport=lambda body:self.fail('unchanged generation uploaded'),settings={'storageMode':'daily-v1'})
            self.assertEqual(result['generation'],'b'*64);self.assertEqual(result['status'],'already_published')
    def test_timely_close_also_archives_daily_history_once_without_rewriting_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with sqlite3.connect(root/'sector-history.sqlite3') as store:
                store.execute('CREATE TABLE sector_membership_snapshot(stock_id TEXT,sector_id TEXT,membership_date TEXT,membership_version TEXT)')
                store.execute("INSERT INTO sector_membership_snapshot VALUES('000001.SZ','881001.TI','2026-11-18','sector-membership-ths-v1')")
                store.execute("INSERT INTO sector_membership_snapshot VALUES('000002.SZ','881001.TI','2026-11-17','sector-membership-ths-v1')")
            store.close()
            calls=[]
            def load(*args):calls.append(args)
            args=Namespace(cli=str(root/'unused'),stock_db=root/'verified-stock.duckdb')
            archive_stock_close(args,root,'2026-11-18',loader=load)
            archive_stock_close(args,root,'2026-11-18',loader=load)
            self.assertEqual(len(calls),1);self.assertEqual(calls[0][4:6],('2026-11-18','2026-11-18'))
            self.assertEqual(calls[0][3],{'000001.SZ'})
            self.assertEqual(json.loads((root/'hithink-live/stock-close-archive.json').read_text())['status'],'success')
            self.assertFalse((root/'hithink-live/current-snapshot.json').exists())
    def test_independent_publication_retry_and_skip_successful_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);args=Namespace(state_root=root,publish_only=False)
            source={'generation':'a'*64,'payload':{'marketDate':'2026-11-17','historicalReconstruction':True}}
            calls=[];fails=[True]
            def collect(args):calls.append('collect');return HithinkJobResult('already_complete')
            def export(root,directory):
                directory.mkdir();(directory/'manifest.json').write_text(json.dumps({'generation':'a'*64}))
            def publish(directory,transport,checkpoint):
                calls.append('publish')
                if fails[0]:fails[0]=False;raise ValueError('PUBLICATION_NETWORK_FAILED')
                checkpoint.write_text(json.dumps({'generation':'a'*64,'activated':True}));return {'generation':'a'*64}
            with patch('tools.market_dashboard.sector_live_service.read_committed_snapshot',return_value=source),patch('tools.market_dashboard.sector_live_service.publish_export',side_effect=publish):
                first=run_service(args,collector=collect,exporter=export,transport=lambda b:{'ok':True},settings={'storageMode':'full'})
                second=run_service(args,collector=collect,exporter=export,transport=lambda b:{'ok':True},settings={'storageMode':'full'})
                third=run_service(args,collector=collect,exporter=export,transport=lambda b:{'ok':True},settings={'storageMode':'full'})
            self.assertEqual(first['safeErrorCode'],'PUBLICATION_NETWORK_FAILED')
            self.assertTrue(second['published']);self.assertTrue(third['published'])
            self.assertEqual(calls,['collect','publish','collect','publish','collect'])

    def test_publish_only_does_not_query_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);args=Namespace(state_root=root,publish_only=True)
            with patch('tools.market_dashboard.sector_live_service.read_committed_snapshot',return_value=None):
                result=run_service(args,collector=lambda args:self.fail('provider called'),transport=lambda body:{'ok':True})
            self.assertEqual(result['status'],'no_snapshot')


if __name__=='__main__':unittest.main()
