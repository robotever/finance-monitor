import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tools.market_dashboard.market_observation_data import enrich_turnover
class EnrichmentTests(unittest.TestCase):
 def test_failed_enrichment_preserves_prior_time_instead_of_dropping_to_original_card(self):
  with tempfile.TemporaryDirectory() as root:
   saved={'date':'2026-11-25','asOf':'2026-11-25T15:00:00+08:00','rows':[{'currentCny':123}]}
   Path(root,'latest.json').write_text(json.dumps({'turnover':saved}));payload={'notes':[]}
   with patch('tools.market_dashboard.market_turnover_data.collect_turnover',side_effect=RuntimeError('private source failed')):
    enrich_turnover(payload,snapshot_rows=[],snapshot_at='2026-11-26T14:00:00+08:00',previous_date='2026-11-25',calendar_days=[],state_root=Path(root),project_root=Path(root))
   self.assertEqual(payload['turnover'],saved);self.assertTrue(payload['notes']);self.assertNotIn('private source',str(payload))
