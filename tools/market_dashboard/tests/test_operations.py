"""Exercise installers and wrappers in disposable roots; never load real jobs."""
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[3]
OPS = REPO / 'ops/macos'
LABEL = 'com.robot-ever.newsmonitor.market-dashboard'


def health_module():
    common = subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=REPO, text=True).strip()
    project = Path(common).resolve().parent.parent
    path = Path(os.environ.get('MARKET_DASHBOARD_TEST_PROJECT_ROOT', project)) / 'scripts/intake_health_check.py'
    if not path.exists():
        raise unittest.SkipTest('Financial Knowledge Repository health script is not available')
    spec = importlib.util.spec_from_file_location('dashboard_health_operations', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dashboard ops ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / 'Financial Project'
        self.repo = self.root / 'newsmonitor'
        (self.repo / 'ops/macos').mkdir(parents=True)
        (self.root / 'scripts').mkdir()
        (self.root / 'scripts/rotate_service_logs.py').touch()
        self.env = {**os.environ, 'HOME': str(Path(self.tmp.name) / 'user home'),
                    'MARKET_DASHBOARD_PROJECT_ROOT': str(self.root),
                    'MARKET_DASHBOARD_PYTHON': sys.executable}
        self.env.pop('MARKET_DASHBOARD_PUBLISH_TOKEN', None)
        self.env.pop('MARKET_DASHBOARD_PUBLISH_URL', None)
        self.env.pop('MX_APIKEY', None)
        Path(self.env['HOME']).mkdir()

    def copy_ops(self):
        self.assertTrue((OPS / 'run-market-dashboard.sh').exists(), 'wrapper is missing')
        shutil.copytree(OPS, self.repo / 'ops/macos', dirs_exist_ok=True)

    def make_checkout(self):
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True, capture_output=True)
        (self.repo / 'tools/market_dashboard').mkdir(parents=True, exist_ok=True)
        (self.repo / 'tools/market_dashboard/job.py').touch()
        (self.repo / 'config').mkdir(exist_ok=True)
        (self.repo / 'config/market-dashboard.json').write_text('{}')

    def trap_launchctl(self):
        binary = self.root / 'bin'
        binary.mkdir(exist_ok=True)
        launchctl = binary / 'launchctl'
        launchctl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$HOME/launchctl-calls"\n'
                             'if [ "$1" = print ]; then exit 1; fi\nexit 0\n')
        launchctl.chmod(0o755)
        self.env['PATH'] = f'{binary}:{os.environ["PATH"]}'

    def execute(self, script, *args):
        return subprocess.run(['/bin/bash', str(self.repo / 'ops/macos' / script), *args],
                              env=self.env, capture_output=True, text=True, timeout=15)

    def test_wrapper_loads_literal_dotenv_executes_cli_and_rotates_private_logs(self):
        self.copy_ops()
        package = self.repo / 'tools/market_dashboard'
        package.mkdir(parents=True)
        (self.repo / 'tools/__init__.py').touch()
        (package / '__init__.py').touch()
        (package / 'job.py').write_text(
            'import json, os, sys\nfrom pathlib import Path\n'
            'Path(os.environ["TEST_CAPTURE"]).write_text(json.dumps({'
            '"key":os.environ["MX_APIKEY"], "token":os.environ["MARKET_DASHBOARD_PUBLISH_TOKEN"],'
            '"state":os.environ["MARKET_DASHBOARD_STATE_ROOT"],"args":sys.argv[1:],"pid":os.getpid()}))\n')
        (self.root / '.env').write_text('export MX_APIKEY="synthetic $(touch should-not-exist)"\n'
                                      'MARKET_DASHBOARD_PUBLISH_TOKEN=synthetic-private\n')
        self.env['TEST_CAPTURE'] = str(self.root / 'capture.json')
        scripts = self.root / 'scripts'
        # Use the real existing rotation policy, never execute its CLI on live logs.
        health = health_module()
        shutil.copy(health.ROOT / 'scripts/rotate_service_logs.py', scripts)
        logs = self.root / 'logs/market-dashboard'
        logs.mkdir(parents=True)
        (logs / 'job.log').write_text('x' * 2_000_001)
        result = self.execute('run-market-dashboard.sh', '--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        captured = json.loads((self.root / 'capture.json').read_text())
        self.assertEqual(captured['key'], 'synthetic $(touch should-not-exist)')
        self.assertEqual(captured['token'], 'synthetic-private')
        self.assertEqual(captured['state'], str(self.root / 'state'))
        self.assertEqual(captured['args'], ['--dry-run'])
        self.assertFalse((self.repo / 'should-not-exist').exists())
        self.assertNotIn('synthetic-private', result.stdout + result.stderr)
        self.assertTrue((logs / 'job.log.1').exists())
        self.assertEqual(logs.stat().st_mode & 0o777, 0o700)
        self.assertEqual((logs / 'job.log').stat().st_mode & 0o777, 0o600)

    def test_log_directory_symlinks_fail_before_writes_or_launchctl(self):
        self.copy_ops()
        self.make_checkout()
        self.trap_launchctl()
        (self.root / 'scripts/rotate_service_logs.py').write_text('def rotate(path): pass\n')
        outside = Path(self.tmp.name) / 'outside logs'
        outside.mkdir(mode=0o755)
        sentinel = outside / 'sentinel.log'
        sentinel.write_text('retained')
        sentinel.chmod(0o644)
        for relative in ('logs', 'logs/market-dashboard'):
            link = self.root / relative
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(outside, target_is_directory=True)
            for script, args in (('run-market-dashboard.sh', ('--dry-run',)),
                                 ('install-market-dashboard-service.sh', ('--prepare',)),
                                 ('install-market-dashboard-service.sh', ('--enable',))):
                with self.subTest(relative=relative, script=script, args=args):
                    result = self.execute(script, *args)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(sentinel.read_text(), 'retained')
                    self.assertEqual(sentinel.stat().st_mode & 0o777, 0o644)
                    self.assertEqual(outside.stat().st_mode & 0o777, 0o755)
                    self.assertEqual(sorted(p.name for p in outside.iterdir()), ['sentinel.log'])
                    self.assertFalse((Path(self.env['HOME']) / 'Library/LaunchAgents').exists())
                    self.assertFalse((Path(self.env['HOME']) / 'launchctl-calls').exists())
            link.unlink()

    def test_opt_in_wrapper_runs_one_combined_cycle_and_can_be_disabled(self):
        self.copy_ops()
        package = self.repo / 'tools/market_dashboard'
        package.mkdir(parents=True)
        (self.repo / 'tools/__init__.py').touch()
        (package / '__init__.py').touch()
        (package / 'job.py').write_text(
            'import json, os, sys\nfrom pathlib import Path\n'
            'with Path(os.environ["TEST_CAPTURE"]).open("a") as f:\n'
            ' f.write(json.dumps(sys.argv[1:])+"\\n")\n'
            'print("safe-summary")\n')
        (self.root / 'scripts/rotate_service_logs.py').write_text('def rotate(path): pass\n')
        capture = self.root / 'calls.jsonl'
        self.env.update(TEST_CAPTURE=str(capture), MARKET_DASHBOARD_ROTATION_SHADOW='1')
        enabled = self.execute('run-market-dashboard.sh')
        self.assertEqual(enabled.returncode, 0, enabled.stderr)
        self.assertEqual([json.loads(line) for line in capture.read_text().splitlines()],
                         [['--with-rotation']])
        self.assertFalse((self.root / 'logs/market-dashboard-shadow/job.log').exists())
        self.assertIn('safe-summary', (self.root / 'logs/market-dashboard/job.log').read_text())
        capture.unlink()
        self.env['MARKET_DASHBOARD_ROTATION_SHADOW'] = '0'
        disabled = self.execute('run-market-dashboard.sh')
        self.assertEqual(disabled.returncode, 0, disabled.stderr)
        self.assertEqual(capture.read_text().splitlines(), ['[]'])
        # An explicit shadow command must not silently run a v2 publish first.
        capture.unlink()
        self.env['MARKET_DASHBOARD_ROTATION_SHADOW'] = '1'
        explicit = self.execute('run-market-dashboard.sh', '--rotation-shadow', '--dry-run')
        self.assertEqual(explicit.returncode, 0, explicit.stderr)
        self.assertEqual([json.loads(line) for line in capture.read_text().splitlines()],
                         [['--rotation-shadow', '--dry-run']])

    def test_direct_job_test_module_includes_close_freshness_tests(self):
        result = subprocess.run([sys.executable, '-m', 'tools.market_dashboard.tests.test_job', '-v'],
                                cwd=REPO, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('CloseFreshnessTests.test_final_close_remains_fresh', result.stderr)

    def test_installer_renders_idempotently_without_starting_and_recovers_previous_file(self):
        self.copy_ops()
        self.make_checkout()
        agents = Path(self.env['HOME']) / 'Library/LaunchAgents'
        agents.mkdir(parents=True)
        target = agents / f'{LABEL}.plist'
        target.write_bytes(b'previous installation')
        # A trap records even an accidental launchctl command during prepare.
        binary = self.root / 'bin'
        binary.mkdir()
        launchctl = binary / 'launchctl'
        launchctl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$HOME/launchctl-calls"\nexit 1\n')
        launchctl.chmod(0o755)
        self.env['PATH'] = f'{binary}:{os.environ["PATH"]}'
        first = self.execute('install-market-dashboard-service.sh', '--prepare')
        self.assertEqual(first.returncode, 0, first.stderr)
        data = target.read_bytes()
        plist = plistlib.loads(data)
        self.assertEqual(plist['StartInterval'], 300)
        self.assertEqual(plist['ProgramArguments'], ['/bin/bash', str(self.repo / 'ops/macos/run-market-dashboard.sh')])
        self.assertEqual(plist['EnvironmentVariables']['MARKET_DASHBOARD_PROJECT_ROOT'], str(self.root))
        self.assertFalse(plist.get('RunAtLoad', False))
        self.assertFalse(plist.get('KeepAlive', False))
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(target.with_suffix('.plist.bak').read_bytes(), b'previous installation')
        second = self.execute('install-market-dashboard-service.sh', '--prepare')
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(target.read_bytes(), data)
        self.assertEqual(target.with_suffix('.plist.bak').read_bytes(), b'previous installation')
        self.assertFalse((Path(self.env['HOME']) / 'launchctl-calls').exists())
        self.assertIn('--disable', first.stdout)
        self.assertIn('--uninstall', first.stdout)

    def test_disable_uninstall_and_restore_preserve_configuration_without_bootstrap(self):
        self.copy_ops()
        self.make_checkout()
        agents = Path(self.env['HOME']) / 'Library/LaunchAgents'
        agents.mkdir(parents=True)
        target = agents / f'{LABEL}.plist'
        target.write_bytes(b'previous installation')
        binary = self.root / 'bin'
        binary.mkdir()
        launchctl = binary / 'launchctl'
        launchctl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$HOME/launchctl-calls"\nexit 0\n')
        launchctl.chmod(0o755)
        self.env['PATH'] = f'{binary}:{os.environ["PATH"]}'
        self.assertEqual(self.execute('install-market-dashboard-service.sh', '--prepare').returncode, 0)
        prepared = target.read_bytes()
        for action in ('--disable', '--uninstall', '--restore'):
            result = self.execute('install-market-dashboard-service.sh', action)
            self.assertEqual(result.returncode, 0, result.stderr)
            if action == '--disable':
                self.assertEqual(target.read_bytes(), prepared)
            if action == '--uninstall':
                self.assertFalse(target.exists())
                self.assertEqual(target.with_suffix('.plist.disabled').read_bytes(), prepared)
        self.assertEqual(target.read_bytes(), b'previous installation')
        calls = (Path(self.env['HOME']) / 'launchctl-calls').read_text()
        self.assertIn('disable gui/', calls)
        self.assertIn('bootout gui/', calls)
        self.assertNotIn('bootstrap', calls)
        self.assertNotIn('kickstart', calls)

    def test_prepare_requires_real_project_rotation_policy_before_writing_agent(self):
        self.copy_ops()
        self.make_checkout()
        (self.root / 'scripts/rotate_service_logs.py').unlink()
        result = self.execute('install-market-dashboard-service.sh', '--prepare')
        self.assertNotEqual(result.returncode, 0)
        target = Path(self.env['HOME']) / f'Library/LaunchAgents/{LABEL}.plist'
        self.assertFalse(target.exists())

    def test_dotenv_preserves_hashes_backslashes_quotes_spaces_comments_and_environment(self):
        self.copy_ops()
        package = self.repo / 'tools/market_dashboard'
        package.mkdir(parents=True)
        (package / 'job.py').write_text('import json, os\nfrom pathlib import Path\n'
            'Path(os.environ["TEST_CAPTURE"]).write_text(json.dumps({key:value for key,value in os.environ.items() if key.startswith("SYNTH_")}))\n')
        (self.root / 'scripts/rotate_service_logs.py').write_text('def rotate(path): pass\n')
        (self.root / '.env').write_text(
            '# comment\nSYNTH_HASH=synthetic#suffix\n'
            'SYNTH_BACKSLASH=C:\\synthetic\\path\n'
            'SYNTH_SINGLE=\'single # value \\literal\' # trailing comment\n'
            'SYNTH_DOUBLE="double # value \\literal"  # trailing comment\n'
            'SYNTH_SPACES=  two  internal spaces  # ignored\n'
            'SYNTH_QUOTE=unquoted"quote\n'
            'SYNTH_OVERRIDE=dotenv-value\n'
            'SYNTH_COMMAND=$(touch synthetic-sentinel)\n')
        self.env['SYNTH_OVERRIDE'] = 'existing-environment'
        self.env['TEST_CAPTURE'] = str(self.root / 'capture.json')
        result = self.execute('run-market-dashboard.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.root / 'capture.json').read_text()), {
            'SYNTH_HASH': 'synthetic#suffix', 'SYNTH_BACKSLASH': 'C:\\synthetic\\path',
            'SYNTH_SINGLE': 'single # value \\literal', 'SYNTH_DOUBLE': 'double # value \\literal',
            'SYNTH_SPACES': 'two  internal spaces', 'SYNTH_QUOTE': 'unquoted"quote',
            'SYNTH_OVERRIDE': 'existing-environment', 'SYNTH_COMMAND': '$(touch synthetic-sentinel)'})
        self.assertFalse((self.repo / 'synthetic-sentinel').exists())
        self.assertNotIn('dotenv-value', result.stdout + result.stderr)

    def test_invalid_checkout_and_missing_cli_or_config_fail_before_writes_or_launchctl(self):
        self.copy_ops()
        self.trap_launchctl()
        for missing in ('.git', 'tools/market_dashboard/job.py', 'config/market-dashboard.json',
                        'ops/macos/run-market-dashboard.sh', f'ops/macos/{LABEL}.plist'):
            self.copy_ops()
            self.make_checkout()
            path = self.repo / missing
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            for action in ('--prepare', '--enable'):
                with self.subTest(missing=missing, action=action):
                    result = self.execute('install-market-dashboard-service.sh', action)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse((Path(self.env['HOME']) / 'Library/LaunchAgents').exists())
                    self.assertFalse((Path(self.env['HOME']) / 'launchctl-calls').exists())
                    self.assertFalse((self.root / 'logs').exists())

    def test_worktree_requires_explicit_override_and_stable_checkout_can_enable(self):
        self.copy_ops()
        self.make_checkout()
        self.trap_launchctl()
        subprocess.run(['git', '-C', str(self.repo), 'add', '.'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.repo), '-c', 'user.name=Synthetic',
                        '-c', 'user.email=synthetic@example.invalid', 'commit', '-qm', 'fixture'],
                       check=True, capture_output=True)
        stable_repo = self.repo
        worktree = self.root / 'isolated worktree'
        subprocess.run(['git', '-C', str(stable_repo), 'worktree', 'add', '--detach', str(worktree)],
                       check=True, capture_output=True)
        self.repo = worktree
        for action in ('--prepare', '--enable'):
            result = self.execute('install-market-dashboard-service.sh', action)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('--allow-worktree', result.stderr)
            self.assertFalse((Path(self.env['HOME']) / 'Library/LaunchAgents').exists())
            self.assertFalse((Path(self.env['HOME']) / 'launchctl-calls').exists())
            self.assertFalse((self.root / 'logs').exists())
        allowed = self.execute('install-market-dashboard-service.sh', '--prepare', '--allow-worktree')
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertFalse((Path(self.env['HOME']) / 'launchctl-calls').exists())
        self.repo = stable_repo
        enabled = self.execute('install-market-dashboard-service.sh', '--enable')
        self.assertEqual(enabled.returncode, 0, enabled.stderr)
        calls = (Path(self.env['HOME']) / 'launchctl-calls').read_text()
        self.assertIn('enable gui/', calls)
        self.assertIn('bootstrap gui/', calls)
        self.assertNotIn('bootout', calls)
        self.assertNotIn('kickstart', calls)


class DashboardHealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.health = health_module()

    def check(self, clock, state=None, enabled=True, trading_dates=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            if state is not None:
                (root / 'market-dashboard').mkdir()
                (root / 'market-dashboard/last-success.json').write_text(json.dumps(state))
            errors, warnings = [], []
            self.health.check_market_dashboard_health(errors, warnings, state_root=root,
                now=datetime.fromisoformat(clock), enabled=enabled, trading_dates=trading_dates)
            return errors, warnings

    def test_uninstalled_is_informational_even_during_trading(self):
        errors, warnings = self.check('2026-11-13T10:20:00+08:00', enabled=False)
        self.assertEqual(errors, [])
        self.assertTrue(any('not yet enabled' in warning for warning in warnings))

    def test_installed_branch_rejects_invalid_config_without_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            repo = home / 'checkout'
            (repo / 'config').mkdir(parents=True)
            agents = home / 'Library/LaunchAgents'
            agents.mkdir(parents=True)
            (agents / f'{LABEL}.plist').write_bytes(plistlib.dumps({'WorkingDirectory': str(repo)}))
            bad_configs = [None, [], 7, {'schedule': None}, {'schedule': []},
                           {'schedule': {'tradingDates': None}},
                           {'schedule': {'tradingDates': '2026-11-13'}},
                           {'schedule': {'tradingDates': {}}},
                           {'schedule': {'tradingDates': [1]}},
                           {'schedule': {'tradingDates': ['not-a-date']}}]
            for config in bad_configs:
                with self.subTest(config=config):
                    (repo / 'config/market-dashboard.json').write_text(json.dumps(config))
                    errors, warnings = [], []
                    with patch.object(self.health.Path, 'home', return_value=home), patch.object(
                            self.health, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as launch:
                        self.health.check_market_dashboard_health(errors, warnings, state_root=home / 'state',
                            now=datetime.fromisoformat('2026-11-13T10:25:00+08:00'))
                    self.assertEqual(launch.call_args.args[0], ['launchctl', 'print', f'gui/{os.getuid()}/{LABEL}'])
                    self.assertTrue(any('configuration invalid' in item for item in errors + warnings))

    def test_expected_completed_bucket_is_required_after_ten_minute_grace(self):
        stale = {'bucket': '2026-11-13:intraday:09:45', 'mode': 'published',
                 'observedAt': '2026-11-13T09:46:00+08:00'}
        errors, _ = self.check('2026-11-13T10:25:00+08:00', stale)
        self.assertTrue(any('market dashboard' in error for error in errors))
        fresh = {'bucket': '2026-11-13:intraday:10:15', 'mode': 'published',
                 'observedAt': '2026-11-13T10:16:00+08:00'}
        self.assertEqual(self.check('2026-11-13T02:25:00+00:00', fresh)[0], [])
        self.assertEqual(self.check('2026-11-13T09:39:00+08:00')[0], [])

    def test_lunch_weekends_and_explicit_holidays_do_not_alert(self):
        for clock in ['2026-11-13T09:00:00+08:00', '2026-11-13T11:30:00+08:00',
                      '2026-11-13T12:00:00+08:00',
                      '2026-11-14T10:25:00+08:00']:
            with self.subTest(clock=clock):
                self.assertEqual(self.check(clock)[0], [])
        self.assertEqual(self.check('2026-11-13T10:25:00+08:00', trading_dates=['2026-11-12'])[0], [])

    def test_close_is_required_only_at_close_deadline_and_has_to_be_published(self):
        self.assertEqual(self.check('2026-11-13T15:29:00+08:00')[0], [])
        self.assertTrue(self.check('2026-11-13T15:30:00+08:00')[0])
        self.assertTrue(self.check('2026-11-13T15:31:00+08:00')[0])
        self.assertTrue(self.check('2026-11-13T17:00:00+08:00')[0])
        close = {'bucket': '2026-11-13:close', 'mode': 'published',
                 'observedAt': '2026-11-13T15:05:00+08:00'}
        self.assertEqual(self.check('2026-11-13T15:30:00+08:00', close)[0], [])
        self.assertEqual(self.check('2026-11-13T17:00:00+08:00', close)[0], [])
        close['mode'] = 'fixture'
        self.assertTrue(self.check('2026-11-13T15:30:00+08:00', close)[0])


class RotationOperationalTests(unittest.TestCase):
    def api(self):
        from tools.market_dashboard import job
        module = getattr(job, 'rotation_operations', None)
        self.assertIsNotNone(module, 'safe shadow operational ledger is missing')
        return module

    def test_health_allowlist_removes_nested_provider_data_and_unsafe_codes(self):
        api = self.api()
        result = api.safe_health({'rotationMode': 'shadow', 'rotationSession': 'close',
            'rotationCoverage': 81, 'rotationUniverseCounts': {'industries': 35, 'concepts': 75,
                'provider': 'private'}, 'rotationLatencySeconds': 30, 'rotationCloseSuccesses': 2,
            'rotationSafeErrorCode': 'secret token', 'rotationObservedAt': '2026-11-13T15:01:00+08:00',
            'rotationSourceAt': '2026-11-13T15:00:00+08:00', 'rawResponse': 'private', 'token': 'secret'})
        self.assertEqual(result['rotationSafeErrorCode'], 'INVALID_STATE')
        self.assertEqual(result['rotationUniverseCounts'], {'industries': 35, 'concepts': 75})
        self.assertNotIn('private', json.dumps(result)); self.assertNotIn('secret', json.dumps(result))
        for key in ('rotationCoverage', 'rotationLatencySeconds', 'rotationCloseSuccesses'):
            self.assertIsNone(api.safe_health({key: float('nan')})[key])

    def test_ledger_is_atomic_private_deduplicated_and_only_counts_official_closes(self):
        api = self.api()
        from tools.market_dashboard.scoring import load_config
        config = load_config(); config['schedule'] = {'tradingDates': ['2026-11-13']}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'market-dashboard-shadow/rotation-ledger.json'
            event = self.event()
            api.update_ledger(path, event, config)
            api.update_ledger(path, event, config)
            self.assertEqual(api.read_ledger(path, config)['successfulCloseDates'], ['2026-11-13'])
            self.assertEqual(len(api.read_ledger(path, config)['events']), 1)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            before = path.read_bytes()
            # Simulate interruption at the real installation boundary.
            with patch.object(Path, 'replace', side_effect=OSError('interrupted')):
                with self.assertRaises(OSError): api.update_ledger(path, self.event(session='14:00'), config)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(path.parent.glob('.rotation-*')), [])
            api.update_ledger(path, self.event(marketDate='2026-11-16', observedAt='2026-11-16T15:05:00+08:00',
                sourceAt='2026-11-16T15:00:00+08:00'), config)
            api.update_ledger(path, self.event(marketDate='2026-11-17', observedAt='2026-11-17T15:05:00+08:00',
                sourceAt='2026-11-17T15:00:00+08:00', success=False, safeErrorCode='COLLECTION_FAILED'), config)
            self.assertEqual(api.read_ledger(path, config)['successfulCloseDates'], ['2026-11-13'])
            self.assertNotIn('token', path.read_text())
            target = Path(tmp)/'outside'; target.write_text('retained')
            path.unlink(); path.symlink_to(target)
            with self.assertRaises(ValueError): api.update_ledger(path, event, config)
            self.assertEqual(target.read_text(), 'retained')

    @staticmethod
    def event(**changes):
        return {'marketDate': '2026-11-13', 'session': 'close', 'observedAt': '2026-11-13T15:05:00+08:00',
            'sourceAt': '2026-11-13T15:00:00+08:00', 'success': True, 'officialClose': True,
            'counts': {'industries': 35, 'concepts': 75}, 'medianCompleteness': 85,
            'minimumCandidateCompleteness': 75, 'candidateCount': 10,
            'latencySeconds': 300, 'publicationSkipped': True, 'safeErrorCode': None,
            'opportunityLists': {'industry': ['882100.WI'], 'concept': ['884201.WI']},
            'token': 'must-not-persist', **changes}

    def test_shadow_opportunity_churn_uses_private_precision_for_top_ten_membership(self):
        api = self.api()
        from tools.market_dashboard.scoring import load_config
        from tools.market_dashboard.sources import INDUSTRY_DEFINITIONS
        config = load_config()
        rows = [dict(id=identity, universe='industry', strength=60, opportunity=80, risk=30,
            completeness=80, heatState='warming', _rawScores={'opportunity': 80+index/1000, 'strength': 60})
            for index, (identity, _) in enumerate(INDUSTRY_DEFINITIONS[:11])]
        block = {'industries': [{k:v for k,v in row.items() if k != '_rawScores'} for row in rows],
                 'concepts': [], 'session': 'close', 'officialClose': True}
        now = datetime.fromisoformat('2026-11-13T15:05:00+08:00')
        event = api.event_from_block(block, now, '2026-11-13T15:00:00+08:00', config, scored_rows=rows)
        self.assertEqual(event['opportunityLists']['industry'], [identity for identity, _ in reversed(INDUSTRY_DEFINITIONS[1:11])])
        self.assertNotIn('_rawScores', json.dumps(event))

    def test_duplicate_summary_retains_unverified_live_evidence_codes(self):
        self.api()
        from tools.market_dashboard import job
        from tools.market_dashboard.tests.test_job import rotation_batches
        with tempfile.TemporaryDirectory() as tmp:
            deps = {'now': datetime.fromisoformat('2026-11-13T15:05:00+08:00'),
                    'state_root': Path(tmp), 'collector': rotation_batches}
            self.assertTrue(job.run_job({'rotation_shadow': True}, deps).success)
            duplicate = job.run_job({'rotation_shadow': True}, deps)
            self.assertEqual(duplicate.status, 'duplicate')
            self.assertIn('LIVE_HISTORY_UNVERIFIED', duplicate.metadata['safeCodes'])
            self.assertIn('LIVE_QUOTA_UNVERIFIED', duplicate.metadata['safeCodes'])

    def test_success_ledger_is_recovered_before_the_next_session_can_replace_state(self):
        self.api()
        from tools.market_dashboard import job
        from tools.market_dashboard.tests.test_job import rotation_batches
        from tools.market_dashboard.scoring import load_config
        config = load_config(); config['schedule'] = {'tradingDates': ['2026-11-13', '2026-11-16']}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deps = {'now': datetime.fromisoformat('2026-11-13T15:05:00+08:00'), 'state_root': root,
                    'config': config, 'collector': rotation_batches}
            with patch.object(job.rotation_operations, 'update_ledger', side_effect=OSError('interrupted')):
                first = job.run_job({'rotation_shadow': True}, deps)
            self.assertTrue(first.success)
            second = job.run_job({'rotation_shadow': True}, deps | {'now': deps['now'].replace(day=16, hour=9, minute=50)})
            self.assertTrue(second.success, second.error_code)
            value = json.loads((root/'market-dashboard-shadow/rotation-ledger.json').read_text())
            self.assertEqual(value['successfulCloseDates'], ['2026-11-13'])
            metadata = job.run_job({'rotation_report': True}, deps).metadata
            self.assertEqual(metadata['rotationSession'], '09:45')
            self.assertEqual(metadata['rotationCloseSuccesses'], 1)

    def release_evidence(self):
        from tools.market_dashboard import rotation_diagnostics
        rows, dates, config = RotationDiagnosticTests().sample()
        config['schedule'] = {'tradingDates': dates}
        events = [self.event(marketDate=day, observedAt=day+'T15:05:00+08:00',
                             sourceAt=day+'T15:00:00+08:00') for day in dates[:9]]
        # Synthetic-only attestation exercises all other gates; never saved live.
        report = rotation_diagnostics.diagnose(rows, dates, config, live_verified=True)
        return events, dates, config, report

    def test_unskipped_or_missing_publication_evidence_fails_even_with_nine_good_closes(self):
        api = self.api(); events, dates, config, report = self.release_evidence()
        ordinary_failure = self.event(marketDate=dates[-1], observedAt=dates[-1]+'T15:05:00+08:00',
            sourceAt=dates[-1]+'T15:00:00+08:00', success=False, safeErrorCode='COLLECTION_FAILED')
        self.assertTrue(api.evaluate_release(api._envelope(events+[ordinary_failure], config), dates, report)['evidenceGatesPassed'])
        for skipped in (False, None):
            with self.subTest(publicationSkipped=skipped):
                unsafe = ordinary_failure | {'success': True, 'safeErrorCode': None}
                if skipped is None: unsafe.pop('publicationSkipped')
                else: unsafe['publicationSkipped'] = skipped
                ledger = api._envelope(events+[unsafe], config)
                self.assertIs(ledger['events'][-1]['success'], False)
                assessment = api.evaluate_release(ledger, dates, report)
                self.assertEqual(assessment['successfulCloses'], 9)
                self.assertIn('PUBLICATION_SKIPPED', assessment['failedGates'])
                self.assertFalse(assessment['evidenceGatesPassed'])
                self.assertEqual(assessment['productionMode'], 'v2')

    def test_historical_disclosed_metrics_must_be_finite_including_one_day_spread(self):
        from copy import deepcopy
        api = self.api(); events, dates, config, report = self.release_evidence()
        ledger = api._envelope(events, config)
        self.assertTrue(api.evaluate_release(ledger, dates, report)['evidenceGatesPassed'])
        corruptions = [('spread', value) for value in ('not-a-number', None, True, float('nan'), float('inf'), -float('inf'))]
        corruptions += [('rankCorrelation', float('inf')), ('hitRate', float('nan')), ('maximumDrawdown', float('inf'))]
        for field, value in corruptions:
            with self.subTest(field=field, value=value):
                changed = deepcopy(report); changed['universes']['industry']['horizons']['1'][field] = value
                result = api.evaluate_release(ledger, dates, changed)
                self.assertIn('HISTORICAL_DIAGNOSTICS_INDUSTRY', result['failedGates'])
                self.assertFalse(result['evidenceGatesPassed'])
                self.assertNotIn('HISTORICAL_DIAGNOSTICS_CONCEPT', result['failedGates'])

    def test_historical_qualification_requires_present_positive_finite_leave_one_out_proof(self):
        from copy import deepcopy
        api = self.api(); events, dates, config, report = self.release_evidence()
        ledger = api._envelope(events, config)
        for field in ('minimumLeaveOneDateSpread', 'minimumLeaveOneSectorSpread'):
            for value in ('absent', -10, 0, None, float('nan'), float('inf'), 'wrong'):
                with self.subTest(field=field, value=value):
                    changed = deepcopy(report)
                    for horizon in ('3', '5'):
                        point = changed['universes']['industry']['horizons'][horizon]
                        if value == 'absent': point.pop(field)
                        else: point[field] = value
                    result = api.evaluate_release(ledger, dates, changed)
                    self.assertIn('HISTORICAL_SPREAD_INDUSTRY', result['failedGates'])
                    self.assertIn('HISTORICAL_DIAGNOSTICS_INDUSTRY', result['failedGates'])
                    self.assertFalse(result['evidenceGatesPassed'])
        # A separate good horizon must not hide a stale true boolean at 3d.
        changed = deepcopy(report)
        changed['universes']['industry']['horizons']['3']['minimumLeaveOneDateSpread'] = -1
        self.assertIn('HISTORICAL_DIAGNOSTICS_INDUSTRY', api.evaluate_release(ledger, dates, changed)['failedGates'])

    def test_invalid_historical_report_shapes_return_safe_failed_gates(self):
        api = self.api()
        for report in ({'universes': []}, {'universes': {'industry': {'horizons': {'3': None}}}},
                       {'universes': {'industry': {'horizons': {'1': {'dates': ['raw-provider-secret']}}}}}):
            result = api.evaluate_release({'events': [], 'versions': {}}, [], report)
            self.assertFalse(result['evidenceGatesPassed'])
            self.assertNotIn('raw-provider-secret', json.dumps(result))

    def test_readonly_evaluation_requires_complete_horizon_diagnostics_and_all_gates(self):
        api = self.api()
        from copy import deepcopy
        from tools.market_dashboard.scoring import load_config
        dates = ['2026-11-%02d' % d for d in (2, 3, 4, 5, 6, 9, 10, 11, 12, 13)]
        config = load_config(); config['schedule'] = {'tradingDates': dates}
        ledger = api._envelope([self.event(marketDate=d, observedAt=d+'T15:05:00+08:00',
            sourceAt=d+'T15:00:00+08:00') for d in dates[:9]], config)
        report = {'liveVerified': True, 'versions': ledger['versions'], 'universes': {
            u: {'listTurnover': .1, 'horizons': {h: {'validDates': 5, 'spread': 1, 'nonDominated': True,
                'minimumLeaveOneDateSpread': .8, 'minimumLeaveOneSectorSpread': .7,
                'rankCorrelation': .1, 'hitRate': .6, 'maximumDrawdown': 2, 'dates': [
                    {'marketDate': d, 'status': 'VALID'} for d in dates[:5]]} for h in ('1', '3', '5')}}
            for u in ('industry', 'concept')}}
        self.assertTrue(api.evaluate_release(ledger, dates, report)['evidenceGatesPassed'])
        for field, value, gate in [('medianCompleteness', 79, 'MEDIAN_COMPLETENESS'),
                ('minimumCandidateCompleteness', 69, 'CANDIDATE_COMPLETENESS'),
                ('latencySeconds', 601, 'CLOSE_LATENCY'), ('publicationSkipped', False, 'PUBLICATION_SKIPPED')]:
            changed = deepcopy(ledger); changed['events'][0][field] = value
            self.assertIn(gate, api.evaluate_release(changed, dates, report)['failedGates'])
        changed = deepcopy(ledger); changed['events'] = changed['events'][:8]
        self.assertIn('CLOSE_SUCCESS_9_OF_10', api.evaluate_release(changed, dates, report)['failedGates'])
        incomplete = deepcopy(report); del incomplete['universes']['concept']['horizons']['1']
        self.assertIn('HISTORICAL_DIAGNOSTICS_CONCEPT', api.evaluate_release(ledger, dates, incomplete)['failedGates'])

    def test_release_window_requires_ten_distinct_official_dates_and_fails_closed(self):
        api = self.api()
        from tools.market_dashboard.scoring import load_config
        dates = ['2026-11-%02d' % d for d in (2, 3, 4, 5, 6, 9, 10, 11, 12, 13)]
        config = load_config(); config['schedule'] = {'tradingDates': dates}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'shadow/rotation-ledger.json'
            for day in dates:
                api.update_ledger(path, self.event(marketDate=day, observedAt=day+'T15:05:00+08:00',
                    sourceAt=day+'T15:00:00+08:00'), config)
            ledger = api.read_ledger(path, config)
            historical = {'liveVerified': True, 'versions': ledger['versions'], 'universes': {
                u: {'listTurnover': .1, 'horizons': {h: {'validDates': 10, 'spread': 1, 'nonDominated': True,
                'minimumLeaveOneDateSpread': .8, 'minimumLeaveOneSectorSpread': .7,
                    'rankCorrelation': .2, 'hitRate': .6, 'maximumDrawdown': 1,
                    'dates': [{'marketDate': d, 'status': 'VALID'} for d in dates]} for h in ('1', '3', '5')}}
                for u in ('industry', 'concept')}}
            evaluation = api.evaluate_release(ledger, dates, historical)
            self.assertTrue(evaluation['evidenceGatesPassed'])
            self.assertFalse(evaluation['productionSwitchApproved'])
            self.assertEqual(evaluation['productionMode'], 'v2')
            self.assertFalse(api.evaluate_release(ledger, dates[:-1]+[dates[-2]], historical)['evidenceGatesPassed'])
            self.assertFalse(api.evaluate_release(ledger, dates, historical | {'liveVerified': False})['evidenceGatesPassed'])
            # A nine-close success rate is allowed; a failed close itself never increments the count.
            api.update_ledger(path, self.event(marketDate=dates[-1], success=False, safeErrorCode='COLLECTION_FAILED'), config)
            self.assertEqual(len(api.read_ledger(path, config)['successfulCloseDates']), 10)
            ledger['events'][0]['counts']['concepts'] = 71
            self.assertIn('UNIVERSE_COVERAGE', api.evaluate_release(ledger, dates, historical)['failedGates'])
            ledger['events'][0]['counts']['concepts'] = 75
            ledger['events'][0]['safeErrorCode'] = 'UNIT_MISMATCH'
            self.assertIn('IDENTITY_UNIT_TIME', api.evaluate_release(ledger, dates, historical)['failedGates'])

    def test_job_records_failed_then_successful_close_without_changing_v2_state(self):
        self.api()
        from tools.market_dashboard import job
        from tools.market_dashboard.tests.test_job import rotation_batches
        from tools.market_dashboard.scoring import load_config
        config = load_config(); config['schedule'] = {'tradingDates': ['2026-11-13']}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); v2 = root/'market-dashboard/last-success.json'
            v2.parent.mkdir(); v2.write_text('{"mode":"published"}')
            health = root/'service-health/market-dashboard.json'; health.parent.mkdir(); health.write_text('{}')
            before = v2.read_bytes(), health.read_bytes()
            deps = {'now': datetime.fromisoformat('2026-11-13T15:05:00+08:00'), 'state_root': root,
                    'config': config, 'collector': lambda c: (_ for _ in ()).throw(ValueError('secret'))}
            failed = job.run_job({'rotation_shadow': True}, deps)
            self.assertFalse(failed.success)
            ledger = root/'market-dashboard-shadow/rotation-ledger.json'
            self.assertEqual(json.loads(ledger.read_text())['successfulCloseDates'], [])
            good = job.run_job({'rotation_shadow': True}, deps | {'collector': rotation_batches})
            self.assertTrue(good.success, good.error_code)
            self.assertEqual(json.loads(ledger.read_text())['successfulCloseDates'], ['2026-11-13'])
            report = job.run_job({'rotation_report': True}, deps)
            self.assertEqual(report.metadata['rotationCloseSuccesses'], 1)
            self.assertEqual(report.metadata['rotationSession'], 'close')
            self.assertEqual((v2.read_bytes(), health.read_bytes()), before)
            self.assertNotIn('secret', json.dumps(report.metadata))
            with patch.object(job.rotation_operations, 'update_ledger', side_effect=OSError('interrupted')):
                other = job.run_job({'rotation_shadow': True}, deps | {'now': deps['now'].replace(day=16), 'collector': rotation_batches,
                    'config': config | {'schedule': {'tradingDates': ['2026-11-13', '2026-11-16']}}})
                self.assertTrue(other.success)
                self.assertIn('LEDGER_WRITE_FAILED', other.metadata['safeCodes'])
            recovered = job.run_job({'rotation_shadow': True}, deps | {'now': deps['now'].replace(day=16),
                'config': config | {'schedule': {'tradingDates': ['2026-11-13', '2026-11-16']}}})
            self.assertEqual(recovered.status, 'duplicate')
            self.assertEqual(json.loads(ledger.read_text())['successfulCloseDates'], ['2026-11-13', '2026-11-16'])


class RotationDiagnosticTests(unittest.TestCase):
    def api(self):
        import importlib
        self.assertIsNotNone(importlib.util.find_spec('tools.market_dashboard.rotation_diagnostics'),
                             'point-in-time offline diagnostics are missing')
        return importlib.import_module('tools.market_dashboard.rotation_diagnostics')

    def sample(self):
        from tools.market_dashboard.scoring import load_config
        from tools.market_dashboard.sources import INDUSTRY_DEFINITIONS
        from tools.market_dashboard.concepts import concept_definitions, load_concept_config
        dates = ['2026-11-%02d' % d for d in (2, 3, 4, 5, 6, 9, 10, 11, 12, 13)]
        config = load_config()
        rows = []
        for day in dates:
            for universe, definitions in [('industry', INDUSTRY_DEFINITIONS), ('concept', concept_definitions(load_concept_config()))]:
                for index, (identity, _) in enumerate(definitions):
                    rows.append(dict(id=identity, universe=universe, marketDate=day, session='close', officialClose=True,
                        observedAt=day+'T15:05:00+08:00', availableAt=day+'T15:05:00+08:00',
                        sectorScoringVersion=config['sectorScoringVersion'], sectorUniverseVersion=config['sectorUniverseVersion'],
                        opportunity=100-index, completeness=90, validCloses=25,
                        metrics={'return1d': (len(definitions)-index)/100}))
        return rows, dates, config

    def test_diagnostics_report_all_horizons_and_dates_separately_without_lookahead(self):
        api = self.api(); rows, dates, config = self.sample()
        result = api.diagnose(rows, dates, config, live_verified=False)
        self.assertFalse(result['liveVerified'])
        for universe in ('industry', 'concept'):
            report = result['universes'][universe]
            self.assertEqual(report['listTurnover'], 0)
            for horizon, valid in [('1', 9), ('3', 7), ('5', 5)]:
                point = report['horizons'][horizon]
                self.assertEqual(point['validDates'], valid)
                self.assertEqual(len(point['dates']), 10)
                self.assertAlmostEqual(point['rankCorrelation'], 1)
                self.assertGreater(point['spread'], 0)
                self.assertEqual(point['hitRate'], 1)
                self.assertEqual(point['maximumDrawdown'], 0)
                self.assertTrue(point['nonDominated'])
        # Future availability invalidates a score as of its close, even if returns are attractive.
        for row in rows:
            if row['marketDate'] == dates[0]: row['availableAt'] = dates[1]+'T15:05:00+08:00'
        changed = api.diagnose(rows, dates, config)
        self.assertEqual(changed['universes']['industry']['horizons']['1']['validDates'], 8)
        self.assertEqual(changed['universes']['industry']['horizons']['1']['dates'][0]['status'], 'NO_PIT_SCORES')

    def test_diagnostic_cli_rejects_malformed_state_without_a_traceback(self):
        self.api(); rows, dates, _ = self.sample()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); calendar = root/'calendar.json'; calendar.write_text(json.dumps(dates))
            state = root/'state.json'
            corrupt = rows[0].copy(); corrupt['_rawScores'] = None
            for value in ([], {'closes': [corrupt]}):
                state.write_text(json.dumps(value))
                result = subprocess.run([sys.executable, '-m', 'tools.market_dashboard.rotation_diagnostics',
                    '--state', str(state), '--calendar', str(calendar)], cwd=REPO, capture_output=True, text=True)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stderr, '')
                self.assertEqual(json.loads(result.stdout), {'liveVerified': False, 'safeErrorCode': 'INVALID_DIAGNOSTIC_INPUT'})

    def test_single_sector_driving_positive_spread_fails_domination_check(self):
        api = self.api(); rows, dates, config = self.sample()
        for row in rows:
            row['metrics']['return1d'] = 5 if row['id'] == '882100.WI' else 0
        result = api.diagnose(rows, dates, config)['universes']['industry']['horizons']['3']
        self.assertGreater(result['spread'], 0)
        self.assertEqual(result['minimumLeaveOneSectorSpread'], 0)
        self.assertFalse(result['nonDominated'])

    def test_compounding_spread_and_high_group_drawdown_have_hand_checked_units(self):
        api = self.api(); rows, dates, config = self.sample()
        for row in rows:
            day = dates.index(row['marketDate'])
            # Every top quintile: +10%, -20%, +10%; bottom quintile: flat.
            # 3-day outcome = 1.1*.8*1.1-1 = -3.2%; drawdown = 20%.
            row['metrics']['return1d'] = (10, -20, 10)[(day-1) % 3] if row['opportunity'] >= 94 else 0
        report = api.diagnose(rows, dates, config)['universes']['industry']['horizons']['3']
        first = report['dates'][0]
        self.assertAlmostEqual(first['spread'], -3.2)
        self.assertAlmostEqual(first['maximumDrawdown'], 20)
        self.assertEqual(first['hitRate'], 0)
        self.assertFalse(report['nonDominated'])

    def test_diagnostics_missing_future_dates_do_not_bridge_and_single_date_cannot_pass(self):
        api = self.api(); rows, dates, config = self.sample()
        rows = [row for row in rows if row['marketDate'] != dates[2]]
        result = api.diagnose(rows, dates, config)
        point = result['universes']['industry']['horizons']['3']
        self.assertEqual(point['dates'][0]['status'], 'MISSING_FORWARD_RETURNS')
        # No fabricated confidence from a single eligible score date.
        rows, dates, config = self.sample()
        for row in rows:
            if row['marketDate'] != dates[0]: row['opportunity'] = None
        result = api.diagnose(rows, dates, config)
        self.assertEqual(result['universes']['industry']['horizons']['3']['validDates'], 1)
        self.assertFalse(result['universes']['industry']['horizons']['3']['nonDominated'])
        with self.assertRaises(ValueError): api.diagnose(rows, dates+[dates[0]], config)


if __name__ == '__main__':
    unittest.main()
