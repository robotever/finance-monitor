import io,json,unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch
from tools.market_dashboard.market_observation_service import bucket,publish
class ServiceTests(unittest.TestCase):
 def test_fifteen_minute_windows(self):
  sh=ZoneInfo('Asia/Shanghai')
  self.assertIsNone(bucket(datetime(2026,11,26,12,5,tzinfo=sh)))
  self.assertIsNone(bucket(datetime(2026,11,28,10,0,tzinfo=sh)))
  self.assertEqual(bucket(datetime(2026,11,26,14,16,tzinfo=sh)),'2026-11-26T14:15')
  self.assertNotEqual(bucket(datetime(2026,11,26,14,14,tzinfo=sh)),bucket(datetime(2026,11,26,14,16,tzinfo=sh)))
 def test_publish_target_and_auth_identification(self):
  with self.assertRaises(ValueError):publish({},'https://other.example/api/market-observation','private')
  with patch('tools.market_dashboard.market_observation_service.urllib.request.build_opener') as make:
   make.return_value.open.return_value.__enter__.return_value=io.BytesIO(b'{"ok":true}')
   publish({},'https://newsmonitor.pages.dev/api/market-observation','private')
   req=make.return_value.open.call_args.args[0]
   self.assertEqual(req.get_header('User-agent'),'FinanceMonitorMarketDashboard/1.0')
