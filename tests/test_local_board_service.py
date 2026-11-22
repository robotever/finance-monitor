import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('local_board_service',Path('ops/macos/install-local-board-service.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class LocalBoardServiceTests(unittest.TestCase):
 def test_login_service_uses_absolute_runtime_and_no_network_credentials(self):
  p=module.service_plist(Path('/path with spaces/repo'),'/usr/local/bin/node',Path('/tmp/logs'))
  self.assertTrue(p['RunAtLoad']);self.assertTrue(p['KeepAlive'])
  self.assertEqual(p['ProgramArguments'],['/usr/local/bin/node','/path with spaces/repo/tools/market_dashboard/hithink_preview_server.mjs'])
  self.assertEqual(p['WorkingDirectory'],'/path with spaces/repo')
  self.assertNotIn('HTTP_PROXY',p['EnvironmentVariables'])
 def test_desktop_app_bootstrap_is_shell_quoted_and_independent_of_codex(self):
  script=module.desktop_launcher(Path('/path with spaces/repo'),'/usr/local/bin/python3')
  self.assertIn("'/path with spaces/repo/ops/macos/install-local-board-service.py'",script)
  self.assertIn('--open',script)
  self.assertNotIn('codex ',script)
 def test_readiness_bypasses_proxy_and_rejects_unrelated_listener(self):
  self.assertTrue(module.is_local_board_html(b'<script src="/@id/virtual:hithink-preview"></script>'))
  self.assertTrue(module.is_local_board_html(b'<title>Finance Monitor</title><script src="/src/main.ts"></script>'))
  self.assertFalse(module.is_local_board_html(b'<html>other app</html>'))
