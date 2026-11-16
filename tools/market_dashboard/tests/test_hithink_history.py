import json
import math
from pathlib import Path
import subprocess
from contextlib import redirect_stdout
import io
import unittest
from unittest.mock import patch

from tools.market_dashboard import hithink_history


CLI = Path('/opt/hithink/bin/hithink-finance')
DB = Path('/data/hithink/market.duckdb')


def envelope(rows, *, count=None, truncated=False, command='db.query', ok=True):
    return {
        'ok': ok,
        'command': command,
        'data': rows,
        'meta': {
            'request_id': 'test-request',
            'count': len(rows) if count is None else count,
            'truncated': truncated,
            'schema_version': '1',
        },
    }


class SequenceRunner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        return self.responses.pop(0)


class HithinkHistoryAdapterTests(unittest.TestCase):
    def test_two_page_query_is_allowlisted_minimized_and_stably_sorted(self):
        runner = SequenceRunner([
            envelope([
                {'thscode': '000001.SZ', 'date': '2026-11-10', 'close': 11.86},
                {'thscode': '600519.SH', 'date': '2026-11-10', 'close': 1439},
            ]),
            envelope([
                {'thscode': '000001.SZ', 'date': '2026-11-11', 'close': 11.71},
            ]),
        ])

        batch = hithink_history.load_daily_closes(
            runner, CLI, DB, ['600519.SH', '000001.SZ'],
            '2026-11-10', '2026-11-13', adjustment='qfq', page_size=2)

        self.assertEqual(batch, {
            'schemaVersion': 'hithink-daily-history-v1',
            'source': 'Hithink',
            'adjustment': 'qfq',
            'startDate': '2026-11-10',
            'endDate': '2026-11-13',
            'requestedSymbols': ['000001.SZ', '600519.SH'],
            'returnedSymbols': ['000001.SZ', '600519.SH'],
            'missingSymbols': [],
            'complete': True,
            'pages': 2,
            'rows': [
                {'id': '000001.SZ', 'date': '2026-11-10', 'close': 11.86,
                 'adjustment': 'qfq', 'source': 'Hithink'},
                {'id': '600519.SH', 'date': '2026-11-10', 'close': 1439.0,
                 'adjustment': 'qfq', 'source': 'Hithink'},
                {'id': '000001.SZ', 'date': '2026-11-11', 'close': 11.71,
                 'adjustment': 'qfq', 'source': 'Hithink'},
            ],
        })
        first_sql = runner.calls[0][-1]
        second_sql = runner.calls[1][-1]
        self.assertEqual(runner.calls[0][:-1], [
            str(CLI), '--db', str(DB), 'db', 'query', '--sql'])
        self.assertEqual(first_sql,
            "select thscode, date, close from v_daily_qfq "
            "where thscode in ('000001.SZ','600519.SH') "
            "and date between '2026-11-10' and '2026-11-13' "
            "order by date, thscode limit 2 offset 0")
        self.assertTrue(second_sql.endswith('limit 2 offset 2'))

    def test_each_adjustment_selects_only_its_fixed_view(self):
        expected = {'none': 'v_daily', 'qfq': 'v_daily_qfq', 'hfq': 'v_daily_hfq'}
        for adjustment, view in expected.items():
            with self.subTest(adjustment=adjustment):
                runner = SequenceRunner([envelope([])])
                batch = hithink_history.load_daily_closes(
                    runner, CLI, DB, ['600519.SH'], '2026-11-10', '2026-11-13',
                    adjustment=adjustment)
                self.assertIn(f'from {view} ', runner.calls[0][-1])
                self.assertEqual(batch['missingSymbols'], ['600519.SH'])
                self.assertFalse(batch['complete'])

    def test_missing_requested_symbol_is_disclosed_without_inventing_rows(self):
        runner = SequenceRunner([envelope([
            {'thscode': '600519.SH', 'date': '2026-11-10', 'close': 1439},
        ])])

        batch = hithink_history.load_daily_closes(
            runner, CLI, DB, ['600519.SH', '000001.SZ'],
            '2026-11-10', '2026-11-13')

        self.assertEqual(batch['returnedSymbols'], ['600519.SH'])
        self.assertEqual(batch['missingSymbols'], ['000001.SZ'])
        self.assertFalse(batch['complete'])

    def test_invalid_input_is_rejected_before_the_runner_is_called(self):
        invalid = [
            (['600519.SH);delete'], '2026-11-10', '2026-11-13', 'qfq', 500, CLI, DB),
            (['600519.SH', '600519.SH'], '2026-11-10', '2026-11-13', 'qfq', 500, CLI, DB),
            (['600519.SH'], '2026-11-1', '2026-11-13', 'qfq', 500, CLI, DB),
            (['600519.SH'], '2026-11-14', '2026-11-13', 'qfq', 500, CLI, DB),
            (['600519.SH'], '2026-11-10', '2026-11-13', 'forward', 500, CLI, DB),
            (['600519.SH'], '2026-11-10', '2026-11-13', 'qfq', 0, CLI, DB),
            (['600519.SH'], '2026-11-10', '2026-11-13', 'qfq', 1001, CLI, DB),
            (['600519.SH'], '2026-11-10', '2026-11-13', 'qfq', 500, Path('cli'), DB),
            (['600519.SH'], '2026-11-10', '2026-11-13', 'qfq', 500, CLI, Path('db')),
        ]
        for symbols, start, end, adjustment, size, cli, db in invalid:
            with self.subTest(symbols=symbols, start=start, adjustment=adjustment, size=size):
                runner = SequenceRunner([])
                with self.assertRaises(hithink_history.HithinkHistoryError) as raised:
                    hithink_history.load_daily_closes(
                        runner, cli, db, symbols, start, end,
                        adjustment=adjustment, page_size=size)
                self.assertEqual(raised.exception.code, 'INVALID_HISTORY_REQUEST')
                self.assertEqual(runner.calls, [])

    def test_malformed_or_unsafe_response_fails_closed(self):
        valid_row = {'thscode': '600519.SH', 'date': '2026-11-10', 'close': 1439}
        cases = [
            envelope([valid_row], truncated=True),
            envelope([valid_row], count=2),
            envelope([valid_row], command='market.history'),
            envelope([valid_row], ok=False),
            {'ok': True, 'command': 'db.query', 'data': {}, 'meta': {}},
            envelope([valid_row | {'thscode': '000001.SZ'}]),
            envelope([valid_row | {'date': '2026-11-09'}]),
            envelope([valid_row | {'close': 0}]),
            envelope([valid_row | {'close': math.inf}]),
            subprocess.CompletedProcess([], 2, json.dumps(envelope([], ok=False)), 'secret'),
        ]
        for response in cases:
            with self.subTest(response=response):
                runner = SequenceRunner([response])
                with self.assertRaises(hithink_history.HithinkHistoryError) as raised:
                    hithink_history.load_daily_closes(
                        runner, CLI, DB, ['600519.SH'], '2026-11-10', '2026-11-13')
                self.assertEqual(raised.exception.code, 'HITHINK_HISTORY_ERROR')

    def test_duplicate_identity_date_across_pages_fails_closed(self):
        row = {'thscode': '600519.SH', 'date': '2026-11-10', 'close': 1439}
        runner = SequenceRunner([envelope([row]), envelope([row])])

        with self.assertRaises(hithink_history.HithinkHistoryError) as raised:
            hithink_history.load_daily_closes(
                runner, CLI, DB, ['600519.SH'], '2026-11-10', '2026-11-13', page_size=1)

        self.assertEqual(raised.exception.code, 'HITHINK_HISTORY_ERROR')


class HithinkHistoryAuditTests(unittest.TestCase):
    def batch(self, symbols=('000001.SZ', '600519.SH')):
        rows = [
            {'thscode': '000001.SZ', 'date': '2026-11-10', 'close': 11.86},
            {'thscode': '600519.SH', 'date': '2026-11-10', 'close': 1439},
            {'thscode': '000001.SZ', 'date': '2026-11-11', 'close': 11.71},
        ]
        selected = [row for row in rows if row['thscode'] in symbols]
        return hithink_history.load_daily_closes(
            SequenceRunner([envelope(selected)]), CLI, DB, list(symbols),
            '2026-11-10', '2026-11-13')

    def test_audit_contains_only_hand_checked_coverage_and_date_bounds(self):
        audit = hithink_history.audit_history(self.batch())

        self.assertEqual(audit, {
            'schemaVersion': 'hithink-history-audit-v1',
            'source': 'Hithink',
            'adjustment': 'qfq',
            'startDate': '2026-11-10',
            'endDate': '2026-11-13',
            'requestedSymbols': 2,
            'returnedSymbols': 2,
            'missingSymbols': [],
            'rowCount': 3,
            'firstDate': '2026-11-10',
            'lastDate': '2026-11-11',
            'pages': 1,
            'complete': True,
        })
        serialized = json.dumps(audit)
        for forbidden in ('rows', 'close', 'request_id', '1439', '11.86'):
            self.assertNotIn(forbidden, serialized)

    def test_cli_missing_symbol_emits_incomplete_audit_and_nonzero_exit(self):
        response = envelope([
            {'thscode': '600519.SH', 'date': '2026-11-10', 'close': 1439},
        ])
        output = io.StringIO()
        argv = ['--cli', str(CLI), '--db', str(DB),
                '--symbols', '600519.SH,000001.SZ',
                '--start', '2026-11-10', '--end', '2026-11-13']

        with patch.object(hithink_history, 'run_command', return_value=response), redirect_stdout(output):
            result = hithink_history.main(argv)

        audit = json.loads(output.getvalue())
        self.assertEqual(result, 1)
        self.assertFalse(audit['complete'])
        self.assertEqual(audit['missingSymbols'], ['000001.SZ'])
        self.assertNotIn('rows', audit)

    def test_cli_complete_batch_emits_audit_and_zero_exit(self):
        response = envelope([
            {'thscode': '000001.SZ', 'date': '2026-11-10', 'close': 11.86},
        ])
        output = io.StringIO()
        argv = ['--cli', str(CLI), '--db', str(DB), '--symbols', '000001.SZ',
                '--start', '2026-11-10', '--end', '2026-11-13', '--adjustment', 'none']

        with patch.object(hithink_history, 'run_command', return_value=response), redirect_stdout(output):
            result = hithink_history.main(argv)

        audit = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertTrue(audit['complete'])
        self.assertEqual(audit['adjustment'], 'none')

    def test_cli_external_failure_returns_only_safe_error(self):
        external = subprocess.CompletedProcess(
            [], 2, '{"provider":"private response"}', 'sensitive database error')
        output = io.StringIO()
        argv = ['--cli', str(CLI), '--db', str(DB), '--symbols', '600519.SH',
                '--start', '2026-11-10', '--end', '2026-11-13']

        with patch.object(hithink_history, 'run_command', return_value=external), redirect_stdout(output):
            result = hithink_history.main(argv)

        self.assertEqual(result, 1)
        self.assertEqual(json.loads(output.getvalue()), {
            'schemaVersion': 'hithink-history-audit-v1',
            'complete': False,
            'safeErrorCode': 'HITHINK_HISTORY_ERROR',
        })
        self.assertNotIn('private response', output.getvalue())
        self.assertNotIn('sensitive', output.getvalue())


if __name__ == '__main__':
    unittest.main()
