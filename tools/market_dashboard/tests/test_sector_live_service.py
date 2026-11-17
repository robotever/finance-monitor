from argparse import Namespace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.market_dashboard.hithink_job import HithinkJobResult
from tools.market_dashboard.sector_live_service import run_service


class LiveServiceTests(unittest.TestCase):
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
                first=run_service(args,collector=collect,exporter=export,transport=lambda b:{'ok':True})
                second=run_service(args,collector=collect,exporter=export,transport=lambda b:{'ok':True})
                third=run_service(args,collector=collect,exporter=export,transport=lambda b:{'ok':True})
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
