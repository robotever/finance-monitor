import json,tempfile,unittest
from pathlib import Path
from tools.market_dashboard.radar_history_job import read_panel,commit_candidate
from tools.market_dashboard.radar_input_service import content_digest
class RadarHistoryJobTests(unittest.TestCase):
 def test_panel_keeps_actual_turnover_and_dates(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'panel.csv';p.write_text('thscode,date,close,volume,amount\n600519.SH,2026-11-20,1485.75,6722940,9796311852.38\n')
   r=read_panel(p)[0];self.assertEqual(r['turnover'],9796311852.38);self.assertEqual(r['date'],'2026-11-20')
 def test_concurrent_new_daily_payload_is_never_overwritten(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);old={'marketDate':'2026-11-20','objects':{},'observedAt':'old'};new={**old,'marketDate':'2026-11-23'}
   (root/'latest.json').write_text(json.dumps(new))
   with self.assertRaisesRegex(RuntimeError,'BASE_CHANGED'):commit_candidate(root,content_digest(old),old)
   self.assertEqual(json.loads((root/'latest.json').read_text()),new)
 def test_successful_commit_saves_original_for_rollback(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);old={'marketDate':'2026-11-20','objects':{},'observedAt':'old'};(root/'latest.json').write_text(json.dumps(old))
   commit_candidate(root,content_digest(old),{**old,'objects':{'verified':True}})
   self.assertTrue(list(root.glob('latest.pre-history-*.json')))
   self.assertEqual(json.loads((root/'latest.json').read_text())['objects'],{'verified':True})
 def test_date_metadata_is_validated_before_readonly_sql_export(self):
  from tools.market_dashboard.radar_history_job import verify_dates
  valid=['2026-11-12','2026-11-13','2026-11-16','2026-11-17','2026-11-18','2026-11-19','2026-11-20']
  self.assertEqual(verify_dates(valid,'2026-11-20'),valid)
  with self.assertRaises(ValueError):verify_dates(["' OR 1=1--",*valid[1:]],'2026-11-20')
  with self.assertRaises(ValueError):verify_dates([*valid[:-1],'2026-11-21'],'2026-11-20')
