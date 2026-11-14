"""Metadata probe tests use synthetic data, never live provider rows."""
import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from unittest.mock import patch

from tools.market_dashboard import sources


def history_envelope(rows=None):
    return {'data': {'columns': ['Wind代码', '日期', '开盘价', '最高价', '最低价', '收盘价'],
                     'rows': rows if rows is not None else [
                         ['882100.WI', '2026-11-12', 10, 12, 9, 11],
                         ['882100.WI', '2026-11-13', 11, 13, 10, 12]]}}


class HistoryTests(unittest.TestCase):
    def adapter(self):
        adapter = getattr(sources, 'collect_index_history', None)
        self.assertTrue(callable(adapter), 'daily history adapter is missing')
        return adapter

    def test_single_verified_identity_and_explicit_daily_dates(self):
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            return history_envelope()
        output = io.StringIO()
        with redirect_stdout(output):
            rows = self.adapter()(runner, '882100.WI', '2026-11-12', '2026-11-13')
        self.assertEqual(calls[0][2:5], ['call', 'index_data', 'get_index_kline'])
        self.assertEqual(json.loads(calls[0][-1]), {'windcode': '882100.WI',
                         'begin_date': '2026-11-12', 'end_date': '2026-11-13', 'period': '1d'})
        self.assertEqual([(r['date'], r['close']) for r in rows], [('2026-11-12', 11), ('2026-11-13', 12)])
        self.assertEqual(output.getvalue(), '')

    def test_invalid_requests_never_call_provider(self):
        def runner(*a, **k):
            self.fail('invalid request reached provider')
        cases = [('882100.WI,882101.WI', '2026-11-12', '2026-11-13', '1d'),
                 ('999999.WI', '2026-11-12', '2026-11-13', '1d'),
                 ('882100.WI', '2026-2-01', '2026-11-13', '1d'),
                 ('882100.WI', '2026-11-13', '2026-11-12', '1d'),
                 ('882100.WI', '2026-11-12', '2999-11-13', '1d'),
                 ('882100.WI', '2026-11-12', '2026-11-13', '1w')]
        adapter = self.adapter()
        for args in cases:
            with self.subTest(args=args), self.assertRaises(sources.SourceError):
                adapter(runner, *args)

    def test_history_rejects_wrong_identity_duplicates_dates_and_nonfinite_ohlc(self):
        adapter = self.adapter()
        for column, value in [(0, '882101.WI'), (1, '2026-11-31'), (1, '2026-11-12'),
                              (1, '2999-01-01'), (1, '2026-11-14'), (2, float('inf')),
                              (3, None), (4, 'nan'), (5, '.')]:
            response = history_envelope()
            response['data']['rows'][1][column] = value
            with self.subTest(column=column, value=value), self.assertRaises(sources.SourceError):
                adapter(lambda *a, **k: response, '882100.WI', '2026-11-12', '2026-11-13')

    def test_provider_errors_are_safe_and_never_printed(self):
        adapter = self.adapter()
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(sources.SourceError) as caught:
            adapter(lambda *a, **k: {'ok': False, 'code': 'AUTH_ERROR', 'message': 'private-marker'},
                    '882100.WI', '2026-11-12', '2026-11-13')
        self.assertEqual(str(caught.exception), 'AUTH_ERROR')
        self.assertNotIn('private-marker', output.getvalue())


class ProbeTests(unittest.TestCase):
    @staticmethod
    def successful_runner(argv, **kwargs):
        params = json.loads(argv[-1])
        if argv[4] == 'get_index_kline':
            response = history_envelope()
            for row in response['data']['rows']:
                row[0] = params['windcode']
            return response
        fields = params['indexes'].split(',')
        values = {'最新交易日': '2026-11-13', '交易时间': '15:00:00', '中文简称': 'synthetic'}
        return {'data': {'columns': ['Wind代码', *fields], 'unit': sources.CONCEPT_UNITS,
                         'rows': [[code, *(values.get(field, 1234567) for field in fields)]
                                  for code in params['windcode'].split(',')]}}

    def probe(self):
        from importlib.util import find_spec
        self.assertIsNotNone(find_spec('tools.market_dashboard.rotation_probe'), 'metadata probe is missing')
        from tools.market_dashboard import rotation_probe
        return rotation_probe

    def test_summary_distinguishes_price_closes_from_current_rolling_flow(self):
        probe = self.probe()
        fields = ['涨跌幅', '5日涨跌幅', '20日涨跌幅', '成交额', '换手率',
                  '当日主力净流入额', '近5日主力净流入额', '近20日主力净流入额',
                  '上涨家数', '下跌家数', '平盘家数']
        row = {key: 1234567 for key in fields}
        row.update(id='882100.WI', _timestamp='2026-11-13T15:00:00+08:00', _units={'成交额': '元'})
        histories = {'882100.WI': [{'date': '2026-11-13', 'close': 9876543}]}
        summary = probe.summarize_rotation_capability(
            {'industries': sources.SourceBatch('Wind', [row], complete=True)}, histories,
            datetime(2026, 11, 14, tzinfo=timezone.utc))
        self.assertEqual(summary['groups']['industries']['fieldCoverage']['近20日主力净流入额'], 1)
        self.assertEqual(summary['history']['price']['closesAtLeast']['20'], 0)
        self.assertEqual(summary['history']['flow']['status'], 'unavailable')
        self.assertEqual(summary['history']['breadth']['status'], 'unavailable')
        self.assertEqual(summary['history']['price']['earliestDate'], '2026-11-13')
        self.assertNotIn('1234567', json.dumps(summary))
        self.assertNotIn('9876543', json.dumps(summary))

    def test_sample_stops_after_first_safe_error_and_emits_metadata_only(self):
        probe = self.probe()
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            return {'ok': False, 'code': 'TOOL_RUNTIME_ERROR', 'message': 'private-marker'}
        output = io.StringIO()
        with redirect_stdout(output):
            status = probe.main(['--scope', 'sample', '--metadata-only'], runner=runner)
        result = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(json.loads(calls[0][-1])['windcode'].split(',')), 6)
        self.assertEqual(result['status'], 'BLOCKED_RUNTIME')
        self.assertEqual(result['safeErrorCodes'], ['TOOL_RUNTIME_ERROR'])
        self.assertNotIn('private-marker', output.getvalue())

    def test_sample_success_uses_twelve_serial_histories_and_records_window_and_counts(self):
        probe = self.probe()
        calls, output = [], io.StringIO()
        def runner(argv, **kwargs):
            calls.append(argv)
            return self.successful_runner(argv, **kwargs)
        with patch('pathlib.Path.write_text', side_effect=AssertionError('probe wrote a file')):
            with redirect_stdout(output):
                code = probe.main(['--scope', 'sample', '--metadata-only'], runner=runner)
        result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 14)
        self.assertEqual([call[4] for call in calls[:2]], ['get_index_price_indicators'] * 2)
        self.assertEqual(len({json.loads(call[-1])['windcode'] for call in calls[2:]}), 12)
        self.assertTrue(all(json.loads(call[-1])['period'] == '1d' for call in calls[2:]))
        self.assertEqual(result['history']['price']['identityCount'], 12)
        self.assertEqual(result['history']['price'].get('minimumCloses'), 2)
        self.assertEqual(result['history']['price'].get('maximumCloses'), 2)
        self.assertEqual(result.get('historicalSampleAttempted'), True)
        self.assertEqual(result.get('requestedIdentityCounts'), {'industries': 6, 'concepts': 6})
        self.assertEqual(len(result['requestDurationsSeconds']), 14)
        self.assertNotIn('1234567', output.getvalue())

    def test_full_checks_all_current_identities_with_three_requests_and_no_history(self):
        probe = self.probe()
        calls, output = [], io.StringIO()
        def runner(argv, **kwargs):
            calls.append(argv)
            return self.successful_runner(argv, **kwargs)
        with redirect_stdout(output):
            code = probe.main(['--scope', 'full', '--metadata-only'], runner=runner)
        result = json.loads(output.getvalue().splitlines()[-1])
        self.assertEqual(code, 0)
        self.assertEqual([len(json.loads(call[-1])['windcode'].split(',')) for call in calls], [35, 50, 25])
        self.assertEqual(result['groups']['concepts']['identityCount'], 75)
        self.assertEqual(len(result['requestDurationsSeconds']), 3)
        self.assertFalse(result['historicalSampleAttempted'])

    def test_first_history_error_stops_remaining_history_without_losing_safe_code(self):
        probe = self.probe()
        calls, output = [], io.StringIO()
        def runner(argv, **kwargs):
            calls.append(argv)
            if argv[4] == 'get_index_kline':
                return {'ok': False, 'code': 'RATE_LIMIT_ERROR', 'message': 'private-marker'}
            return self.successful_runner(argv, **kwargs)
        with redirect_stdout(output):
            code = probe.main(['--scope', 'sample', '--metadata-only'], runner=runner)
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 3)
        self.assertEqual(json.loads(output.getvalue())['status'], 'BLOCKED_QUOTA')
        self.assertNotIn('private-marker', output.getvalue())

    def test_full_estimates_cost_before_any_requests_without_backfilling(self):
        probe = self.probe()
        output = io.StringIO()
        observed = []
        def runner(*a, **k):
            observed.append(json.loads(output.getvalue().splitlines()[0]))
            return {'ok': False, 'code': 'RATE_LIMIT_ERROR'}
        with redirect_stdout(output):
            probe.main(['--scope', 'full', '--metadata-only'], runner=runner)
        self.assertEqual(observed[0]['historicalCallsEstimated'], 110)
        self.assertEqual(observed[0]['currentCallsEstimated'], 3)
        self.assertEqual(observed[0]['historicalBackfillAttempted'], False)
