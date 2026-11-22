import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from tools.market_dashboard.radar_input_service import should_collect, content_digest
class RadarInputServiceTests(unittest.TestCase):
 def test_daily_close_window_is_shanghai_not_machine_timezone(self):
  self.assertFalse(should_collect(datetime(2026,11,23,7,0,tzinfo=ZoneInfo('UTC'))))
  self.assertTrue(should_collect(datetime(2026,11,23,7,21,tzinfo=ZoneInfo('UTC'))))
  self.assertFalse(should_collect(datetime(2026,11,22,8,0,tzinfo=ZoneInfo('UTC'))))
 def test_digest_does_not_publish_again_when_only_checked_time_changes(self):
  a={'observedAt':'2026-11-22T00:00:00Z','objects':{'x':1}}
  self.assertEqual(content_digest(a),content_digest({**a,'observedAt':'2026-11-22T01:00:00Z'}))
  self.assertNotEqual(content_digest(a),content_digest({**a,'objects':{'x':2}}))
 def test_publish_rejects_untrusted_hosts_before_using_credentials(self):
  from tools.market_dashboard.radar_input_service import publish
  with self.assertRaisesRegex(ValueError,'INVALID_PUBLISH_DESTINATION'):
   publish({},'https://unrelated.example/api/market-radar/inputs','test-token')
 def test_incomplete_inputs_get_a_bounded_preopen_recovery_window(self):
  before_open=datetime(2026,11,23,0,35,tzinfo=ZoneInfo('UTC'))
  self.assertTrue(should_collect(before_open,pending=True))
  self.assertFalse(should_collect(before_open,pending=False))
  self.assertFalse(should_collect(datetime(2026,11,23,2,0,tzinfo=ZoneInfo('UTC')),pending=True))
 def test_complete_but_old_bundle_is_pending_against_verified_session(self):
  import tempfile,json
  from pathlib import Path
  from tools.market_dashboard.radar_input_service import pending_inputs
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);point={'date':'2026-11-19','up':1,'down':1,'flat':0,'mainNetFlow':0,'turnover':100,'fundMatched':2,'fundExpected':2,'membershipMode':'current-members'}
   objects={k:{'history':[point]} for k in ['ashare','large','small','value','growth','dividend','tech']}
   (root/'latest.json').write_text(json.dumps({'marketDate':'2026-11-19','objects':objects}))
   self.assertFalse(pending_inputs(root,expected_date='2026-11-19'))
   self.assertTrue(pending_inputs(root,expected_date='2026-11-20'))
