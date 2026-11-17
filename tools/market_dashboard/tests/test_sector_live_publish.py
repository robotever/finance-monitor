import base64
import gzip
import hashlib
import json
import io
import ssl
from pathlib import Path
import tempfile
import unittest

from tools.market_dashboard.sector_live_publish import prepare_documents, publish_export, LiveTransport


class LivePublishTests(unittest.TestCase):
    def test_transport_verifies_tls_and_identifies_client_without_changing_host(self):
        seen=[]
        def opener(request,*,timeout,context):
            seen.append(request)
            self.assertTrue(context.check_hostname)
            self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
            self.assertEqual(request.get_header('User-agent'),'NewsmonitorMarketDashboard/1.0')
            self.assertEqual(request.full_url,'https://newsmonitor.pages.dev/api/sector-live/publish')
            return io.BytesIO(b'{"ok":true}')
        self.assertTrue(LiveTransport('test-token',opener=opener)({'action':'health'})['ok'])
        self.assertEqual(len(seen),1)
        with self.assertRaisesRegex(ValueError,'INVALID_PUBLICATION_HOST'):LiveTransport('test-token',base='https://elsewhere.test')

    def fixture(self, path):
        generation='a'*64
        root=path/generation;root.mkdir()
        manifest=dict(generation=generation,marketDate='2026-11-17',observedAt='2026-11-17T07:00:00Z',exportedAt='2026-11-17T07:01:00Z')
        (path/'manifest.json').write_text(json.dumps(manifest))
        keys=['latest','catalog-industry','catalog-concept']+[f'history-{u}-{a}' for u in ['industry','concept'] for a in ['return1d','strength','opportunity','risk']]
        keys += [f'detail-881{i:03d}.TI' for i in range(90)] + [f'detail-885{i:03d}.TI' for i in range(390)]
        for key in keys:(root/(key+'.json')).write_text(json.dumps({'value':key}))
        return manifest,root

    def test_complete_deterministic_preparation_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);manifest,root=self.fixture(path)
            first=prepare_documents(path);second=prepare_documents(path)
            self.assertEqual(first,second)
            self.assertEqual(len(first['documents']),491)
            d=first['documents'][0]
            self.assertEqual(hashlib.sha256(base64.b64decode(d['gzipBase64'])).hexdigest(),d['digest'])
            self.assertIsInstance(json.loads(gzip.decompress(base64.b64decode(d['gzipBase64']))),dict)
            (root/'latest.json').write_text('{"secret":"Bearer hidden-token"}')
            with self.assertRaisesRegex(ValueError,'PRIVATE_EXPORT'):prepare_documents(path)

    def test_failure_does_not_activate_and_resume_reuses_uploaded_parts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);self.fixture(path);checkpoint=path/'checkpoint.json'
            calls=[];failed=[False]
            def transport(body):
                calls.append(body)
                if body['action']=='documents' and not failed[0]:failed[0]=True;raise RuntimeError('NETWORK')
                return {'ok':True}
            with self.assertRaises(RuntimeError):publish_export(path,transport,checkpoint=checkpoint)
            self.assertFalse(any(c['action']=='activate' for c in calls))
            calls.clear();publish_export(path,transport,checkpoint=checkpoint)
            self.assertEqual(calls[-1]['action'],'activate')
            self.assertTrue(json.loads(checkpoint.read_text())['activated'])


if __name__=='__main__':unittest.main()
