import copy
import unittest
from tools.market_dashboard import radar_style_backfill as backfill

DATES=['2026-11-19','2026-11-20']
CODES=['000001.SZ','600001.SH']


def inputs():
    point={'date':DATES[-1],'up':1,'down':1,'flat':0,'turnover':3000,'mainNetFlow':100,'fundMatched':2,'fundExpected':2,'membershipMode':'current-members'}
    base={'schemaVersion':'radar-inputs-v1','observedAt':'2026-11-22T12:00:00+08:00','marketDate':DATES[-1],'objects':{key:{'id':key,'scope':key,'sources':['MX'],'membershipAsOf':'2026-11-22','history':[copy.deepcopy(point)]} for key in ['ashare']+backfill.STYLE_IDS}}
    members={key:{'members':CODES[:],'asOf':'2026-11-20','source':'CSI','scope':key} for key in backfill.STYLE_IDS}
    panel=[]
    for code,closes in [('000001.SZ',[10,11,12]),('600001.SH',[20,21,20])]:
        for day,close in zip(['2026-11-18']+DATES,closes):panel.append({'code':code,'date':day,'close':close,'volume':100,'turnover':1000 if code.startswith('0') else 2000})
    flows={code:{day:{'date':day,'mainNetFlow':150 if code.startswith('0') else -50} for day in DATES} for code in CODES}
    return base,members,panel,flows


class BackfillTest(unittest.TestCase):
    def test_full_members_exact_dates_amounts_and_latest_immutable(self):
        base,members,panel,flows=inputs();original=copy.deepcopy(base)
        out,report=backfill.backfill_bundle(base,members,panel,flows,DATES,{})
        self.assertTrue(report['ready']);self.assertEqual(base,original)
        self.assertEqual(out['objects']['small']['history'][-1],original['objects']['small']['history'][-1])
        point=out['objects']['small']['history'][0]
        self.assertEqual(point['date'],DATES[0]);self.assertEqual(point['turnover'],3000);self.assertEqual(point['mainNetFlow'],100)
        self.assertEqual((point['up'],point['down'],point['flat']),(2,0,0));self.assertEqual(point['fundMatched'],2)
        self.assertEqual(out['objects']['small']['membershipAsOf'],'2026-11-22');self.assertIn('当前成员历史重建',out['objects']['small']['scope'])
        self.assertEqual(set(out),set(original));self.assertEqual(set(point),set(original['objects']['small']['history'][0]))

    def test_missing_flow_is_not_zero_or_copied_across_dates(self):
        base,members,panel,flows=inputs();del flows[CODES[0]][DATES[0]]
        out,report=backfill.backfill_bundle(base,members,panel,flows,DATES,{})
        self.assertFalse(report['ready']);self.assertEqual(len(out['objects']['small']['history']),1)
        self.assertIn(CODES[0],report['styles']['small']['dates'][DATES[0]]['missingFlow'])

    def test_unknown_missing_panel_and_exact_previous_day_required(self):
        base,members,panel,flows=inputs();panel=[row for row in panel if not(row['code']==CODES[0] and row['date']=='2026-11-18')]
        panel.append({'code':CODES[0],'date':'2026-11-17','close':10,'volume':100,'turnover':1000})
        out,report=backfill.backfill_bundle(base,members,panel,flows,DATES,{})
        self.assertFalse(report['ready']);self.assertIn(CODES[0],report['styles']['small']['dates'][DATES[0]]['missingPrevious'])
        base,members,panel,flows=inputs();panel=[row for row in panel if not(row['code']==CODES[0] and row['date']==DATES[0])]
        out,report=backfill.backfill_bundle(base,members,panel,flows,DATES,{})
        self.assertFalse(report['ready']);self.assertIn(CODES[0],report['styles']['small']['dates'][DATES[0]]['missingPanel'])
        self.assertEqual(report['styles']['small']['dates'][DATES[0]]['excluded'],0)

    def test_explicit_zero_activity_or_evidence_can_exclude_without_filling(self):
        for evidence in (False,True):
            base,members,panel,flows=inputs()
            if evidence:
                for row in panel:
                    if row['code']==CODES[1] and row['date']==DATES[0]:row.update(volume=None,turnover=None)
            else:
                for row in panel:
                    if row['code']==CODES[1] and row['date']==DATES[0]:row.update(volume=0,turnover=0)
            del flows[CODES[1]][DATES[0]]
            out,report=backfill.backfill_bundle(base,members,panel,flows,DATES,{DATES[0]:[CODES[1]]} if evidence else {})
            p=out['objects']['small']['history'][0];self.assertEqual(p['fundExpected'],1);self.assertEqual(p['mainNetFlow'],150);self.assertEqual(p['turnover'],1000)
            self.assertEqual(report['styles']['small']['dates'][DATES[0]]['excluded'],1)

    def test_bad_ratio_or_latest_control_failure_preserves_old_points(self):
        base,members,panel,flows=inputs();flows[CODES[0]][DATES[0]]['mainNetFlow']=99999
        out,report=backfill.backfill_bundle(base,members,panel,flows,DATES,{})
        self.assertFalse(report['ready']);self.assertEqual(len(out['objects']['small']['history']),1)
        base,members,panel,flows=inputs();base['objects']['small']['history'][-1]['mainNetFlow']=2000000
        out,report=backfill.backfill_bundle(base,members,panel,flows,DATES,{})
        self.assertFalse(report['styles']['small']['ready']);self.assertEqual(out['objects']['small']['history'],base['objects']['small']['history'])

    def test_duplicate_zero_activity_cannot_hide_a_trading_row(self):
        base,members,panel,flows=inputs()
        for code in CODES:
            day18=next(row for row in panel if row['code']==code and row['date']=='2026-11-18')
            panel.append(dict(day18,date='2026-11-17'))
            flows[code]['2026-11-18']={'date':'2026-11-18','mainNetFlow':150 if code.startswith('0') else -50}
        real=next(row for row in panel if row['code']==CODES[0] and row['date']=='2026-11-18')
        panel.insert(0,dict(real,volume=0,turnover=0))
        out,report=backfill.backfill_bundle(base,members,panel,flows,['2026-11-18']+DATES,{})
        self.assertFalse(report['ready'])
        self.assertEqual(len(out['objects']['small']['history']),1)

    def test_latest_breadth_disagreement_is_reported_without_overwriting(self):
        base,members,panel,flows=inputs();base['objects']['small']['history'][-1].update(up=0,down=2)
        out,report=backfill.backfill_bundle(base,members,panel,flows,DATES,{})
        self.assertTrue(report['styles']['small']['ready'])
        self.assertEqual(report['styles']['small']['control']['breadthDelta'],{'up':1,'down':-1,'flat':0})
        self.assertEqual(out['objects']['small']['history'][-1],base['objects']['small']['history'][-1])

    def test_excluded_sample_with_explicit_nonzero_same_day_funding_is_rejected(self):
        for evidence in (False,True):
            base,members,panel,flows=inputs()
            for row in panel:
                if row['code']==CODES[1] and row['date']==DATES[0]:row.update(volume=0,turnover=0)
            out,report=backfill.backfill_bundle(base,members,panel,flows,DATES,{DATES[0]:[CODES[1]]} if evidence else {})
            detail=report['styles']['small']['dates'][DATES[0]]
            self.assertEqual(detail['status'],'failed')
            self.assertTrue(any('排除与非零资金矛盾' in reason for reason in detail['reasons']))
            self.assertEqual(out['objects']['small']['history'],base['objects']['small']['history'])

    def test_excluded_sample_with_explicit_zero_funding_does_not_create_basket_zero(self):
        base,members,panel,flows=inputs()
        for row in panel:
            if row['code']==CODES[1] and row['date']==DATES[0]:row.update(volume=0,turnover=0)
        flows[CODES[1]][DATES[0]]['mainNetFlow']=0
        out,report=backfill.backfill_bundle(base,members,panel,flows,DATES,{})
        p=out['objects']['small']['history'][0]
        self.assertEqual(p['mainNetFlow'],150);self.assertEqual(p['fundExpected'],1)
        self.assertEqual(report['styles']['small']['dates'][DATES[0]]['status'],'verified')

if __name__=='__main__':unittest.main()
