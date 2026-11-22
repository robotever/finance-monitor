from copy import deepcopy
import json
from pathlib import Path
import unittest
from tools.market_dashboard import rotation_v4 as v4

class OpportunityV04Tests(unittest.TestCase):
    def test_position_is_monotone_and_missing_stays_missing(self):
        values=[v4.opportunity_position(x) for x in [0,5,10,20,35,70,100]]
        self.assertEqual(values,[100,95,90,80,65,30,0])
        for x in [None,float('nan'),-1,101,True]:self.assertIsNone(v4.opportunity_position(x))

    def test_low_position_can_score_without_turn_confirmation(self):
        from tools.market_dashboard.tests.test_rotation_v4 import panel
        indexes,breadth=panel();f=v4.build_v4_features(indexes,breadth)
        f['metrics'].update(position60d=0,position250d=0,breadthDelta5d=-1,shortAcceleration=-1,mediumAcceleration=-1,participationDelta5d=-1,relativeTurn5d=-1,relativeTurn20d=-1)
        c=json.loads(Path('config/hithink-sector-dashboard.json').read_text())
        r=v4.score_v4_sector(f,[],[f],c)
        self.assertEqual(r['improvementEvidence'],0)
        self.assertGreater(r['opportunity'],69)
        self.assertEqual(r['components']['position']['value'],100)
        self.assertEqual(c['scoring']['weights']['opportunity'],dict(position=60,breadthImprovement=15,momentumImprovement=10,participationWarming=10,relativeTurn=5))
        g=deepcopy(f);g['metrics'].update(position60d=100,position250d=100)
        high=v4.score_v4_sector(g,[],[g],c)
        self.assertEqual(r['strength'],high['strength']);self.assertEqual(r['risk'],high['risk'])
        self.assertGreater(r['opportunity'],high['opportunity'])

class OpportunityMigrationTests(unittest.TestCase):
    def test_reprice_preserves_other_axes_and_provenance_and_is_idempotent(self):
        from tools.market_dashboard.opportunity_migration import reprice_row
        from tools.market_dashboard.rotation import _leaf,_combine
        c=json.loads(Path('config/hithink-sector-dashboard.json').read_text())['scoring']
        components={k:_leaf(50) for k in c['componentWeights']}
        components['position']=_combine({'position60d':_leaf(0),'position250d':_leaf(0)},c['componentWeights']['position'])
        r=dict(id='881001.TI',universe='industry',sectorScoringVersion='sector-score-v0.3',strength=40,risk=90,opportunity=25,_rawScores=dict(strength=40.1,risk=90.1,opportunity=25.1),components=components,metrics=dict(position60d=5,position250d=10),axisCompleteness=dict(strength=100,opportunity=100,risk=100),validCloses=300,observedAt='2026-11-20T15:00:00+08:00',ranks=dict(strength=1,opportunity=1,risk=1),missing=[])
        old=deepcopy(r);new=reprice_row(r,c)
        self.assertEqual(r,old)
        for k in ['strength','risk','metrics','observedAt']:self.assertEqual(new[k],r[k])
        self.assertEqual(new['opportunity'],76)
        self.assertEqual(new['sectorScoringVersion'],'sector-score-v0.4')
        self.assertEqual(reprice_row(new,c),new)
        r['metrics']['position60d']=None;r['metrics']['position250d']=None
        self.assertIsNone(reprice_row(r,c)['opportunity'])
        r['sectorScoringVersion']='unknown'
        with self.assertRaises(ValueError):reprice_row(r,c)
