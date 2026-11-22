import unittest
from tools.market_dashboard.etf_observation_job import parse_caps,parse_nav,parse_sse,parse_szse,merge_rows,confirmed_sessions

class EtfJobTests(unittest.TestCase):
 def test_exchange_units_and_dates(self):
  self.assertEqual(parse_sse({'result':[{'SEC_CODE':'510300','STAT_DATE':'2026-11-20','TOT_VOL':'5518488.77'}]})['510300.SH'][0]['shares'],55184887700)
  self.assertEqual(parse_szse([{'data':[{'fund_code':'159919 ','size_date':'2026-11-20','current_size':'2,156,781.66'}],'metadata':{'pagecount':1}}])[0]['shares'],21567816600)
 def test_caps_field_identity_and_real_dates(self):
  t={'code':'000300.SH','field':{'returnSourceCode':'SHRMARKETVALUEM','returnName':'流通市值','dateGranularity':'DAY','unit':'1','returnCode':'x','fixedParamValue':'Period=1'},'rawTable':{'headName':['2026-11-20'],'x':['48236749804141.08']}}
  self.assertEqual(parse_caps({'data':{'dataTableDTOList':[t]}})[0],{'date':'2026-11-20','value':48236749804141.08})
  t['field']['returnName']='自由流通市值'
  with self.assertRaises(ValueError):parse_caps({'data':{'dataTableDTOList':[t]}})
 def test_nav_not_adjusted_and_no_duplicate_conflicts(self):
  p=parse_nav({'ok':True,'data':{'item':[{'nav_date':1795104000000,'unit_nav':4.0286}]}})
  self.assertEqual(p,[{'date':'2026-11-20','nav':4.0286}])
  with self.assertRaises(ValueError):parse_nav({'ok':True,'data':{'item':[{'nav_date':1795104000000,'adj_nav':4.1}]}})
  with self.assertRaises(ValueError):merge_rows([{'date':'2026-11-20','shares':1},{'date':'2026-11-20','shares':2}],[])
 def test_confirmed_only_excludes_current_shares_date(self):
  from datetime import datetime
  from zoneinfo import ZoneInfo
  rows=[['2026-11-19'],['2026-11-20']]
  self.assertEqual(confirmed_sessions(rows,datetime(2026,11,20,23,tzinfo=ZoneInfo('Asia/Shanghai'))),['2026-11-19'])

 def test_public_referer_matches_source(self):
  from unittest.mock import patch
  from types import SimpleNamespace
  from tools.market_dashboard.etf_observation_job import fetch_json
  with patch('tools.market_dashboard.etf_observation_job.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=b'{}')) as run:
   fetch_json('https://www.szse.cn/api/report/ShowReport/data')
   self.assertIn('Referer: https://www.szse.cn/market/fund/volume/etf/index.html',run.call_args.args[0])

 def test_incomplete_latest_retries_and_force_bypasses_same_day(self):
  from datetime import datetime
  from zoneinfo import ZoneInfo
  from tools.market_dashboard.etf_observation_job import can_reuse
  day='2026-11-20';now=datetime(2026,11,21,10,tzinfo=ZoneInfo('Asia/Shanghai'))
  b={'generatedAt':'2026-11-21T01:00:00Z','sessions':[day],'indexCloses':[{'date':day,'value':100}],'marketCaps':[{'date':day,'value':1e13}],'funds':[{'points':[{'date':day,'shares':100,'nav':4}]} for _ in range(4)]}
  self.assertTrue(can_reuse(b,day,now,False))
  self.assertFalse(can_reuse(b,day,now,True))
  b['funds'][3]['points'][0]['nav']=None
  self.assertFalse(can_reuse(b,day,now,False))
  b['funds'][3]['points'][0]['nav']=4;b['marketCaps']=[]
  self.assertFalse(can_reuse(b,day,now,False))

 def test_publisher_identifies_client_and_rejects_other_destinations(self):
  from unittest.mock import patch
  import io
  from tools.market_dashboard.etf_observation_job import publish
  with patch('tools.market_dashboard.etf_observation_job.urllib.request.build_opener') as build:
   build.return_value.open.return_value.__enter__.return_value=io.BytesIO(b'{"ok":true}')
   publish({},'https://newsmonitor.pages.dev/api/market-radar/etf','private')
   request=build.return_value.open.call_args.args[0]
   self.assertEqual(request.get_header('User-agent'),'FinanceMonitorMarketDashboard/1.0')
  with self.assertRaises(ValueError):publish({},'https://example.com/api/market-radar/etf','private')
