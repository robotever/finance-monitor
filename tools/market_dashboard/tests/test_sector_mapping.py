import json
import unittest


from tools.market_dashboard.sector_mapping import (
    SectorMappingError,
    evaluate_overlap,
    parse_hithink_constituents,
    parse_wind_constituents,
)


def wind_envelope(codes, *, windcode="884201.WI", date="2026-11-16"):
    columns = [
        {"name": "指数成份代码", "type": "string"},
        {"name": "指数成份简称", "type": "string"},
        {"name": "Wind代码", "type": "string"},
        {"name": "证券简称", "type": "string"},
        {"name": "日期", "type": "date"},
    ]
    rows = [[code, f"证券{index}", windcode, "人工智能指数", date] for index, code in enumerate(codes)]
    payload = {"data": {"data": [{"columns": columns, "rows": rows}]}, "error": None}
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


if __name__ == "__main__":
    unittest.main()
