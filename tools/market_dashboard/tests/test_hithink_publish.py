import hashlib
import json
import unittest
from tools.market_dashboard.hithink_job import build_publish_chunks, refresh_local_projection

class HithinkPublishTests(unittest.TestCase):
    def row(self,i):
        return dict(id=f'885{i:03}.TI',name='示例概念',universe='concept',strength=55,opportunity=44,risk=33,
            completeness=80,ranks={'strength':i+1,'opportunity':i+1,'risk':i+1},heatState=None,
            coldStart=False,validCloses=250,improvementEvidence=2,membershipMode='point_in_time_snapshot',
            missing=[],schemaVersion='market-dashboard-v4',sectorScoringVersion='sector-score-v0.3',
            sectorUniverseVersion='sector-universe-ths-v1',featureVersion='sector-features-ths-v1',
            membershipVersion='sector-membership-ths-v1',_rawScores={'strength':55.111},
            members=['private member'],metrics={'return1d':.01},namePrivate='/Users/private')
    def test_projection_excludes_private_and_chunk_digests_match_exact_utf8(self):
        rows=[self.row(i) for i in range(110)]
        chunks=build_publish_chunks(rows)
        self.assertEqual([len(json.loads(c['rowsJson'])) for c in chunks],[50,50,10])
        self.assertEqual(chunks,build_publish_chunks(rows))
        for c in chunks:
            self.assertEqual(hashlib.sha256(c['rowsJson'].encode()).hexdigest(),c['digest'])
            self.assertLessEqual(len(json.dumps(c,ensure_ascii=False,separators=(',',':')).encode()),131072)
            r=json.loads(c['rowsJson'])[0]
            self.assertNotIn('_rawScores',r);self.assertNotIn('members',r);self.assertNotIn('namePrivate',r)
            self.assertIsNone(r['conceptRole'])
    def test_byte_limit_includes_outer_escaped_json_envelope(self):
        chunks=build_publish_chunks([self.row(i) for i in range(10)],max_bytes=1800)
        self.assertGreater(len(chunks),1)
        self.assertTrue(all(len(json.dumps(c,ensure_ascii=False,separators=(',',':')).encode())<=1800 for c in chunks))
        with self.assertRaises(ValueError):build_publish_chunks([self.row(0)],max_bytes=10)
    def test_duplicate_mixed_version_missing_ranks_and_empty_rejected(self):
        row=self.row(0)
        with self.assertRaises(ValueError):build_publish_chunks([row,row])
        with self.assertRaises(ValueError):build_publish_chunks([])
        bad={**row,'featureVersion':'old'}
        with self.assertRaises(ValueError):build_publish_chunks([bad])
        bad={**row,'ranks':{'strength':1}}
        with self.assertRaises(ValueError):build_publish_chunks([bad])

    def test_python_requests_pass_real_server_row_validator(self):
        import subprocess
        from pathlib import Path
        chunks=build_publish_chunks([self.row(i) for i in range(3)])
        script="""import fs from 'node:fs';
import {validateV4Row,sha256} from './functions/_lib/sector-rotation-v4.js';
const chunks=JSON.parse(fs.readFileSync(0,'utf8'));let count=0;
for(const c of chunks){if(await sha256(c.rowsJson)!==c.digest)throw Error('CHECKSUM');for(const r of JSON.parse(c.rowsJson)){validateV4Row(r,{industryCount:90,conceptCount:390});count++}}
console.log(count);"""
        result=subprocess.run(['node','--input-type=module','-e',script],input=json.dumps(chunks),
            text=True,capture_output=True,timeout=10,cwd=Path(__file__).resolve().parents[3])
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'3')


    def test_offline_metadata_refresh_preserves_scores_availability_and_bucket(self):
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        from tools.market_dashboard import hithink_job as job
        from tools.market_dashboard.hithink_universe import load_catalog_fixture
        sectors=[*load_catalog_fixture(Path(job.__file__).parent/'fixtures/hithink/catalog-industry.json'),
                 *load_catalog_fixture(Path(job.__file__).parent/'fixtures/hithink/catalog-concept.json')]
        sectors=[s for s in sectors if s.tag!='industry' or s.code.startswith('881')]
        rows=[{**self.row(i),'id':s.code,'name':s.name,'universe':'industry' if s.tag=='industry' else 'concept',
               'ranks':{'strength':None,'opportunity':None,'risk':None},'observedAt':'2026-11-17T01:00:00+08:00','availableAt':None} for i,s in enumerate(sectors)]
        payload={'marketDate':'2026-11-16','bucket':'2026-11-16:reconstructed-close','historicalReconstruction':True,'officialClose':False,'rows':rows}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();local=root/'hithink-live';local.mkdir()
            (local/'latest.json').write_text(json.dumps(payload));(local/'state.json').write_text('{"completed":["unchanged"]}')
            with patch.object(job,'HithinkClient',side_effect=AssertionError('network forbidden')):
                summary=refresh_local_projection(root)
                self.assertEqual(summary,refresh_local_projection(root))
            after=json.loads((local/'latest.json').read_text())
            self.assertEqual(summary['coreCount'],25);self.assertEqual(summary['rows'],480)
            self.assertEqual(after['officialClose'],False);self.assertEqual(after['historicalReconstruction'],True)
            self.assertEqual(after['bucket'],payload['bucket'])
            for before,row in zip(payload['rows'],after['rows']):
                self.assertEqual({k:row[k] for k in before},before)
                self.assertEqual(row['session'],'close')
                self.assertTrue(row['historicalReconstruction'])
                self.assertFalse(row['officialClose'])
            self.assertEqual((local/'state.json').read_text(),'{"completed":["unchanged"]}')
            projected=[r for c in json.loads((local/'publish-chunks.json').read_text()) for r in json.loads(c['rowsJson'])]
            self.assertEqual(sum(r['conceptRole']=='core' for r in projected),25)

if __name__=='__main__':unittest.main()
