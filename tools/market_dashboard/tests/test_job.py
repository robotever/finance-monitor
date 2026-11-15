"""Offline job contracts: scheduling, validation, publication and fixture flow."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
import json
import io
from contextlib import redirect_stdout
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from tools.market_dashboard import job
from tools.market_dashboard.concepts import load_concept_config
from tools.market_dashboard.scoring import load_config
from tools.market_dashboard.concepts import concept_definitions
from tools.market_dashboard.sources import INDUSTRY_DEFINITIONS, SourceBatch


NOW = datetime.fromisoformat('2026-11-13T10:15:00+08:00')


class ScheduleTests(unittest.TestCase):
    def test_state_root_override_and_precedence_without_logging_paths(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fake_module = root / 'project/newsmonitor/tools/market_dashboard/job.py'
            for explicit, override, expected in [
                (None, None, root / 'project/state'),
                (None, str(root / 'env state'), root / 'env state'),
                (root / 'explicit state', str(root / 'ignored state'), root / 'explicit state'),
            ]:
                deps = {'now': NOW.replace(day=14)}
                if explicit:
                    deps['state_root'] = explicit
                with self.subTest(expected=expected), patch.object(job, '__file__', str(fake_module)), patch.dict(job.os.environ, {}, clear=True):
                    if override:
                        job.os.environ['MARKET_DASHBOARD_STATE_ROOT'] = override
                    output = io.StringIO()
                    with redirect_stdout(output):
                        result = job.run_job({}, deps)
                    self.assertEqual(result.status, 'outside_schedule')
                    self.assertTrue((expected / 'market-dashboard/job.lock').exists())
                    self.assertNotIn(str(root), output.getvalue())

    def test_shanghai_sessions_lunch_weekends_and_close(self):
        for clock, expected in [('09:29', False), ('09:30', True), ('11:29', True),
                                ('11:30', False), ('12:00', False), ('13:00', True),
                                ('14:59', True), ('15:00', True), ('15:15', True),
                                ('15:31', False)]:
            with self.subTest(clock=clock):
                now = datetime.fromisoformat(f'2026-11-13T{clock}:00+08:00')
                self.assertEqual(job.should_collect(now, {}, {}), expected)
        self.assertFalse(job.should_collect(datetime.fromisoformat('2026-11-14T10:00:00+08:00'), {}, {}))
        # Equivalent UTC time must land in the same session.
        self.assertTrue(job.should_collect(datetime.fromisoformat('2026-11-13T02:15:00+00:00'), {}, {}))

    def test_bucket_is_idempotent_and_final_close_only_once(self):
        state = {'bucket': '2026-11-13:intraday:10:15'}
        self.assertFalse(job.should_collect(NOW.replace(minute=29), state, {}))
        self.assertTrue(job.should_collect(NOW.replace(minute=30), state, {}))
        close = {'bucket': '2026-11-13:close'}
        self.assertFalse(job.should_collect(NOW.replace(hour=15, minute=20), close, {}))
        self.assertTrue(job.should_collect(NOW.replace(day=16, hour=15, minute=0), close, {}))

    def test_explicit_calendar_excludes_weekday_holidays(self):
        config = {'schedule': {'tradingDates': ['2026-11-12']}}
        self.assertFalse(job.should_collect(NOW, {}, config))
        with self.assertRaises(ValueError):
            job.should_collect(NOW.replace(tzinfo=None), {}, {})


def valid_payload():
    def obj(id):
        return {'id': id, 'strength': 50, 'heat': None, 'risk': None,
                'completeness': 10, 'missing': ['unavailable'], 'contributors': [],
                'sourceTimestamps': [{'source': 'Wind', 'timestamp': NOW.isoformat()}],
                'change1d': None, 'change5d': None}
    def concept(index, dynamic=False):
        item = obj(f'884{2000 + index}.WI')
        item['name'] = f'概念{index}'
        if dynamic:
            item.update(selectionScore=60, selectedOn='2026-11-13', retainedTradingDays=1)
        return item
    return {'schemaVersion': 'market-dashboard-v2', 'scoringVersion': 'market-score-v0.1',
            'observedAt': NOW.isoformat(), 'marketDate': '2026-11-13', 'session': 'intraday',
            'global': obj('global'), 'aShare': {**obj('a-share'), 'stage': None},
            'styles': [obj(code) for code, _ in job.STYLE_DEFINITIONS],
            'industries': [obj(code) for code, _ in job.INDUSTRY_DEFINITIONS],
            'concepts': {'selectionVersion': 'concept-selection-v0.1',
                         'scoringVersion': 'concept-score-v0.1', 'selectedAt': NOW.isoformat(),
                         'core': [concept(index) for index in range(25)],
                         'dynamic': [concept(index, True) for index in range(25, 35)]},
            'dataStatus': {'completeness': 10, 'stale': False, 'missing': ['unavailable']}}


def v2_payload():
    payload = valid_payload()
    payload['sourceMode'] = {'breadth': 'wind', 'styles': 'wind', 'industries': 'wind',
                             'concepts': 'wind', 'conceptDiscovery': 'mx', 'global': {}}
    return payload


class Response:
    def __init__(self, status=201):
        self.status = status
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class PublishTests(unittest.TestCase):
    def test_bearer_json_timeout_and_no_secret_in_result(self):
        requests = []
        def transport(request, timeout):
            requests.append((request, timeout))
            return Response()
        with patch.object(job, 'urlopen', transport):
            result = job.publish_payload(valid_payload(), 'https://example.test/publish', 'private-token', 8)
        self.assertTrue(result.success)
        self.assertEqual(requests[0][0].get_header('Authorization'), 'Bearer private-token')
        self.assertEqual(requests[0][0].get_header('Content-type'), 'application/json')
        self.assertEqual(requests[0][0].get_header('User-agent'), 'NewsmonitorMarketDashboard/1.0')
        self.assertEqual(requests[0][1], 8)
        self.assertEqual(json.loads(requests[0][0].data)['styles'][0]['id'], '000300.SH')
        self.assertNotIn('private-token', repr(result))

    def test_network_and_5xx_retry_but_4xx_never_retry(self):
        for status, expected_calls in [(503, 3), (429, 1), (401, 1), (400, 1), (None, 3)]:
            calls = []
            def transport(request, timeout):
                calls.append(request)
                if status is None:
                    raise URLError('private-token provider detail')
                raise HTTPError(request.full_url, status, 'private-token', None, None)
            with self.subTest(status=status), patch.object(job, 'urlopen', transport), patch.object(job.time, 'sleep'):
                result = job.publish_payload(valid_payload(), 'https://example.test/publish', 'private-token', 8)
                self.assertFalse(result.success)
                self.assertEqual(len(calls), expected_calls)
                self.assertEqual(result.attempts, expected_calls)
                self.assertNotIn('private-token', repr(result))

    def test_transient_failure_can_recover(self):
        calls = []
        def transport(request, timeout):
            calls.append(request)
            if len(calls) == 1:
                raise TimeoutError('private-token')
            return Response(200)
        with patch.object(job, 'urlopen', transport), patch.object(job.time, 'sleep'):
            result = job.publish_payload(valid_payload(), 'https://example.test/publish', 'private-token', 8)
        self.assertTrue(result.success)
        self.assertEqual(result.attempts, 2)

    def test_invalid_payloads_are_rejected_before_network(self):
        mutations = [lambda p: p.update(schemaVersion='old'),
                     lambda p: p.update(scoringVersion='old'),
                     lambda p: p.pop('observedAt'),
                     lambda p: p.update(observedAt='2026-11-13T10:15:00'),
                     lambda p: p['global'].update(strength=101),
                     lambda p: p['global'].update(strength=42.2),
                     lambda p: p['dataStatus'].update(completeness=100),
                     lambda p: p['global'].update(completeness=0),
                     lambda p: p['global'].update(strength=float('nan')),
                     lambda p: p['dataStatus'].update(completeness=-1),
                     lambda p: p['dataStatus'].update(completeness=0),
                     lambda p: p['industries'].pop(),
                     lambda p: p['styles'][-1].update(id=p['styles'][0]['id']),
                     lambda p: p['global'].update(rawRows=[]),
                     lambda p: p['aShare'].update(stage='扩张'),
                     lambda p: p['global'].pop('missing'),
                     lambda p: p['global'].update(sourceTimestamps=[])]
        for mutate in mutations:
            payload = valid_payload()
            mutate(payload)
            with self.subTest(mutation=mutate), patch.object(job, 'urlopen') as network:
                result = job.publish_payload(payload, 'https://example.test/publish', 'private-token', 8)
                self.assertFalse(result.success)
                self.assertEqual(result.error_code, 'INVALID_PAYLOAD')
                network.assert_not_called()

    def test_low_completeness_permitted_and_configurable_minimum_enforced(self):
        job.validate_payload(valid_payload(), load_config())
        config = load_config()
        config['publication'] = {'minimumCompleteness': 20}
        with self.assertRaises(job.ValidationError):
            job.validate_payload(valid_payload(), config)

    def test_cold_start_discount_does_not_require_invented_missing_inputs(self):
        payload = valid_payload()
        for obj in [payload['global'], payload['aShare'], *payload['styles'], *payload['industries'],
                    *payload['concepts']['core'], *payload['concepts']['dynamic']]:
            obj.update(strength=50, heat=60, risk=40, completeness=85, missing=[])
        payload['dataStatus'].update(completeness=85, missing=[])
        job.validate_payload(payload)

    def test_missing_token_and_insecure_target_are_rejected(self):
        for url, token in [('https://example.test', ''), ('http://example.test', 'private-token'),
                           ('https://user:private-token@example.test', 'private-token')]:
            with self.subTest(url=url), patch.object(job, 'urlopen') as network:
                self.assertFalse(job.publish_payload(valid_payload(), url, token, 8).success)
                network.assert_not_called()


class JobTests(unittest.TestCase):
    def args(self, **overrides):
        return SimpleNamespace(**({'dry_run': False, 'fixture': False, 'force': False,
                                   'skip_publish': False, 'url': 'https://example.test/publish',
                                   'token': 'private-token', 'timeout': 8} | overrides))

    def deps(self, directory, **overrides):
        return {'now': NOW, 'state_root': Path(directory),
                'collector': lambda config: job.collect_batches(config, fixture=True),
                'publisher': lambda *args, **kwargs: job.PublishResult(True, 201, 1)} | overrides

    def test_rotation_and_legacy_close_commit_together_only_after_successful_publication(self):
        from tools.market_dashboard.tests.test_rotation_store import snapshot
        close = NOW.replace(hour=15, minute=5)
        derive = job.derive_inputs
        def sector_inputs(*args):
            inputs = derive(*args)
            inputs['sectorRows'] = [dict(id=row['id'], name=row['name'], universe=row['universe'],
                marketDate=row['marketDate'], session='close', observedAt=row['observedAt'],
                metrics={'return1d': 1., 'return5d': 2., 'return20d': 3.})
                for row in snapshot(str(args[1].date()))['sectors']]
            return inputs
        def close_batches(config):
            batches = job.collect_batches(config, fixture=True)
            for group in ('breadth', 'styles', 'industries', 'concepts'):
                for row in batches[group].rows:
                    row['_timestamp'] = config['sources']['now']
            return batches
        with TemporaryDirectory() as directory, patch.object(job, 'derive_inputs', sector_inputs):
            deps = self.deps(directory, now=close, collector=close_batches)
            for failure in ['publish', 'validation', 'collection']:
                bad_deps = dict(deps)
                if failure == 'publish':
                    bad_deps['publisher'] = lambda *a, **k: job.PublishResult(False, 503, 3, 'HTTP_503')
                elif failure == 'validation':
                    bad_deps['builder'] = lambda *a: {'invalid': True}
                else:
                    bad_deps['collector'] = lambda config: (_ for _ in ()).throw(ValueError('provider'))
                failed = job.run_job(self.args(), bad_deps)
                self.assertFalse(failed.success)
                self.assertEqual(failed.status, {'publish': 'publish', 'validation': 'validate', 'collection': 'collect'}[failure])
                self.assertFalse((Path(directory)/'market-dashboard/last-success.json').exists())
            result = job.run_job(self.args(), deps)
            self.assertTrue(result.success, result.error_code)
            path = Path(directory)/'market-dashboard/last-success.json'
            saved = path.read_bytes()
            state = json.loads(saved)
            self.assertEqual(len(state.get('rotation', {}).get('closes', [])), 110)
            self.assertNotIn('rotation', state['payload'])
            self.assertNotIn('_rawScores', json.dumps(result.payload))
            duplicate = job.run_job(self.args(force=True), deps)
            self.assertEqual(duplicate.status, 'duplicate')
            self.assertEqual(path.read_bytes(), saved)
            for mode in ['publish', 'validation', 'collection']:
                bad_deps = deps | {'now': NOW.replace(day=16, hour=15, minute=5)}
                if mode == 'publish':
                    bad_deps['publisher'] = lambda *a, **k: job.PublishResult(False, 503, 3, 'HTTP_503')
                elif mode == 'validation':
                    bad_deps['builder'] = lambda *a: {'invalid': True}
                else:
                    bad_deps['collector'] = lambda config: (_ for _ in ()).throw(ValueError('provider'))
                failed = job.run_job(self.args(), bad_deps)
                self.assertFalse(failed.success)
                self.assertEqual(failed.status, {'publish': 'publish', 'validation': 'validate', 'collection': 'collect'}[mode])
                self.assertEqual(path.read_bytes(), saved)

    def test_rotation_incomplete_close_rejects_before_publish_and_preserves_state(self):
        from tools.market_dashboard.tests.test_rotation_store import snapshot
        with TemporaryDirectory() as directory:
            deps = self.deps(directory)
            self.assertTrue(job.run_job(self.args(), deps).success)
            path = Path(directory)/'market-dashboard/last-success.json'
            saved = path.read_bytes()
            derive = job.derive_inputs
            def incomplete(*args):
                inputs = derive(*args)
                inputs['sectorRows'] = snapshot()['sectors'][:-1]
                return inputs
            def close_batches(config):
                batches = job.collect_batches(config, fixture=True)
                for group in ('breadth', 'styles', 'industries', 'concepts'):
                    for row in batches[group].rows:
                        row['_timestamp'] = config['sources']['now']
                return batches
            with patch.object(job, 'derive_inputs', incomplete):
                result = job.run_job(self.args(), deps | {'now': NOW.replace(hour=15, minute=5),
                    'collector': close_batches,
                    'publisher': lambda *a, **k: self.fail('invalid close published')})
            self.assertFalse(result.success)
            self.assertEqual(result.status, 'score')
            self.assertEqual(path.read_bytes(), saved)

    def test_fixture_end_to_end_missing_fields_safe_metadata_no_writes(self):
        with TemporaryDirectory() as directory:
            result = job.run_job(self.args(fixture=True, dry_run=True),
                                 {'state_root': Path(directory)})
            self.assertTrue(result.success, result.error_code)
            payload = result.payload
            self.assertIsInstance(payload['global'], dict)
            self.assertIsInstance(payload['aShare'], dict)
            self.assertEqual(len(payload['styles']), 6)
            self.assertEqual(len(payload['industries']), 35)
            job.validate_payload(payload)
            for industry in payload['industries']:
                for missing in ('advancingShare', 'decliningShare', 'relativeReturn5d',
                                'relativeReturn20d', 'mediumTrendDeterioration'):
                    self.assertIn(missing, industry['missing'])
                self.assertLess(industry['completeness'], 100)
            self.assertEqual(payload['sourceMode']['global'], {'DGS10': 'fred', 'gold': 'mx'})
            self.assertEqual(payload['sourceMode']['industries'], 'wind')
            self.assertEqual(list(Path(directory).rglob('*')), [])
            public = json.dumps(payload, ensure_ascii=False)
            for raw_key in ('rawRows', '_units', '最新成交额', 'SYNTHETIC_GOLD', 'private-token', 'indicators'):
                self.assertNotIn(raw_key, public)

    def test_v2_fixture_contains_strict_core_and_dynamic_concepts(self):
        with TemporaryDirectory() as directory:
            result = job.run_job(self.args(fixture=True, dry_run=True),
                                 {'state_root': Path(directory)})
        self.assertTrue(result.success, result.error_code)
        payload = result.payload
        self.assertEqual(payload['schemaVersion'], 'market-dashboard-v2')
        self.assertEqual(len(payload['concepts']['core']), 25)
        self.assertEqual(len(payload['concepts']['dynamic']), 10)
        core = {item['id'] for item in payload['concepts']['core']}
        dynamic = {item['id'] for item in payload['concepts']['dynamic']}
        self.assertEqual(len(core), 25)
        self.assertEqual(len(dynamic), 10)
        self.assertFalse(core & dynamic)
        self.assertEqual(payload['sourceMode']['concepts'], 'wind')
        self.assertEqual(payload['sourceMode']['conceptDiscovery'], 'mx')
        self.assertLessEqual(len(json.dumps(payload, ensure_ascii=False).encode()), 256 * 1024)
        job.validate_payload(payload)

    def test_v2_validation_rejects_concept_count_overlap_and_metadata_mutations(self):
        mutations = [
            lambda p: p['concepts']['core'].pop(),
            lambda p: p['concepts']['dynamic'].pop(),
            lambda p: p['concepts']['dynamic'][0].update(id=p['concepts']['core'][0]['id']),
            lambda p: p['concepts']['dynamic'][0].update(retainedTradingDays=0),
            lambda p: p['concepts']['dynamic'][0].update(selectionScore=101),
            lambda p: p['sourceMode'].update(concepts='mx'),
        ]
        for mutate in mutations:
            payload = v2_payload()
            mutate(payload)
            with self.subTest(mutation=mutate), self.assertRaises(job.ValidationError):
                job.validate_payload(payload, load_config())

    def test_concept_collection_failure_preserves_last_selection_or_fails_closed(self):
        from tools.market_dashboard.sources import SourceBatch
        with TemporaryDirectory() as directory:
            deps = self.deps(directory)
            first = job.run_job(self.args(), deps)
            self.assertTrue(first.success, first.error_code)
            previous = first.payload['concepts']
            def failed_concepts(config):
                batches = job.collect_batches(config, fixture=True)
                batches['concepts'] = SourceBatch('Wind', source_mode='wind',
                    errors=[{'source': 'Wind', 'code': 'backend_error', 'group': 'concepts'}])
                return batches
            second = job.run_job(self.args(), deps | {'now': NOW.replace(minute=30),
                                                       'collector': failed_concepts})
            self.assertTrue(second.success, second.error_code)
            self.assertEqual(second.payload['concepts'], previous)
            self.assertTrue(second.payload['dataStatus']['stale'])

        with TemporaryDirectory() as directory:
            result = job.run_job(self.args(), self.deps(directory, collector=failed_concepts))
            self.assertFalse(result.success)
            self.assertEqual(result.error_code, 'COLLECTION_FAILED')

    def test_close_selection_advances_once_and_duplicate_does_not_collect(self):
        close = NOW.replace(hour=15, minute=5)
        def close_batches(config):
            batches = job.collect_batches(config, fixture=True)
            for group in ('breadth', 'styles', 'industries', 'concepts'):
                for row in batches[group].rows:
                    row['_timestamp'] = '2026-11-13T15:00:02+08:00'
            return batches
        with TemporaryDirectory() as directory:
            deps = self.deps(directory, now=close, collector=close_batches)
            first = job.run_job(self.args(), deps)
            self.assertTrue(first.success, first.error_code)
            retained = [item['retainedTradingDays'] for item in first.payload['concepts']['dynamic']]
            duplicate = job.run_job(self.args(force=True), deps | {
                'now': close.replace(minute=20),
                'collector': lambda config: self.fail('duplicate close collected again'),
            })
            self.assertEqual(duplicate.status, 'duplicate')
            state = json.loads((Path(directory) / 'market-dashboard/last-success.json').read_text())
            self.assertEqual([item['retainedTradingDays'] for item in state['payload']['concepts']['dynamic']], retained)

    def test_next_day_intraday_reuses_roster_without_advancing_hold_days(self):
        with TemporaryDirectory() as directory:
            first = job.run_job(self.args(), self.deps(directory))
            self.assertTrue(first.success, first.error_code)
            previous = first.payload['concepts']
            next_day = NOW.replace(day=16)
            def next_day_batches(config):
                batches = job.collect_batches(config, fixture=True)
                for group in ('breadth', 'styles', 'industries', 'concepts'):
                    for row in batches[group].rows:
                        row['_timestamp'] = next_day.isoformat()
                return batches
            second = job.run_job(self.args(), self.deps(
                directory, now=next_day, collector=next_day_batches))
            self.assertTrue(second.success, second.error_code)
            self.assertEqual([item['id'] for item in second.payload['concepts']['dynamic']],
                             [item['id'] for item in previous['dynamic']])
            self.assertEqual([item['retainedTradingDays'] for item in second.payload['concepts']['dynamic']],
                             [item['retainedTradingDays'] for item in previous['dynamic']])
            self.assertEqual(second.payload['concepts']['selectedAt'], previous['selectedAt'])

    def test_cold_start_uses_config_and_never_hardcoded_bounds(self):
        config = load_config()
        batches = job.collect_batches(config, fixture=True)
        inputs = job.derive_inputs(batches, NOW, config)
        scored = job.build_dashboard_payload(inputs, [], config)
        self.assertEqual(scored['global']['strength'], 59)
        self.assertEqual(scored['global']['completeness'], 9)
        config['normalization']['fixedBounds']['DGS10'] = {'min': 0, 'max': 20}
        inputs = job.derive_inputs(batches, NOW, config)
        self.assertEqual(job.build_dashboard_payload(inputs, [], config)['global']['strength'], 80)
        del config['normalization']['fixedBounds']['DGS10']
        inputs = job.derive_inputs(batches, NOW, config)
        scored = job.build_dashboard_payload(inputs, [], config)
        self.assertIsNone(scored['global']['strength'])
        self.assertIn('ratesLiquidity', scored['global']['missing'])
        # Once sufficient observations exist, removing cold bounds must not lose evidence.
        row = batches['global'].rows[0]
        row['history'] = [{'value': v, 'timestamp': NOW.isoformat()} for v in range(20)]
        inputs = job.derive_inputs(batches, NOW, config)
        self.assertIsNotNone(job.build_dashboard_payload(inputs, [], config)['global']['strength'])

    def test_success_duplicate_and_close_state_and_health(self):
        with TemporaryDirectory() as directory:
            deps = self.deps(directory)
            first = job.run_job(self.args(), deps)
            self.assertTrue(first.success, first.error_code)
            state_path = Path(directory) / 'market-dashboard/last-success.json'
            state = json.loads(state_path.read_text())
            self.assertEqual(state['bucket'], '2026-11-13:intraday:10:15')
            self.assertEqual(state['mode'], 'published')
            self.assertEqual(state['payload']['sourceMode']['global']['DGS10'], 'fred')
            def unexpected_collection(config):
                self.fail('Repeated bucket collected again')
            duplicate = job.run_job(self.args(force=True), deps | {'collector': unexpected_collection})
            self.assertTrue(duplicate.success)
            self.assertEqual(duplicate.status, 'duplicate')
            health = json.loads((Path(directory) / 'service-health/market-dashboard.json').read_text())
            self.assertEqual(health['lastPublishStatus'], 'published')
            self.assertIn('sourceCounts', health)
            self.assertIn('completeness', health)
            self.assertNotIn('private-token', json.dumps(health))

    def test_publication_failure_preserves_success_and_redacts_health(self):
        with TemporaryDirectory() as directory:
            deps = self.deps(directory)
            self.assertTrue(job.run_job(self.args(), deps).success)
            state_path = Path(directory) / 'market-dashboard/last-success.json'
            previous = state_path.read_bytes()
            deps.update(now=NOW.replace(minute=30),
                        publisher=lambda *a, **k: job.PublishResult(False, 401, 1, 'HTTP_401'))
            failed = job.run_job(self.args(), deps)
            self.assertFalse(failed.success)
            self.assertEqual(state_path.read_bytes(), previous)
            health = json.loads((Path(directory) / 'service-health/market-dashboard.json').read_text())
            self.assertEqual(health['stage'], 'publish')
            self.assertEqual(health['lastPublishStatus'], 'failed')
            self.assertEqual(health['errorCode'], 'HTTP_401')

    def test_force_bypasses_only_schedule_and_validation_still_runs(self):
        with TemporaryDirectory() as directory:
            deps = self.deps(directory, now=NOW.replace(hour=12))
            self.assertEqual(job.run_job(self.args(), deps).status, 'outside_schedule')
            deps['builder'] = lambda inputs, previous, config: valid_payload() | {'schemaVersion': 'old'}
            with patch.object(job, 'urlopen') as network:
                result = job.run_job(self.args(force=True), deps)
                self.assertFalse(result.success)
                self.assertEqual(result.error_code, 'INVALID_PAYLOAD')
                network.assert_not_called()
            self.assertFalse((Path(directory) / 'market-dashboard/last-success.json').exists())

    def test_skip_publish_and_dry_run_do_not_replace_last_success(self):
        with TemporaryDirectory() as directory:
            deps = self.deps(directory)
            self.assertTrue(job.run_job(self.args(), deps).success)
            state_path = Path(directory) / 'market-dashboard/last-success.json'
            previous = state_path.read_bytes()
            deps['now'] = NOW.replace(minute=30)
            for flag in ('skip_publish', 'dry_run'):
                result = job.run_job(self.args(**{flag: True}), deps)
                self.assertTrue(result.success)
                self.assertEqual(state_path.read_bytes(), previous)

    def test_lock_prevents_concurrent_collection_and_releases_on_error(self):
        import fcntl
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'market-dashboard'
            path.mkdir()
            with (path / 'job.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = job.run_job(self.args(), self.deps(directory))
                self.assertEqual(result.status, 'locked')
            def broken(config):
                raise RuntimeError('private-token upstream raw response')
            result = job.run_job(self.args(), self.deps(directory, collector=broken))
            self.assertFalse(result.success)
            self.assertNotIn('private-token', repr(result))
            health = (Path(directory) / 'service-health/market-dashboard.json').read_text()
            self.assertNotIn('private-token', health)
            self.assertTrue(job.run_job(self.args(), self.deps(directory)).success)

    def test_live_dry_run_skips_collector_when_production_lock_is_held(self):
        import fcntl
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'market-dashboard'
            path.mkdir()
            calls = []
            def collector(config):
                calls.append('collected')
                return job.collect_batches(config, fixture=True)
            with (path / 'job.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = job.run_job(self.args(dry_run=True), self.deps(directory, collector=collector))
            self.assertTrue(result.success)
            self.assertEqual(result.status, 'locked')
            self.assertEqual(calls, [])
            self.assertEqual(list(Path(directory).rglob('*.json')), [])

    def test_live_dry_run_holds_shared_lock_but_writes_no_snapshot_or_health(self):
        import fcntl
        with TemporaryDirectory() as directory:
            lock_path = Path(directory) / 'market-dashboard/job.lock'
            lock_path.parent.mkdir()
            calls, held_during_collection = [], []
            def collector(config):
                calls.append('collected')
                with lock_path.open('a') as contender:
                    try:
                        fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        held_during_collection.append(True)
                    else:
                        held_during_collection.append(False)
                return job.collect_batches(config, fixture=True)
            result = job.run_job(self.args(dry_run=True), self.deps(directory, collector=collector))
            self.assertTrue(result.success, result.error_code)
            self.assertEqual(result.status, 'dry_run')
            self.assertEqual(calls, ['collected'])
            self.assertEqual(held_during_collection, [True])
            self.assertEqual(list(Path(directory).rglob('*.json')), [])
            self.assertEqual(lock_path.read_bytes(), b'')
            with lock_path.open('a') as released:
                fcntl.flock(released, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_source_observations_during_collection_use_completion_clock(self):
        clocks = iter([NOW, NOW.replace(minute=16)])
        def collector(config):
            batches = job.collect_batches(config, fixture=True)
            for group in ('breadth', 'styles', 'industries'):
                for row in batches[group].rows:
                    row['_timestamp'] = '2026-11-13T10:15:30+08:00'
            return batches
        with TemporaryDirectory() as directory:
            result = job.run_job(self.args(), self.deps(directory, now=lambda: next(clocks), collector=collector))
            self.assertTrue(result.success, result.error_code)
            self.assertEqual(result.payload['observedAt'], '2026-11-13T10:16:00+08:00')

    def test_unused_global_rows_do_not_advance_scored_observation_clock(self):
        config = load_config()
        batches = job.collect_batches(config, fixture=True)
        batches['global'].rows[1]['timestamp'] = NOW.isoformat()
        inputs = job.derive_inputs(batches, NOW, config)
        self.assertEqual(inputs['global']['observedAt'], '2026-11-12T00:00:00+00:00')

    def test_wrong_global_units_remain_unavailable(self):
        config = load_config()
        batches = job.collect_batches(config, fixture=True)
        batches['global'].rows[0]['unit'] = 'USD'
        inputs = job.derive_inputs(batches, NOW, config)
        scored = job.build_dashboard_payload(inputs, [], config)
        self.assertIsNone(scored['global']['strength'])
        self.assertIn('ratesLiquidity', scored['global']['missing'])

    def test_stale_or_incompatible_units_never_enter_scores(self):
        config = load_config()
        batches = job.collect_batches(config, fixture=True)
        industry = batches['industries'].rows[0]
        industry['_timestamp'] = '2026-11-12T10:15:00+08:00'
        industry['_units']['最新成交额(亿元)'] = 'USD'
        inputs = job.derive_inputs(batches, NOW, config)
        scored = job.build_dashboard_payload(inputs, [], config)
        self.assertEqual(scored['industries'][0]['completeness'], 0)
        self.assertIsNone(scored['industries'][0]['strength'])
        self.assertTrue(scored['dataStatus']['stale'])
        batches = job.collect_batches(config, fixture=True)
        industry = batches['industries'].rows[0]
        industry['_units']['最新主力净流入额(亿元)'] = 'USD'
        inputs = job.derive_inputs(batches, NOW, config)
        self.assertFalse(inputs['industries'][0]['indicators']['mainFlowDirection']['available'])

    def test_fixture_dry_run_ignores_live_state_and_prints_compact_summary(self):
        with TemporaryDirectory() as directory:
            deps = self.deps(directory)
            self.assertTrue(job.run_job(self.args(), deps).success)
            result = job.run_job(self.args(fixture=True, dry_run=True), {'state_root': Path(directory)})
            self.assertEqual(result.status, 'dry_run')
            self.assertEqual(result.payload['global']['change1d'], None)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(job.main(['--fixture', '--dry-run']), 0)
        summary = json.loads(output.getvalue())
        self.assertEqual(summary['objectCounts'], {'global': 1, 'aShare': 1, 'styles': 6,
                                                   'industries': 35, 'coreConcepts': 25,
                                                   'dynamicConcepts': 10})
        self.assertTrue(summary['synthetic'])
        self.assertLess(len(output.getvalue()), 500)

    def test_final_close_rejects_intraday_observations_then_is_idempotent(self):
        def close_batches(config, clock):
            batches = job.collect_batches(config, fixture=True)
            for group in ('breadth', 'styles', 'industries', 'concepts'):
                for row in batches[group].rows:
                    row['_timestamp'] = f'2026-11-13T{clock}:00+08:00'
            return batches
        with TemporaryDirectory() as directory:
            deps = self.deps(directory, now=NOW.replace(hour=15, minute=5),
                             collector=lambda config: close_batches(config, '14:55'))
            premature = job.run_job(self.args(), deps)
            self.assertFalse(premature.success)
            deps['collector'] = lambda config: close_batches(config, '15:00')
            final = job.run_job(self.args(), deps)
            self.assertTrue(final.success, final.error_code)
            self.assertEqual(final.payload['session'], 'close')
            self.assertEqual(job.run_job(self.args(), deps | {'now': NOW.replace(hour=15, minute=25)}).status, 'duplicate')

    def test_yuan_and_hundred_million_yuan_are_equivalent_for_ratios(self):
        config = load_config()
        original = job.collect_batches(config, fixture=True)
        changed = deepcopy(original)
        for row in changed['industries'].rows:
            for field in ('最新成交额(亿元)', '最新主力净流入额(亿元)'):
                row[field] *= 100000000
                row['_units'][field] = '元'
        first = job.build_dashboard_payload(job.derive_inputs(original, NOW, config), [], config)
        second = job.build_dashboard_payload(job.derive_inputs(changed, NOW, config), [], config)
        self.assertEqual(first['industries'], second['industries'])

    def test_fixture_mode_cannot_publish_to_live_target(self):
        with TemporaryDirectory() as directory:
            result = job.run_job(self.args(fixture=True), self.deps(directory))
            self.assertFalse(result.success)
            self.assertEqual(result.error_code, 'FIXTURE_PUBLISH_DISABLED')
            self.assertFalse((Path(directory) / 'market-dashboard/last-success.json').exists())


def rotation_batches(config):
    """Sanitized existing provider fixtures, stamped at a controlled clock."""
    batches = job.collect_batches(config, fixture=True)
    for group in ('breadth', 'styles', 'industries', 'concepts'):
        for row in batches[group].rows:
            row['_timestamp'] = config['sources']['now']
    return batches


def decode_rotation_components(block, row):
    """Independent wire decoder; bit positions and node links are public schema."""
    if 'componentNodes' not in block:
        return row['components']
    fields = ('value', 'coverage', 'missing', 'usedWeight', 'totalWeight',
              'effectiveWeight', 'percentile', 'parts')
    if block['componentFields'] != list(fields):
        raise AssertionError('Unexpected compact component fields')
    def decode(index):
        mask, *values = block['componentNodes'][index]
        iterator = iter(values)
        result = {}
        for bit, key in enumerate(fields):
            if mask & (1 << bit):
                value = next(iterator)
                if key == 'missing':
                    value = [block['missingReasons'][item] for item in value]
                elif key == 'parts':
                    value = {block['componentPartNames'][name]: decode(child) for name, child in value}
                result[key] = value
        if len(result) != len(values):
            raise AssertionError('Unexpected compact component values')
        return result
    return {name: decode(index) for name, index in row['components'].items()}


class RotationShadowTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.now = NOW.replace(hour=9, minute=50)
        self.config.setdefault('sources', {})['now'] = self.now.isoformat()

    def test_windows_do_not_backfill_and_use_shanghai_clock(self):
        schedule = getattr(job, 'scheduled_rotation_session', None)
        self.assertTrue(callable(schedule), 'rotation scheduler is missing')
        for clock, expected in [('09:44:59', None), ('09:45:00', '09:45'),
                ('09:55:00', '09:45'), ('09:55:01', None), ('11:29:59', None),
                ('11:30:00', '11:30'), ('11:40:00', '11:30'), ('11:40:01', None),
                ('14:00:00', '14:00'), ('14:10:00', '14:00'), ('14:10:01', None),
                ('15:00:00', 'close'), ('15:30:00', 'close'), ('15:30:01', None)]:
            now = datetime.fromisoformat('2026-11-13T'+clock+'+08:00')
            with self.subTest(clock=clock):
                self.assertEqual(schedule(now, {}, self.config), expected)
                self.assertEqual(schedule(now.astimezone(job.timezone.utc), {}, self.config), expected)
        self.assertIsNone(schedule(NOW.replace(day=14, hour=9, minute=50), {}, self.config))
        holiday = deepcopy(self.config); holiday['schedule'] = {'tradingDates': ['2026-11-12']}
        self.assertIsNone(schedule(self.now, {}, holiday))
        self.assertIsNone(schedule(self.now, {'bucket': '2026-11-13:09:45'}, self.config))

    def test_full_rotation_block_and_mixed_payload_are_derived_and_bounded(self):
        builder = getattr(job, 'build_rotation_block', None)
        self.assertTrue(callable(builder), 'rotation block builder is missing')
        batches = rotation_batches(self.config)
        block = builder(batches, [], self.config)
        self.assertEqual(block['sectorScoringVersion'], 'sector-score-v0.2')
        self.assertEqual(block['sectorUniverseVersion'], 'sector-universe-v0.1')
        rows = block['industries'] + block['concepts']
        self.assertEqual({row['id'] for row in block['industries']}, {code for code, _ in INDUSTRY_DEFINITIONS})
        self.assertEqual({row['id'] for row in block['concepts']}, {code for code, _ in concept_definitions(load_concept_config())})
        self.assertEqual((len(block['industries']), len(block['concepts'])), (35, 75))
        for row in rows:
            self.assertNotIn('heat', row)
            self.assertIn('heatState', row)
            self.assertIsNone(row['opportunity'])
            self.assertLess(row['validCloses'], 20)
            self.assertIn('components', row)
            self.assertIn('axisCompleteness', row)
        inputs = job.derive_inputs(batches, self.now, self.config)
        payload = job.build_rotation_payload(inputs, [], block, self.config)
        legacy = job.build_market_payload(inputs, [], self.config)
        self.assertEqual(payload['schemaVersion'], 'market-dashboard-v3')
        self.assertEqual(payload['concepts']['scoringVersion'], 'sector-score-v0.2')
        self.assertEqual(payload['concepts']['selectionScoringVersion'], 'concept-score-v0.1')
        self.assertEqual(block['auditDefinitions']['gates']['minimumCloses'], 20)
        for group in ('global', 'aShare', 'styles'):
            self.assertEqual(payload[group], legacy[group])
        self.assertEqual(payload['sectorRotation'], block)
        self.assertEqual(len(payload['concepts']['core']), 25)
        self.assertEqual(len(payload['concepts']['dynamic']), 10)
        for row in payload['industries'] + payload['concepts']['core'] + payload['concepts']['dynamic']:
            self.assertIn('opportunity', row)
            self.assertNotIn('heat', row)
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
        self.assertLessEqual(len(encoded), 256*1024)
        def check_keys(value):
            if isinstance(value, dict):
                self.assertFalse({'metrics', '_rawScores', '_units', '_timestamp', 'rawRows',
                    'netFlow1d', 'amount1d', 'close', 'token', 'rawResponse'} & value.keys())
                for child in value.values(): check_keys(child)
            elif isinstance(value, list):
                for child in value: check_keys(child)
        check_keys(payload)
        self.assertFalse(block['releaseEligible'])
        self.assertIn('LIVE_HISTORY_UNVERIFIED', block['safeCodes'])
        with patch.object(job, 'urlopen') as network:
            result = job.publish_payload(payload, 'https://example.test/publish', 'synthetic')
            self.assertEqual(result.error_code, 'INVALID_PAYLOAD')
            network.assert_not_called()

    def test_rotation_rejects_missing_duplicate_unknown_future_or_nonwind_sector_rows(self):
        builder = getattr(job, 'build_rotation_block', None)
        self.assertTrue(callable(builder), 'rotation block builder is missing')
        for mutation in ('missing', 'duplicate', 'unknown', 'future', 'nonwind', 'version'):
            batches = rotation_batches(self.config)
            if mutation == 'missing': batches['concepts'].rows.pop()
            elif mutation == 'duplicate': batches['concepts'].rows[-1] = deepcopy(batches['concepts'].rows[0])
            elif mutation == 'unknown': batches['industries'].rows[0]['id'] = 'unknown'
            elif mutation == 'future': batches['concepts'].rows[0]['_timestamp'] = '2026-11-13T09:51:00+08:00'
            elif mutation == 'version': self.config['sectorUniverseVersion'] = 'unknown'
            else: batches['concepts'] = SourceBatch('MX', rows=batches['concepts'].rows, source_mode='mx')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                builder(batches, [], self.config)
        self.config = load_config()

    def test_local_close_builder_rejects_after_exact_catchup_deadline(self):
        self.config['sources']['now'] = '2026-11-13T15:30:01+08:00'
        with self.assertRaises(ValueError):
            job.build_rotation_block(rotation_batches(self.config), [], self.config)

    def test_shadow_isolates_state_and_health_never_calls_production_publisher(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            production = root/'market-dashboard/last-success.json'
            production.parent.mkdir(); production.write_text('{"mode":"published","private":"v2"}')
            health = root/'service-health/market-dashboard.json'
            health.parent.mkdir(); health.write_text('{"lastPublishStatus":"published"}')
            before = production.read_bytes(), health.read_bytes()
            result = job.run_job({'rotation_shadow': True}, {'now': self.now, 'state_root': root,
                'collector': rotation_batches, 'publisher': lambda *a, **k: self.fail('shadow published')})
            self.assertTrue(result.success, result.error_code)
            self.assertEqual(result.status, 'rotation_shadow')
            self.assertEqual((production.read_bytes(), health.read_bytes()), before)
            shadow = root/'market-dashboard-shadow/last-success.json'
            value = json.loads(shadow.read_text())
            self.assertEqual(value['payload']['schemaVersion'], 'market-dashboard-v3')
            self.assertEqual(value['rotation']['closes'], [])
            self.assertEqual(shadow.stat().st_mode & 0o777, 0o600)
            self.assertEqual(shadow.parent.stat().st_mode & 0o777, 0o700)
            self.assertTrue((shadow.parent/'health.json').exists())
            duplicate = job.run_job({'rotation_shadow': True}, {'now': self.now, 'state_root': root,
                'collector': lambda c: self.fail('duplicate collected')})
            self.assertEqual(duplicate.status, 'duplicate')

    def test_close_requires_every_sector_timestamp_and_does_not_advance_twice(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            now = self.now.replace(hour=15, minute=5)
            def premature(config):
                batches = rotation_batches(config)
                batches['concepts'].rows[-1]['_timestamp'] = '2026-11-13T14:59:59+08:00'
                return batches
            deps = {'now': now, 'state_root': root, 'collector': premature}
            bad = job.run_job({'rotation_shadow': True}, deps)
            self.assertFalse(bad.success)
            self.assertFalse((root/'market-dashboard-shadow/last-success.json').exists())
            good = job.run_job({'rotation_shadow': True}, deps | {'collector': rotation_batches})
            self.assertTrue(good.success, good.error_code)
            state = root/'market-dashboard-shadow/last-success.json'
            saved = state.read_bytes()
            value = json.loads(saved)
            self.assertEqual(len(value['rotation']['closes']), 110)
            self.assertTrue(all(row['officialClose'] for row in value['rotation']['closes']))
            self.assertTrue(value['payload']['sectorRotation'].get('officialClose'))
            published_rows = value['payload']['sectorRotation']['industries']
            for row in published_rows:
                self.assertEqual(row['leaderboard']['strength']['topTenCount15d'],
                                 int(row['ranks']['strength'] <= 10))
            industry = next(row for row in value['rotation']['closes'] if row['id'] == '882100.WI')
            self.assertNotEqual(industry['_rawScores']['strength'], industry['strength'])
            again = job.run_job({'rotation_shadow': True, 'force': True}, deps | {
                'now': now.replace(minute=25), 'collector': lambda c: self.fail('duplicate close collected')})
            self.assertEqual(again.status, 'duplicate')
            self.assertEqual(state.read_bytes(), saved)
            late = job.run_job({'rotation_shadow': True, 'force': True}, deps | {
                'now': now.replace(day=16, minute=31), 'collector': lambda c: self.fail('late collected')})
            self.assertEqual(late.status, 'outside_schedule')

    def test_local_audit_preserves_all_missing_reasons_without_repeated_text(self):
        block = job.build_rotation_block(rotation_batches(self.config), [], self.config)
        self.assertIsInstance(block.get('missingReasons'), list)
        first = next(row for row in block['industries'] if row['id'] == '882100.WI')
        self.assertTrue(first['missing'])
        self.assertTrue(all(isinstance(index, int) for index in first['missing']))
        expanded = [block['missingReasons'][index] for index in first['missing']]
        self.assertIn('funding.flow5d.missingInput', expanded)
        self.assertIn('position.position250d.insufficientPositionHistory', expanded)
        self.assertEqual(decode_rotation_components(block, first)['funding']['coverage'], .3)
        self.assertIs(block.get('officialClose'), False)

    def test_health_or_success_write_failure_cannot_consume_official_close(self):
        for failed_name in ('health.json', 'last-success.json'):
            with self.subTest(failed_name=failed_name), TemporaryDirectory() as directory:
                root = Path(directory)
                production = root/'market-dashboard/last-success.json'
                production.parent.mkdir(); production.write_text('{"mode":"published"}')
                health = root/'service-health/market-dashboard.json'
                health.parent.mkdir(); health.write_text('{"lastPublishStatus":"published"}')
                before = production.read_bytes(), health.read_bytes()
                deps = {'now': self.now.replace(hour=15, minute=5), 'state_root': root,
                        'collector': rotation_batches}
                write = job._write_json
                def fail_write(path, value, **kwargs):
                    if path.name == failed_name:
                        raise OSError('synthetic persistence failure')
                    return write(path, value, **kwargs)
                with patch.object(job, '_write_json', side_effect=fail_write):
                    failed = job.run_job({'rotation_shadow': True}, deps)
                self.assertEqual(failed.error_code, 'STATE_WRITE_FAILED')
                path = root/'market-dashboard-shadow/last-success.json'
                self.assertFalse(path.exists(), 'failed run consumed the close')
                self.assertEqual((production.read_bytes(), health.read_bytes()), before)
                retry = job.run_job({'rotation_shadow': True}, deps)
                self.assertEqual(retry.status, 'rotation_shadow')
                self.assertEqual(len(json.loads(path.read_text())['rotation']['closes']), 110)

    def test_directory_sync_error_after_close_replace_does_not_report_failed_close(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root/'market-dashboard-shadow/last-success.json'
            fsync = job.os.fsync
            def fail_after_replace(fd):
                if path.exists():
                    raise OSError('synthetic post-replace directory sync failure')
                return fsync(fd)
            deps = {'now': self.now.replace(hour=15, minute=5), 'state_root': root,
                    'collector': rotation_batches}
            with patch.object(job.os, 'fsync', side_effect=fail_after_replace):
                result = job.run_job({'rotation_shadow': True}, deps)
            self.assertTrue(path.exists())
            self.assertTrue(result.success, 'installed close must be acknowledged as success')
            self.assertEqual(result.status, 'rotation_shadow')
            self.assertIn('STATE_DURABILITY_UNCONFIRMED', result.metadata['safeCodes'])
            with patch.object(job, 'run_job', return_value=result), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(job.main(['--rotation-shadow']), 0)
            self.assertIn('STATE_DURABILITY_UNCONFIRMED', json.loads(output.getvalue()).get('safeCodes', []))

    def test_compact_audit_decodes_full_private_components_for_both_universes_and_sessions(self):
        from tools.market_dashboard.tests.test_rotation import history
        for hour, minute in ((9, 50), (15, 5)):
            with self.subTest(hour=hour):
                config = deepcopy(self.config)
                now = self.now.replace(hour=hour, minute=minute)
                config['sources']['now'] = now.isoformat()
                batches = rotation_batches(config)
                # Known units give both universes real normalized price/breadth
                # leaves; the dated derived history exercises 60/250 percentiles.
                for group in ('industries', 'concepts'):
                    for index, row in enumerate(batches[group].rows):
                        fields = {'最新涨跌幅(%)' if group == 'industries' else '涨跌幅': index/10,
                            '5日涨跌幅': index/5, '20日涨跌幅': index/2,
                            '最新换手率(%)' if group == 'industries' else '换手率': index+1}
                        row.update(fields)
                        row['_units'].update({key: '%' for key in fields})
                        for key, value in [('上涨家数', index+1), ('下跌家数', 100-index), ('平盘家数', 1)]:
                            row[key] = value; row['_units'][key] = '个'
                current = job._rotation_inputs(batches, config)
                prior = history(250, current)
                # Add explicit official-close rank evidence for leaderboard stats.
                for point in prior:
                    point.update(officialClose=True, ranks={'strength': 1, 'opportunity': None, 'risk': 2})
                block = job.build_rotation_block(batches, prior, config)
                for universe, group in (('industry', 'industries'), ('concept', 'concepts')):
                    target = next(row for row in current if row['universe'] == universe)
                    expected = job.score_sector(target, prior, current, config)['components']
                    actual = next(row for row in block[group] if row['id'] == target['id'])
                    decoded = decode_rotation_components(block, actual)
                    self.assertEqual(decoded, expected)
                    self.assertIsNotNone(decoded['position']['parts']['position250d']['percentile'])
                    self.assertIn('effectiveWeight', decoded['funding'])
                payload = job.build_rotation_payload(job.derive_inputs(batches, now, config), [], block, config)
                self.assertLessEqual(len(json.dumps(payload, ensure_ascii=False,
                    allow_nan=False, separators=(',', ':')).encode()), 256*1024)

    def test_collection_failure_keeps_shadow_close_and_redacts_errors(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            deps = {'now': self.now, 'state_root': root, 'collector': rotation_batches}
            self.assertTrue(job.run_job({'rotation_shadow': True}, deps).success)
            path = root/'market-dashboard-shadow/last-success.json'
            saved = path.read_bytes()
            def broken(config):
                raise RuntimeError('private-token upstream response /private/local/path')
            result = job.run_job({'rotation_shadow': True}, deps | {
                'now': self.now.replace(hour=11, minute=35), 'collector': broken})
            self.assertEqual(result.error_code, 'COLLECTION_FAILED')
            self.assertEqual(path.read_bytes(), saved)
            health = (path.parent/'health.json').read_text()
            self.assertNotIn('private-token', health)
            self.assertNotIn('/private/local', health)

    def test_live_shadow_respects_shared_provider_lock(self):
        import fcntl
        with TemporaryDirectory() as directory:
            root = Path(directory)
            lock_path = root/'market-dashboard/job.lock'
            lock_path.parent.mkdir()
            with lock_path.open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = job.run_job({'rotation_shadow': True}, {'now': self.now, 'state_root': root,
                    'collector': lambda c: self.fail('lock ignored')})
            self.assertEqual(result.status, 'locked')
            self.assertFalse((root/'market-dashboard-shadow').exists())

    def test_fixture_cli_scores_shadow_at_fixed_key_window_without_writing(self):
        with TemporaryDirectory() as directory, patch.dict(job.os.environ,
                {'MARKET_DASHBOARD_STATE_ROOT': directory}), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(job.main(['--rotation-shadow', '--fixture', '--dry-run']), 0)
            self.assertEqual(json.loads(output.getvalue())['status'], 'dry_run')
            self.assertEqual(list(Path(directory).rglob('*')), [])

    def test_report_is_read_only_metadata_and_skip_flag_cannot_publish(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            args = {'skip_rotation_publish': True}
            result = job.run_job(args, {'now': self.now, 'state_root': root,
                'collector': rotation_batches, 'publisher': lambda *a, **k: self.fail('skip published')})
            self.assertEqual(result.status, 'rotation_shadow')
            before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with patch.dict(job.os.environ, {'MARKET_DASHBOARD_STATE_ROOT': directory}), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(job.main(['--rotation-report']), 0)
            summary = json.loads(output.getvalue())
            self.assertEqual(set(summary), {'counts', 'versions', 'coverage', 'latencySeconds', 'safeCodes',
                'rotationMode', 'rotationSession', 'rotationCoverage', 'rotationUniverseCounts',
                'rotationLatencySeconds', 'rotationCloseSuccesses', 'rotationSafeErrorCode',
                'rotationObservedAt', 'rotationSourceAt'})
            self.assertEqual(summary['counts']['industries'], 35)
            self.assertEqual(summary['counts']['concepts'], 75)
            self.assertNotIn('882100', output.getvalue())
            self.assertNotIn(directory, output.getvalue())
            self.assertEqual(before, {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_fixture_shadow_requires_dry_run_and_never_writes_state(self):
        with TemporaryDirectory() as directory:
            deps = {'now': self.now, 'state_root': Path(directory)}
            result = job.run_job({'rotation_shadow': True, 'fixture': True}, deps)
            self.assertEqual(result.error_code, 'FIXTURE_SHADOW_WRITE_DISABLED')
            result = job.run_job({'rotation_shadow': True, 'fixture': True, 'dry_run': True}, deps)
            self.assertTrue(result.success, result.error_code)
            self.assertEqual(list(Path(directory).rglob('*')), [])


class CloseFreshnessTests(unittest.TestCase):
    def test_final_close_remains_fresh_during_afternoon_and_evening(self):
        row = {'_timestamp': '2026-11-13T15:00:03+08:00'}
        for clock in ('2026-11-13T15:30:04+08:00', '2026-11-13T17:45:00+08:00',
                      '2026-11-13T23:59:59+08:00', '2026-11-13T15:59:59Z'):
            with self.subTest(clock=clock):
                self.assertTrue(job._fresh(row, datetime.fromisoformat(clock)))

    def test_final_close_expires_at_next_shanghai_date_and_rejects_future(self):
        row = {'_timestamp': '2026-11-13T15:00:03+08:00'}
        for clock in ('2026-11-14T00:00:00+08:00', '2026-11-13T16:00:00Z',
                      '2026-11-13T15:00:02+08:00'):
            with self.subTest(clock=clock):
                self.assertFalse(job._fresh(row, datetime.fromisoformat(clock)))

    def test_close_does_not_promote_preclose_or_previous_day_quotes(self):
        now = datetime.fromisoformat('2026-11-13T16:00:00+08:00')
        for clock in ('2026-11-13T14:59:59+08:00', '2026-11-12T15:00:03+08:00'):
            with self.subTest(clock=clock):
                self.assertFalse(job._fresh({'_timestamp': clock}, now))
        intraday = datetime.fromisoformat('2026-11-13T14:59:00+08:00')
        self.assertTrue(job._fresh({'_timestamp': '2026-11-13T14:29:00+08:00'}, intraday))
        self.assertFalse(job._fresh({'_timestamp': '2026-11-13T14:28:59+08:00'}, intraday))


if __name__ == '__main__':
    unittest.main()
