"""Pins the independently versioned Hithink score contract."""
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import unittest
from tools.market_dashboard import rotation_v4 as v4


def config():
    return json.loads(Path('config/hithink-sector-dashboard.json').read_text())


def panel(n=270):
    days = [(date(2025, 1, 1)+timedelta(days=i)).isoformat() for i in range(n)]
    indexes = [dict(sector_id='881001.TI',market_date=d,close=100+i,turnover=1000+i) for i,d in enumerate(days)]
    breadth = [dict(sector_id='881001.TI',market_date=d,advancing_share=.3+i/1000,declining_share=.5-i/1000,
                    median_return=i/100,strong_stock_share=.2,volume_expansion_share=.5,top5_turnover_share=.6,
                    top1_contribution_share=.3,completeness=1.,membership_mode='point_in_time_snapshot') for i,d in enumerate(days)]
    return indexes,breadth


class V4ScoringTests(unittest.TestCase):
    def test_exact_weights_and_nested_validation(self):
        c=config(); v4.validate_v4_config(c)
        self.assertEqual(c['scoring']['weights'], {
            'strength':dict(priceTrend=30,breadth=30,participation=20,persistence=20),
            'opportunity':dict(position=25,breadthImprovement=25,momentumImprovement=20,participationWarming=15,relativeTurn=15),
            'risk':dict(downsideDiffusion=30,trendDeterioration=25,divergence=20,crowding=15,concentration=10)})
        self.assertEqual(c['scoring']['componentWeights'], {
            'priceTrend':dict(return1d=20,return5d=45,return20d=35),
            'breadth':dict(advancingShare=40,medianReturn=30,strongStockShare=30),
            'participation':dict(turnoverPercentile=40,turnoverMarketShare=30,volumeExpansionShare=30),
            'persistence':dict(meanPercentile=60,topDecileStreak=40),
            'position':dict(position60d=50,position250d=50),
            'breadthImprovement':dict(delta5d=70,improvingDays=30),
            'momentumImprovement':dict(shortAcceleration=50,mediumAcceleration=50),
            'participationWarming':dict(current=40,delta5d=60),
            'relativeTurn':dict(relativeTurn5d=60,relativeTurn20d=40),
            'downsideDiffusion':dict(current=60,delta5d=40),
            'trendDeterioration':dict(return5d=30,return20d=40,slope5d=30),
            'divergence':dict(indexBreadth=60,indexMedian=40),
            'crowding':dict(activity=60,acceleration=40),
            'concentration':dict(top5TurnoverShare=60,top1ContributionShare=40)})
        for section in ('weights','componentWeights'):
            for key in c['scoring'][section]:
                bad=deepcopy(c); first=next(iter(bad['scoring'][section][key])); bad['scoring'][section][key][first]+=1
                with self.assertRaises(ValueError): v4.validate_v4_config(bad)
        bad=deepcopy(c); bad['scoring']['version']='wrong'
        with self.assertRaises(ValueError): v4.validate_v4_config(bad)

    def test_features_use_official_index_returns_no_future_and_missing_windows(self):
        indexes,breadth=panel()
        f=v4.build_v4_features(indexes,breadth,market_date=indexes[100]['market_date'])
        self.assertAlmostEqual(f['metrics']['return5d'],(200/195-1)*100)
        self.assertIsNotNone(f['metrics']['position60d'])
        self.assertIsNone(f['metrics']['position250d'])
        self.assertEqual(f['validCloses'],101)
        self.assertEqual(f,v4.build_v4_features(indexes[:101],breadth[:101]))
        self.assertGreater(v4.build_v4_features(indexes,breadth)['metrics']['position250d'],90)

    def test_missing_breadth_never_becomes_zero_and_approx_discount_once(self):
        indexes,breadth=panel(); full=v4.build_v4_features(indexes,breadth)
        approx=deepcopy(breadth)
        for b in approx: b.update(completeness=.8,membership_mode='current_members_backfill')
        current=v4.build_v4_features(indexes,approx)
        score=v4.score_v4_sector(current,[],[current],config())
        self.assertEqual(score['components']['breadth']['coverage'],.8)
        self.assertLess(score['axisCompleteness']['strength'],v4.score_v4_sector(full,[],[full],config())['axisCompleteness']['strength'])
        absent=v4.build_v4_features(indexes,[])
        result=v4.score_v4_sector(absent,[],[absent],config())
        self.assertIsNone(result['components']['breadth']['value']); self.assertTrue(result['missing'])

    def test_top_decile_not_top_ten_and_gap_breaks_streak(self):
        for size,cutoff in ((90,9),(390,39)):
            rows=[dict(id=str(i),universe='industry',strength=50,_rawScores={'strength':50},completeness=100) for i in range(size)]
            ranked=v4.rank_v4_universe(rows)
            self.assertEqual(sum(r['metrics']['inTopDecile'] for r in ranked),cutoff)
        history=[dict(marketDate=f'2026-01-{i:02}',metrics={'strengthRank':9,'universeSize':90}) for i in range(1,16)]
        self.assertEqual(v4.top_decile_continuity(history),dict(topDecileStreak=15,topDecileCount15d=15))
        history[-2]['metrics']['strengthRank']=10
        self.assertEqual(v4.top_decile_continuity(history)['topDecileStreak'],1)
        history[-1]['metrics']['strengthRank']=None
        self.assertIsNone(v4.top_decile_continuity(history)['topDecileStreak'])

    def test_opportunity_needs_two_independent_positive_changes(self):
        indexes,breadth=panel(); f=v4.build_v4_features(indexes,breadth)
        # A high cross-sectional percentile of negative changes is not evidence.
        f['metrics'].update(breadthDelta5d=-.01,shortAcceleration=-1,mediumAcceleration=-1,
                            participationDelta5d=-1,relativeTurn5d=-1,relativeTurn20d=-1)
        peer=deepcopy(f); peer['id']='881002.TI'
        peer['metrics'].update(breadthDelta5d=-1,shortAcceleration=-2,mediumAcceleration=-2)
        result=v4.score_v4_sector(f,[],[f,peer],config())
        self.assertEqual(result['improvementEvidence'],0)
        self.assertLessEqual(result['opportunity'],69)
        f['metrics'].update(breadthDelta5d=.1,shortAcceleration=1,mediumAcceleration=1)
        peer=deepcopy(f); peer['id']='881002.TI'
        peer['metrics'].update(breadthDelta5d=-1,shortAcceleration=-2,mediumAcceleration=-2)
        result=v4.score_v4_sector(f,[],[f,peer],config())
        self.assertEqual(result['improvementEvidence'],2)

    def test_cross_version_peer_rejected_and_scoring_does_not_mutate_features(self):
        indexes,breadth=panel(); f=v4.build_v4_features(indexes,breadth)
        before=deepcopy(f)
        v4.score_v4_sector(f,[],[f],config())
        self.assertEqual(f,before)
        peer=deepcopy(f); peer['id']='881002.TI'; peer['sectorScoringVersion']='sector-score-v0.2'
        with self.assertRaises(ValueError): v4.score_v4_sector(f,[],[f,peer],config())

    def test_replay_is_forward_only_and_preserves_observation_provenance(self):
        indexes,breadth=panel(30)
        definitions=[dict(id='881001.TI',name='sample',universe='industry')]
        rows=v4.replay_v4(indexes,breadth,definitions,config())
        early=v4.replay_v4(indexes[:25],breadth[:25],definitions,config())
        self.assertEqual(rows[:25],early)
        self.assertEqual(rows[-1]['validCloses'],30)
        self.assertIsNone(rows[-1].get('observedAt'))
        self.assertTrue(rows[-1]['officialClose'])
        self.assertEqual(rows[-1]['membershipMode'],'point_in_time_snapshot')

    def test_replay_late_breadth_cannot_inherit_old_index_arrival(self):
        from tools.market_dashboard.rotation_evaluation import _available
        indexes,breadth=panel(25)
        stamp=lambda value:int(datetime.fromisoformat(value).timestamp()*1000)
        for row in indexes:
            row['observed_at_ms']=stamp(row['market_date']+'T15:10:00+08:00')
        for row in breadth:
            row['observed_at_ms']=stamp(row['market_date']+'T15:12:00+08:00')
        breadth[-1]['observed_at_ms']=stamp('2026-11-16T15:20:00+08:00')
        rows=v4.replay_v4(indexes,breadth,[dict(id='881001.TI',universe='industry')],config())
        self.assertEqual(rows[-1]['availableAt'],'2026-11-16T15:20:00+08:00')
        self.assertEqual(rows[-1]['observedAt'],'2026-11-16T15:20:00+08:00')
        self.assertFalse(_available(rows[-1]))

    def test_feature_availability_requires_all_inputs_and_late_history(self):
        from tools.market_dashboard.rotation_evaluation import _available
        indexes,breadth=panel(30)
        stamp=lambda value:int(datetime.fromisoformat(value).timestamp()*1000)
        for row in indexes:
            row['observed_at_ms']=stamp(row['market_date']+'T15:10:00+08:00')
        for row in breadth:
            row['observed_at_ms']=stamp(row['market_date']+'T15:12:00+08:00')
        benchmark=[dict(row,close=row['close']*.9) for row in indexes]
        amounts={row['market_date']:dict(turnover=5000,observed_at_ms=stamp(row['market_date']+'T15:16:00+08:00')) for row in indexes}
        day=indexes[-1]['market_date']
        f=v4.build_v4_features(indexes,breadth,market_amounts=amounts,benchmark_rows=benchmark)
        self.assertEqual(f['availableAt'],day+'T15:16:00+08:00')
        self.assertEqual(f['availabilityStatus'],'verified')
        self.assertTrue(_available(dict(f,observedAt=f['availableAt'])))
        for field in ('index','breadth','benchmark','market'):
            ii,bb,bench,aa=deepcopy(indexes),deepcopy(breadth),deepcopy(benchmark),deepcopy(amounts)
            dependency={'index':ii[0],'breadth':bb[-2],'benchmark':bench[-1],'market':aa[day]}[field]
            dependency['observed_at_ms']=stamp('2026-11-16T15:20:00+08:00')
            late=v4.build_v4_features(ii,bb,market_amounts=aa,benchmark_rows=bench)
            self.assertEqual(late['availableAt'],'2026-11-16T15:20:00+08:00',field)
            dependency['observed_at_ms']=None
            unknown=v4.build_v4_features(ii,bb,market_amounts=aa,benchmark_rows=bench)
            self.assertIsNone(unknown['availableAt'],field)
            dependency['observed_at_ms']=stamp(day+'T15:15:00+08:00')
            dependency['availabilityStatus']='reconstructed'
            reconstructed=v4.build_v4_features(ii,bb,market_amounts=aa,benchmark_rows=bench)
            self.assertIsNone(reconstructed['availableAt'],field)
        f=v4.build_v4_features(indexes,breadth,market_amounts={day:5000},benchmark_rows=benchmark)
        self.assertIsNone(f['availableAt'])
        f=v4.build_v4_features(indexes,[dict(r,observed_at_ms=None) for r in breadth])
        self.assertIsNone(f['availableAt'])
        self.assertFalse(_available(dict(f,observedAt=day+'T15:20:00+08:00')))

    def test_score_availability_propagates_peer_and_historical_score_arrivals(self):
        indexes,breadth=panel(30)
        f=v4.build_v4_features(indexes,breadth)
        day=f['marketDate']; f.update(observedAt=day+'T15:10:00+08:00',availableAt=day+'T15:10:00+08:00',availabilityStatus='verified')
        peer=deepcopy(f); peer['id']='881002.TI'
        peer.update(availableAt='2026-11-16T15:20:00+08:00',observedAt='2026-11-16T15:20:00+08:00')
        score=v4.score_v4_sector(f,[],[f,peer],config())
        self.assertEqual(score['availableAt'],'2026-11-16T15:20:00+08:00')
        past=dict(f,marketDate='2024-01-01',session='close',availableAt='2026-11-16T15:22:00+08:00',observedAt='2026-11-16T15:22:00+08:00')
        score=v4.score_v4_sector(f,[past],[f],config())
        self.assertEqual(score['availableAt'],'2026-11-16T15:22:00+08:00')

    def test_batch_scoring_matches_single_without_mutating_inputs(self):
        indexes,breadth=panel(); first=v4.build_v4_features(indexes,breadth)
        second=deepcopy(first); second['id']='881002.TI'
        second['metrics']['advancingShare']=.2
        rows=[first,second]; before=deepcopy(rows)
        actual=v4.score_v4_sectors(rows,[],config())
        expected=[v4.score_v4_sector(row,[],rows,config()) for row in rows]
        self.assertEqual(actual,expected)
        self.assertEqual(rows,before)

    def test_store_feature_relative_turn_uses_each_peers_own_history(self):
        current=[]; past=[]
        for index in range(2):
            indexes,breadth=panel(); f=v4.build_v4_features(indexes,breadth)
            f['id']=str(index); f['metrics']['relativeStrength5d']=index*10
            f['metrics']['relativeStrength20d']=index*10
            f['metrics']['relativeTurn5d']=None; f['metrics']['relativeTurn20d']=None
            current.append(f)
            for i in range(5):
                past.append(dict(id=str(index),universe='industry',marketDate=f'2024-01-{i+1:02}',session='close',
                                 sectorScoringVersion=v4.SCORE_VERSION,sectorUniverseVersion=v4.UNIVERSE_VERSION,
                                 metrics=dict(relativeStrength5d=5,relativeStrength20d=5)))
        scores=v4.score_v4_sectors(current,past,config())
        self.assertEqual(scores[0]['metrics']['relativeTurn5d'],-5)
        self.assertEqual(scores[1]['metrics']['relativeTurn5d'],5)
        self.assertGreater(scores[1]['components']['relativeTurn']['value'],scores[0]['components']['relativeTurn']['value'])

    def test_invalid_identity_nonfinite_and_duplicate_dates_rejected(self):
        indexes,breadth=panel()
        with self.assertRaises(ValueError): v4.build_v4_features(indexes+[indexes[-1]],breadth)
        bad=deepcopy(indexes); bad[-1]['close']=float('nan')
        with self.assertRaises(ValueError): v4.build_v4_features(bad,breadth)
        with self.assertRaises(ValueError): v4.rank_v4_universe([dict(id='a',universe='industry')]*2)

    def test_deterministic_ranks_and_no_input_mutation(self):
        rows=[dict(id=i,universe='concept',strength=50,_rawScores={'strength':50},completeness=100) for i in ('b','a')]
        old=deepcopy(rows)
        self.assertEqual([r['id'] for r in v4.rank_v4_universe(rows)],['a','b'])
        self.assertEqual(rows,old)

if __name__=='__main__': unittest.main()
