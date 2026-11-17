"""Offline contract tests: injected runner is the only external boundary."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
import math
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from tools.market_dashboard import hithink_cli as api


FIXTURES = Path(__file__).parents[1] / 'fixtures' / 'hithink' / 'responses.json'
CLI = Path('/opt/hithink/bin/hithink-finance')
MONDAY = 1794758400000


class Runner:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return subprocess.CompletedProcess(argv, 0, json.dumps(response), '')


class HithinkClientTests(unittest.TestCase):
    def setUp(self):
        self.fixtures = json.loads(FIXTURES.read_text())

    def invoke(self, kind, response):
        runner = Runner(response)
        client = api.HithinkClient(CLI, runner=runner)
        calls = {
            'catalog': lambda: client.catalog('industry'),
            'constituents': lambda: client.constituents('881121.TI'),
            'history': lambda: client.index_history('881121.TI', MONDAY, MONDAY),
            'index': lambda: client.index_snapshots(['881121.TI']),
            'stock': lambda: client.stock_snapshots(['000001.SZ']),
        }
        return calls[kind](), runner

    def test_exact_envelopes_normalize_to_frozen_models(self):
        expected = {
            'catalog': api.SectorDefinition('881121.TI', '测试行业', 'industry'),
            'constituents': api.Membership('881121.TI', '000001.SZ', MONDAY),
            'history': api.IndexDailyBar('881121.TI', '2026-11-16', 10., 12., 9., 11., 100., 1100.),
            'index': api.IndexSnapshot('881121.TI', MONDAY, 11., 1., 10., 10., 12., 9., 10., 100., 1100.),
            'stock': api.StockSnapshot('000001.SZ', MONDAY, 11., 1., 10., 10., 12., 9., 10., 100., 1100.),
        }
        for kind, want in expected.items():
            with self.subTest(kind=kind):
                rows, runner = self.invoke(kind, self.fixtures[kind])
                self.assertEqual(rows, (want,))
                with self.assertRaises(FrozenInstanceError):
                    rows[0].code = 'changed'
                self.assertEqual(runner.calls[0][0], str(CLI))
                self.assertEqual(runner.calls[0][-2:], ['--format', 'json'])

    def test_neeq_member_retained_but_not_allowed_as_a_share_snapshot(self):
        response = deepcopy(self.fixtures['constituents'])
        response['data']['item'][0]['thscode'] = '830001.NQ'
        response['data']['item'][0]['ticker'] = '830001'
        rows, _ = self.invoke('constituents', response)
        self.assertEqual(rows[0].stock_code, '830001.NQ')
        client = api.HithinkClient(CLI, runner=Runner())
        with self.assertRaises(api.HithinkError):
            client.stock_snapshots(['830001.NQ'])

    def test_installed_cli_camelcase_metadata_acceptance_and_collision_rejection(self):
        response = deepcopy(self.fixtures['catalog'])
        response['meta']['schemaVersion'] = response['meta'].pop('schema_version')
        response['meta']['requestId'] = response['meta'].pop('request_id', 'private-request')
        rows, _ = self.invoke('catalog', response)
        self.assertEqual(len(rows), 1)
        response['meta']['schema_version'] = '1'
        with self.assertRaises(api.HithinkError):
            self.invoke('catalog', response)

    def test_unknown_and_missing_fields_fail_at_every_schema_level(self):
        for kind, original in self.fixtures.items():
            if kind == 'batch':
                continue
            for level in ('root', 'meta', 'data', 'row'):
                for mutation in ('extra', 'missing'):
                    response = deepcopy(original)
                    target = {'root': response, 'meta': response['meta'],
                              'data': response['data'], 'row': response['data']['item'][0]}[level]
                    if mutation == 'extra':
                        target['unexpected'] = 'private payload'
                    else:
                        target.pop(next(iter(target)))
                    with self.subTest(kind=kind, level=level, mutation=mutation):
                        with self.assertRaises(api.HithinkError) as raised:
                            self.invoke(kind, response)
                        self.assertEqual(str(raised.exception), 'INVALID_HITHINK_RESPONSE')

    def test_duplicate_identities_and_history_days_fail_closed(self):
        for kind in ('catalog', 'constituents', 'history', 'index', 'stock'):
            response = deepcopy(self.fixtures[kind])
            response['data']['item'] *= 2
            response['meta']['count'] = 2
            if 'total' in response['data']:
                response['data']['total'] = 2
            with self.subTest(kind=kind), self.assertRaises(api.HithinkError):
                self.invoke(kind, response)

    def test_numbers_must_be_finite_real_values(self):
        for kind in ('history', 'index', 'stock'):
            for field, original in self.fixtures[kind]['data']['item'][0].items():
                if not isinstance(original, (int, float)):
                    continue
                for invalid in (math.nan, math.inf, -math.inf, True, '11') + (() if kind == 'stock' else (None,)):
                    response = deepcopy(self.fixtures[kind])
                    response['data']['item'][0][field] = invalid
                    with self.subTest(kind=kind, field=field, value=invalid), self.assertRaises(api.HithinkError):
                        self.invoke(kind, response)

    def test_null_stock_quote_is_explicitly_unavailable_not_zero(self):
        response = deepcopy(self.fixtures['stock'])
        for key in ('last_price', 'price_change', 'price_change_ratio_pct', 'open_price', 'high_price', 'low_price'):
            response['data']['item'][0][key] = None
        rows, _ = self.invoke('stock', response)
        self.assertIsInstance(rows[0], api.UnavailableStockSnapshot)
        self.assertEqual(rows[0].code, '000001.SZ')
        self.assertIn('last_price', rows[0].missing_fields)
        response['data']['item'][0]['volume'] = 'bad'
        with self.assertRaises(api.HithinkError):
            self.invoke('stock', response)

    def test_metadata_and_incomplete_snapshots_fail_closed(self):
        for mutation in (
            lambda r: r.update(ok=False),
            lambda r: r.update(command='market.snapshot'),
            lambda r: r['meta'].update(truncated=True),
            lambda r: r['meta'].update(count=2),
            lambda r: r['meta'].update(count=True),
            lambda r: r['meta'].update(schema_version='2'),
            lambda r: r['data'].update(total=100),
            lambda r: r['data']['item'][0].update(thscode='881122.TI'),
        ):
            response = deepcopy(self.fixtures['index'])
            mutation(response)
            with self.assertRaises(api.HithinkError):
                self.invoke('index', response)

    def test_shanghai_monday_midnight_is_monday(self):
        self.assertEqual(api.shanghai_market_date(MONDAY), '2026-11-16')
        for invalid in (True, '1794758400000', None, math.inf, 10**100):
            with self.subTest(value=invalid), self.assertRaises(api.HithinkError):
                api.shanghai_market_date(invalid)

    def test_history_rejects_out_of_window_or_wrong_identity(self):
        for mutation in (
            lambda r: r['data'].update(thscode='881122.TI'),
            lambda r: r['data'].update(interval='1m'),
            lambda r: r['data'].update(adjust='qfq'),
            lambda r: r['data']['item'][0].update(date_ms=MONDAY - 86400000),
            lambda r: r['data']['item'][0].update(close_price=0),
        ):
            response = deepcopy(self.fixtures['history'])
            mutation(response)
            with self.assertRaises(api.HithinkError):
                self.invoke('history', response)

    def test_invalid_requests_do_not_call_runner(self):
        runner = Runner()
        client = api.HithinkClient(CLI, runner=runner)
        for operation in (
            lambda: client.catalog('unknown'),
            lambda: client.constituents('881121.TI;secret'),
            lambda: client.index_history('881121.TI', MONDAY, MONDAY-1),
            lambda: client.index_history('881121.TI', True, MONDAY),
            lambda: client.index_snapshots(['881121.TI', '881121.TI']),
            lambda: client.stock_snapshots(['881121.TI']),
            lambda: client.index_snapshots([]),
        ):
            with self.assertRaises(api.HithinkError) as raised:
                operation()
            self.assertEqual(raised.exception.code, 'INVALID_HITHINK_REQUEST')
        self.assertEqual(runner.calls, [])

    def test_provider_errors_are_safe(self):
        for response in (OSError('secret'), TimeoutError('secret')):
            client = api.HithinkClient(CLI, runner=Runner(response))
            with self.assertRaises(api.HithinkError) as raised:
                client.catalog('industry')
            self.assertEqual(str(raised.exception), 'HITHINK_COMMAND_FAILED')
        for result in (subprocess.CompletedProcess([], 1, 'secret', 'secret'),
                       subprocess.CompletedProcess([], 0, 'secret', 'secret')):
            with self.assertRaises(api.HithinkError) as raised:
                api.HithinkClient(CLI, runner=lambda argv: result).catalog('industry')
            self.assertNotIn('secret', str(raised.exception))

    def test_empty_batch_with_single_history_raises_incomplete(self):
        runner = Runner(self.fixtures['batch'], self.fixtures['history'])
        client = api.HithinkClient(CLI, runner=runner)
        with self.assertRaises(api.HithinkError) as raised:
            client.index_history_batch(['881121.TI'], MONDAY, MONDAY)
        self.assertEqual(raised.exception.code, 'HISTORY_BATCH_INCOMPLETE')
        self.assertEqual([call[2] for call in runner.calls], ['history-batch', 'history'])

    def test_nonempty_batch_normalizes_and_empty_agreement_is_allowed(self):
        response = deepcopy(self.fixtures['batch'])
        response['data']['item'][0]['item'] = deepcopy(self.fixtures['history']['data']['item'])
        result = api.HithinkClient(CLI, runner=Runner(response)).index_history_batch(['881121.TI'], MONDAY, MONDAY)
        self.assertEqual(result[0].date, '2026-11-16')
        empty = deepcopy(self.fixtures['history'])
        empty['data']['item'] = []
        empty['meta']['count'] = 0
        result = api.HithinkClient(CLI, runner=Runner(self.fixtures['batch'], empty)).index_history_batch(['881121.TI'], MONDAY, MONDAY)
        self.assertEqual(result, ())

    def test_batch_rejects_duplicate_unknown_or_malformed_groups(self):
        for mutation in (
            lambda r: r['data']['item'].append(deepcopy(r['data']['item'][0])),
            lambda r: r['data']['item'][0].update(thscode='881122.TI'),
            lambda r: r['data']['item'][0].update(unexpected=True),
            lambda r: r['data']['item'][0].pop('timestamp'),
            lambda r: r['data']['item'][0].update(item={}),
        ):
            response = deepcopy(self.fixtures['batch'])
            mutation(response)
            response['meta']['count'] = len(response['data']['item'])
            with self.assertRaises(api.HithinkError) as raised:
                api.HithinkClient(CLI, runner=Runner(response)).index_history_batch(['881121.TI'], MONDAY, MONDAY)
            self.assertEqual(raised.exception.code, 'INVALID_HITHINK_RESPONSE')

    def test_omitted_batch_group_is_not_silently_no_history(self):
        response = deepcopy(self.fixtures['batch'])
        response['data']['item'] = []
        response['meta']['count'] = 0
        with self.assertRaises(api.HithinkError) as raised:
            api.HithinkClient(CLI, runner=Runner(response, self.fixtures['history'])).index_history_batch(['881121.TI'], MONDAY, MONDAY)
        self.assertEqual(raised.exception.code, 'HISTORY_BATCH_INCOMPLETE')

    def test_timestamp_and_ticker_types_are_validated(self):
        for mutation in (
            lambda r: r['data'].update(timestamp=True),
            lambda r: r['data'].update(timestamp=10**400),
            lambda r: r['data']['item'][0].update(ticker='000002'),
            lambda r: r['data']['item'][0].update(last_price=10**400),
        ):
            response = deepcopy(self.fixtures['stock'])
            mutation(response)
            with self.assertRaises(api.HithinkError):
                self.invoke('stock', response)

    def test_duplicate_json_keys_fail_closed(self):
        payload = json.dumps(self.fixtures['catalog']).replace('"ok": true', '"ok": false, "ok": true')
        with self.assertRaises(api.HithinkError) as raised:
            api.HithinkClient(CLI, runner=lambda argv: subprocess.CompletedProcess(argv, 0, payload, '')).catalog('industry')
        self.assertEqual(str(raised.exception), 'INVALID_HITHINK_RESPONSE')

    def test_default_runner_uses_no_shell(self):
        with patch.object(api.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(self.fixtures['catalog']), '')) as run:
            result = api.HithinkClient(CLI).catalog('industry')
        self.assertEqual(result[0].name, '测试行业')
        self.assertEqual(run.call_args.args[0], [str(CLI), 'index', 'catalog', '--tag', 'industry', '--format', 'json'])
        self.assertFalse(run.call_args.kwargs.get('shell', False))

    def test_default_runner_decoding_failure_returns_only_safe_error(self):
        for stream in ('stdout', 'stderr'):
            error = UnicodeDecodeError('utf-8', b'private-\xff', 8, 9, f'private {stream}')
            with self.subTest(stream=stream), patch.object(api.subprocess, 'run', side_effect=error):
                with self.assertRaises(api.HithinkError) as raised:
                    api.HithinkClient(CLI).catalog('industry')
                self.assertEqual(raised.exception.code, 'HITHINK_COMMAND_FAILED')
                self.assertEqual(str(raised.exception), 'HITHINK_COMMAND_FAILED')
                self.assertTrue(raised.exception.__suppress_context__)
                self.assertIsNone(raised.exception.__cause__)
