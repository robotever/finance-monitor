import json
from pathlib import Path
import tempfile
import unittest


from tools.market_dashboard.sector_mapping import (
    SectorMappingError,
    collect_overlap_audit,
    evaluate_history_alignment,
    evaluate_overlap,
    make_hithink_runner,
    make_wind_runner,
    parse_hithink_constituents,
    parse_wind_constituents,
    run_cli,
)


def wind_envelope(
    codes, *, windcode="884201.WI", date="2026-11-16", extra_count_table=False
):
    columns = [
        {"name": "指数成份代码", "type": "string"},
        {"name": "指数成份简称", "type": "string"},
        {"name": "Wind代码", "type": "string"},
        {"name": "证券简称", "type": "string"},
        {"name": "日期", "type": "date"},
    ]
    rows = [[code, f"证券{index}", windcode, "人工智能指数", date] for index, code in enumerate(codes)]
    tables = [{"columns": columns, "rows": rows}]
    if extra_count_table:
        tables.append(
            {"columns": [{"name": "指数成份数量", "type": "number"}], "rows": [[len(rows)]]}
        )
    payload = {"data": {"data": tables}, "error": None}
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "isError": False,
    }


def hithink_envelope(codes, *, timestamp=1794827519221, truncated=False):
    items = [
        {"thscode": code, "ticker": code.split(".")[0], "name": f"证券{index}"}
        for index, code in enumerate(codes)
    ]
    return {
        "ok": True,
        "command": "index.constituents",
        "data": {"item": items, "timestamp": timestamp},
        "meta": {"count": len(items), "truncated": truncated, "schema_version": "1"},
    }


class SectorMappingTests(unittest.TestCase):
    def setUp(self):
        self.candidate = {
            "wind": {"code": "884201.WI", "name": "人工智能指数"},
            "hithink": {"code": "885728.TI", "name": "人工智能"},
        }

    def test_identical_current_members_passes_price_history_gate(self):
        codes = ["000001.SZ", "000002.SZ", "600000.SH", "688001.SH"]
        wind = parse_wind_constituents(wind_envelope(codes), expected_code="884201.WI")
        hithink = parse_hithink_constituents(
            hithink_envelope(codes), expected_code="885728.TI"
        )

        evidence = evaluate_overlap(self.candidate, wind, hithink)

        self.assertEqual(evidence["schemaVersion"], "sector-overlap-evidence-v1")
        self.assertEqual(evidence["gateVersion"], "sector-overlap-gate-v1")
        self.assertEqual(evidence["status"], "price_history_candidate")
        self.assertEqual(evidence["snapshotDate"], "2026-11-16")
        self.assertEqual(evidence["counts"], {"wind": 4, "hithink": 4, "intersection": 4, "union": 4})
        self.assertEqual(evidence["metrics"], {"jaccard": 1.0, "windCoverage": 1.0, "hithinkCoverage": 1.0})
        self.assertEqual(evidence["differenceSamples"], {"windOnly": [], "hithinkOnly": []})
        self.assertNotIn("members", evidence)

    def test_low_overlap_is_manual_review_with_bounded_samples(self):
        wind = parse_wind_constituents(
            wind_envelope(["000001.SZ", "000002.SZ", "000003.SZ"]),
            expected_code="884201.WI",
        )
        hithink = parse_hithink_constituents(
            hithink_envelope(["000001.SZ", "600000.SH", "600001.SH", "600002.SH"]),
            expected_code="885728.TI",
        )

        evidence = evaluate_overlap(self.candidate, wind, hithink, difference_sample_limit=1)

        self.assertEqual(evidence["status"], "manual_review")
        self.assertEqual(evidence["counts"], {"wind": 3, "hithink": 4, "intersection": 1, "union": 6})
        self.assertEqual(evidence["metrics"], {"jaccard": 0.166667, "windCoverage": 0.333333, "hithinkCoverage": 0.25})
        self.assertEqual(len(evidence["differenceSamples"]["windOnly"]), 1)
        self.assertEqual(len(evidence["differenceSamples"]["hithinkOnly"]), 1)

    def test_parsers_fail_closed_on_duplicate_truncated_and_wrong_target(self):
        with self.subTest("wind duplicate"):
            with self.assertRaises(SectorMappingError):
                parse_wind_constituents(
                    wind_envelope(["000001.SZ", "000001.SZ"]),
                    expected_code="884201.WI",
                )
        with self.subTest("hithink truncated"):
            with self.assertRaises(SectorMappingError):
                parse_hithink_constituents(
                    hithink_envelope(["000001.SZ"], truncated=True),
                    expected_code="885728.TI",
                )
        with self.subTest("wind target mismatch"):
            with self.assertRaises(SectorMappingError):
                parse_wind_constituents(
                    wind_envelope(["000001.SZ"], windcode="884999.WI"),
                    expected_code="884201.WI",
                )

    def test_wind_parser_selects_constituent_table_when_count_summary_is_separate(self):
        snapshot = parse_wind_constituents(
            wind_envelope(
                ["000001.SZ", "000002.SZ"],
                extra_count_table=True,
            ),
            expected_code="884201.WI",
        )

        self.assertEqual(set(snapshot["members"]), {"000001.SZ", "000002.SZ"})

    def test_evaluator_rejects_name_and_snapshot_date_mismatch(self):
        codes = ["000001.SZ"]
        wind = parse_wind_constituents(wind_envelope(codes), expected_code="884201.WI")
        hithink = parse_hithink_constituents(
            hithink_envelope(codes, timestamp=1794741119000),
            expected_code="885728.TI",
        )
        with self.subTest("date mismatch"):
            with self.assertRaises(SectorMappingError):
                evaluate_overlap(self.candidate, wind, hithink)

        wrong_name = {
            "wind": {"code": "884201.WI", "name": "人工智能指数"},
            "hithink": {"code": "885728.TI", "name": "云计算"},
        }
        same_day_hithink = parse_hithink_constituents(
            hithink_envelope(codes), expected_code="885728.TI"
        )
        with self.subTest("name mismatch"):
            with self.assertRaises(SectorMappingError):
                evaluate_overlap(wrong_name, wind, same_day_hithink)


class SectorMappingCollectionTests(unittest.TestCase):
    def test_collection_keeps_pass_review_and_safe_failure_visible(self):
        candidates = [
            {
                "wind": {"code": "884201.WI", "name": "人工智能指数"},
                "hithink": {"code": "885728.TI", "name": "人工智能"},
            },
            {
                "wind": {"code": "884091.WI", "name": "云计算指数"},
                "hithink": {"code": "885362.TI", "name": "云计算"},
            },
            {
                "wind": {"code": "8841665.WI", "name": "数据要素指数"},
                "hithink": {"code": "886041.TI", "name": "数据要素"},
            },
        ]

        def wind_runner(candidate):
            code = candidate["wind"]["code"]
            if code == "8841665.WI":
                raise SectorMappingError("WIND_CLI_FAILED")
            codes = ["000001.SZ", "000002.SZ"]
            return wind_envelope(codes, windcode=code)

        def hithink_runner(candidate):
            code = candidate["hithink"]["code"]
            codes = (
                ["000001.SZ", "000002.SZ"]
                if code == "885728.TI"
                else ["000001.SZ", "600000.SH"]
            )
            return hithink_envelope(codes)

        audit = collect_overlap_audit(candidates, wind_runner, hithink_runner)

        self.assertEqual(audit["schemaVersion"], "sector-overlap-audit-v1")
        self.assertEqual(audit["gateVersion"], "sector-overlap-gate-v1")
        self.assertEqual(
            audit["summary"],
            {"total": 3, "priceHistoryCandidates": 1, "manualReview": 1, "invalidEvidence": 1},
        )
        self.assertEqual(
            [item["status"] for item in audit["candidates"]],
            ["price_history_candidate", "manual_review", "invalid_evidence"],
        )
        self.assertEqual(audit["candidates"][2]["errorCode"], "WIND_CLI_FAILED")
        self.assertNotIn("errorMessage", audit["candidates"][2])

    def test_provider_runners_use_single_target_argv_and_parse_complete_json(self):
        calls = []

        def command_runner(argv, *, cwd, timeout):
            calls.append((argv, cwd, timeout))
            if argv[0] == "node":
                payload = wind_envelope(["000001.SZ"])
            else:
                payload = hithink_envelope(["000001.SZ"])
            return type("Result", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})()

        candidate = {
            "wind": {"code": "884201.WI", "name": "人工智能指数"},
            "hithink": {"code": "885728.TI", "name": "人工智能"},
        }
        wind_runner = make_wind_runner("/opt/wind-skill", command_runner=command_runner)
        hithink_runner = make_hithink_runner("/opt/hithink-finance", command_runner=command_runner)

        wind_runner(candidate)
        hithink_runner(candidate)

        self.assertEqual(calls[0][0][:4], ["node", "scripts/cli.mjs", "call", "index_data"])
        self.assertEqual(calls[0][0][4], "get_index_basicinfo")
        self.assertIn("884201.WI", json.loads(calls[0][0][5])["question"])
        self.assertEqual(calls[0][1], "/opt/wind-skill")
        self.assertEqual(
            calls[1][0],
            [
                "/opt/hithink-finance",
                "index",
                "constituents",
                "--thscode",
                "885728.TI",
                "--max-rows",
                "0",
                "--format",
                "json",
            ],
        )
        self.assertIsNone(calls[1][1])

    def test_cli_writes_aggregate_only_audit_from_versioned_candidates(self):
        candidate = {
            "wind": {"code": "884201.WI", "name": "人工智能指数"},
            "hithink": {"code": "885728.TI", "name": "人工智能"},
        }
        codes = ["000001.SZ", "000002.SZ"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidates_path = root / "candidates.json"
            output_path = root / "audit.json"
            candidates_path.write_text(
                json.dumps(
                    {"mappingVersion": "wind-hithink-concepts-2026-11-16", "candidates": [candidate]}
                ),
                encoding="utf-8",
            )

            exit_code = run_cli(
                [
                    "--candidates",
                    str(candidates_path),
                    "--output",
                    str(output_path),
                    "--wind-skill-dir",
                    "/opt/wind-skill",
                    "--hithink-cli",
                    "/opt/hithink-finance",
                ],
                wind_runner=lambda item: wind_envelope(codes, windcode=item["wind"]["code"]),
                hithink_runner=lambda item: hithink_envelope(codes),
            )

            self.assertEqual(exit_code, 0)
            audit = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(audit["mappingVersion"], "wind-hithink-concepts-2026-11-16")
            self.assertEqual(audit["summary"]["priceHistoryCandidates"], 1)
            self.assertNotIn("members", output_path.read_text(encoding="utf-8"))


class SectorHistoryQualificationTests(unittest.TestCase):
    def test_identical_long_history_qualifies_without_exposing_prices(self):
        rows = [
            {"date": f"2025-{1 + index // 28:02d}-{1 + index % 28:02d}", "close": 100 + index}
            for index in range(280)
        ]

        result = evaluate_history_alignment(rows, rows)

        self.assertEqual(result["schemaVersion"], "sector-history-qualification-v1")
        self.assertEqual(result["gateVersion"], "sector-history-gate-v1")
        self.assertEqual(result["status"], "history_qualified")
        self.assertEqual(result["commonCount"], 280)
        self.assertEqual(result["dailyReturnCorrelation"], 1.0)
        self.assertNotIn("rows", result)
        self.assertNotIn("prices", result)

    def test_short_divergent_history_is_rejected_with_named_failed_gates(self):
        wind = [
            {"date": f"2026-08-{1 + index:02d}", "close": 100 * (1.01**index)}
            for index in range(20)
        ]
        hithink = [
            {
                "date": f"2026-08-{1 + index:02d}",
                "close": 100 + (index if index % 2 == 0 else -index / 2),
            }
            for index in range(20)
        ]

        result = evaluate_history_alignment(wind, hithink)

        self.assertEqual(result["status"], "history_rejected")
        self.assertIn("minimumCommonCloses", result["failedGates"])
        self.assertIn("dailyReturnCorrelation", result["failedGates"])
        self.assertIn("dailyDirectionAgreement", result["failedGates"])

    def test_history_evaluator_rejects_duplicate_dates_and_invalid_closes(self):
        with self.subTest("duplicate"):
            with self.assertRaises(SectorMappingError):
                evaluate_history_alignment(
                    [
                        {"date": "2026-11-12", "close": 100},
                        {"date": "2026-11-12", "close": 101},
                    ],
                    [{"date": "2026-11-12", "close": 100}],
                )
        with self.subTest("nonpositive"):
            with self.assertRaises(SectorMappingError):
                evaluate_history_alignment(
                    [{"date": "2026-11-12", "close": 0}],
                    [{"date": "2026-11-12", "close": 100}],
                )


if __name__ == "__main__":
    unittest.main()
