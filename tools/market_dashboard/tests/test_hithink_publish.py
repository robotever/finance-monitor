import hashlib
import json
import unittest
from tools.market_dashboard.hithink_job import build_publish_chunks

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

if __name__=='__main__':unittest.main()
