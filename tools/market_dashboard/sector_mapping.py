"""Fail-closed current-constituent overlap evaluation for sector mappings."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import tempfile
from typing import Any


SCHEMA_VERSION = "sector-overlap-evidence-v1"
GATE_VERSION = "sector-overlap-gate-v1"
_A_SHARE_CODE = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
_WIND_INDEX_CODE = re.compile(r"^[0-9]+\.WI$")
_HITHINK_INDEX_CODE = re.compile(r"^[0-9]{6}\.TI$")
_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_SAFE_ERROR_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


class SectorMappingError(ValueError):
    """Raised when provider evidence is incomplete or internally inconsistent."""


def _require_dict(value: Any, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SectorMappingError(code)
    return value


def _validate_index_code(code: str, pattern: re.Pattern[str], error_code: str) -> None:
    if not isinstance(code, str) or not pattern.fullmatch(code):
        raise SectorMappingError(error_code)


def _validate_member_code(code: Any) -> str:
    if not isinstance(code, str) or not _A_SHARE_CODE.fullmatch(code):
        raise SectorMappingError("INVALID_MEMBER_CODE")
    return code


def _normalize_name(name: Any) -> str:
    if not isinstance(name, str):
        raise SectorMappingError("INVALID_CONCEPT_NAME")
    normalized = name.strip().replace("（", "(").replace("）", ")").replace(" ", "")
    normalized = re.sub(r"(?:指数|概念)$", "", normalized)
    if not normalized:
        raise SectorMappingError("INVALID_CONCEPT_NAME")
    return normalized


def parse_wind_constituents(
    envelope: dict[str, Any], *, expected_code: str
) -> dict[str, Any]:
    """Parse one complete Wind ``get_index_basicinfo`` constituent response."""

    _validate_index_code(expected_code, _WIND_INDEX_CODE, "INVALID_WIND_CODE")
    outer = _require_dict(envelope, "INVALID_WIND_RESPONSE")
    if outer.get("isError") is not False:
        raise SectorMappingError("WIND_RESPONSE_ERROR")
    content = outer.get("content")
    if not isinstance(content, list) or len(content) != 1:
        raise SectorMappingError("INVALID_WIND_RESPONSE")
    block = _require_dict(content[0], "INVALID_WIND_RESPONSE")
    if block.get("type") != "text" or not isinstance(block.get("text"), str):
        raise SectorMappingError("INVALID_WIND_RESPONSE")
    try:
        payload = json.loads(block["text"])
    except json.JSONDecodeError as exc:
        raise SectorMappingError("INVALID_WIND_JSON") from exc
    payload = _require_dict(payload, "INVALID_WIND_PAYLOAD")
    if payload.get("error") is not None:
        raise SectorMappingError("WIND_RESPONSE_ERROR")
    data = _require_dict(payload.get("data"), "INVALID_WIND_PAYLOAD").get("data")
    if not isinstance(data, list) or not data:
        raise SectorMappingError("INVALID_WIND_TABLE")
    required = {"指数成份代码", "指数成份简称", "Wind代码", "证券简称", "日期"}
    matching_tables = []
    for candidate_table in data:
        candidate_table = _require_dict(candidate_table, "INVALID_WIND_TABLE")
        candidate_columns = candidate_table.get("columns")
        if not isinstance(candidate_columns, list):
            continue
        candidate_names = [
            column.get("name") if isinstance(column, dict) else None
            for column in candidate_columns
        ]
        if required.issubset(candidate_names):
            matching_tables.append(candidate_table)
    if len(matching_tables) != 1:
        raise SectorMappingError("INVALID_WIND_TABLE")
    table = matching_tables[0]
    columns = table.get("columns")
    rows = table.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list) or not rows:
        raise SectorMappingError("INVALID_WIND_TABLE")
    names = []
    for column in columns:
        names.append(_require_dict(column, "INVALID_WIND_COLUMNS").get("name"))
    if not required.issubset(names) or len(set(names)) != len(names):
        raise SectorMappingError("INVALID_WIND_COLUMNS")
    positions = {name: names.index(name) for name in required}

    members: dict[str, str] = {}
    snapshot_dates: set[str] = set()
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns):
            raise SectorMappingError("INVALID_WIND_ROW")
        if row[positions["Wind代码"]] != expected_code:
            raise SectorMappingError("WIND_TARGET_MISMATCH")
        code = _validate_member_code(row[positions["指数成份代码"]])
        name = row[positions["指数成份简称"]]
        if not isinstance(name, str) or not name.strip():
            raise SectorMappingError("INVALID_MEMBER_NAME")
        if code in members:
            raise SectorMappingError("DUPLICATE_WIND_MEMBER")
        date = row[positions["日期"]]
        if not isinstance(date, str) or not _ISO_DATE.fullmatch(date):
            raise SectorMappingError("INVALID_WIND_DATE")
        members[code] = name.strip()
        snapshot_dates.add(date)
    if len(snapshot_dates) != 1:
        raise SectorMappingError("INCONSISTENT_WIND_DATE")
    return {
        "provider": "wind",
        "indexCode": expected_code,
        "snapshotDate": next(iter(snapshot_dates)),
        "members": members,
    }


def parse_hithink_constituents(
    envelope: dict[str, Any], *, expected_code: str
) -> dict[str, Any]:
    """Parse one complete Hithink ``index constituents`` response."""

    _validate_index_code(expected_code, _HITHINK_INDEX_CODE, "INVALID_HITHINK_CODE")
    outer = _require_dict(envelope, "INVALID_HITHINK_RESPONSE")
    if outer.get("ok") is not True or outer.get("command") != "index.constituents":
        raise SectorMappingError("HITHINK_RESPONSE_ERROR")
    meta = _require_dict(outer.get("meta"), "INVALID_HITHINK_META")
    if meta.get("truncated") is not False:
        raise SectorMappingError("TRUNCATED_HITHINK_RESPONSE")
    data = _require_dict(outer.get("data"), "INVALID_HITHINK_DATA")
    items = data.get("item")
    timestamp = data.get("timestamp")
    if not isinstance(items, list) or not items:
        raise SectorMappingError("INVALID_HITHINK_DATA")
    if meta.get("count") != len(items):
        raise SectorMappingError("HITHINK_COUNT_MISMATCH")
    if not isinstance(timestamp, int) or timestamp <= 0:
        raise SectorMappingError("INVALID_HITHINK_TIMESTAMP")

    members: dict[str, str] = {}
    for item in items:
        item = _require_dict(item, "INVALID_HITHINK_MEMBER")
        code = _validate_member_code(item.get("thscode"))
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise SectorMappingError("INVALID_MEMBER_NAME")
        if code in members:
            raise SectorMappingError("DUPLICATE_HITHINK_MEMBER")
        members[code] = name.strip()
    snapshot_date = datetime.fromtimestamp(timestamp / 1000, timezone.utc).date().isoformat()
    return {
        "provider": "hithink",
        "indexCode": expected_code,
        "snapshotDate": snapshot_date,
        "members": members,
    }


def evaluate_overlap(
    candidate: dict[str, Any],
    wind_snapshot: dict[str, Any],
    hithink_snapshot: dict[str, Any],
    *,
    difference_sample_limit: int = 5,
) -> dict[str, Any]:
    """Evaluate one same-name pair under the conservative v1 price-history gate."""

    if not isinstance(difference_sample_limit, int) or not 0 <= difference_sample_limit <= 20:
        raise SectorMappingError("INVALID_SAMPLE_LIMIT")
    candidate = _require_dict(candidate, "INVALID_CANDIDATE")
    wind = _require_dict(candidate.get("wind"), "INVALID_CANDIDATE")
    hithink = _require_dict(candidate.get("hithink"), "INVALID_CANDIDATE")
    _validate_index_code(wind.get("code"), _WIND_INDEX_CODE, "INVALID_WIND_CODE")
    _validate_index_code(hithink.get("code"), _HITHINK_INDEX_CODE, "INVALID_HITHINK_CODE")
    if _normalize_name(wind.get("name")) != _normalize_name(hithink.get("name")):
        raise SectorMappingError("CONCEPT_NAME_MISMATCH")
    if wind_snapshot.get("indexCode") != wind["code"]:
        raise SectorMappingError("WIND_TARGET_MISMATCH")
    if hithink_snapshot.get("indexCode") != hithink["code"]:
        raise SectorMappingError("HITHINK_TARGET_MISMATCH")
    if wind_snapshot.get("snapshotDate") != hithink_snapshot.get("snapshotDate"):
        raise SectorMappingError("SNAPSHOT_DATE_MISMATCH")
    wind_members = wind_snapshot.get("members")
    hithink_members = hithink_snapshot.get("members")
    if not isinstance(wind_members, dict) or not wind_members:
        raise SectorMappingError("INVALID_WIND_MEMBERS")
    if not isinstance(hithink_members, dict) or not hithink_members:
        raise SectorMappingError("INVALID_HITHINK_MEMBERS")

    wind_codes = set(wind_members)
    hithink_codes = set(hithink_members)
    intersection = wind_codes & hithink_codes
    union = wind_codes | hithink_codes
    jaccard = len(intersection) / len(union)
    wind_coverage = len(intersection) / len(wind_codes)
    hithink_coverage = len(intersection) / len(hithink_codes)
    passed = jaccard >= 0.70 and wind_coverage >= 0.80 and hithink_coverage >= 0.80

    return {
        "schemaVersion": SCHEMA_VERSION,
        "gateVersion": GATE_VERSION,
        "status": "price_history_candidate" if passed else "manual_review",
        "snapshotDate": wind_snapshot["snapshotDate"],
        "wind": {"code": wind["code"], "name": wind["name"]},
        "hithink": {"code": hithink["code"], "name": hithink["name"]},
        "counts": {
            "wind": len(wind_codes),
            "hithink": len(hithink_codes),
            "intersection": len(intersection),
            "union": len(union),
        },
        "metrics": {
            "jaccard": round(jaccard, 6),
            "windCoverage": round(wind_coverage, 6),
            "hithinkCoverage": round(hithink_coverage, 6),
        },
        "differenceSamples": {
            "windOnly": sorted(wind_codes - hithink_codes)[:difference_sample_limit],
            "hithinkOnly": sorted(hithink_codes - wind_codes)[:difference_sample_limit],
        },
        "allowedUse": "price_history_research_only",
    }


def _validated_close_map(rows: Any, provider: str) -> dict[str, float]:
    if not isinstance(rows, list) or not rows:
        raise SectorMappingError(f"INVALID_{provider}_HISTORY")
    closes: dict[str, float] = {}
    for row in rows:
        row = _require_dict(row, f"INVALID_{provider}_HISTORY")
        date = row.get("date")
        close = row.get("close")
        if not isinstance(date, str) or not _ISO_DATE.fullmatch(date):
            raise SectorMappingError(f"INVALID_{provider}_HISTORY_DATE")
        try:
            if datetime.strptime(date, "%Y-%m-%d").date().isoformat() != date:
                raise ValueError
        except ValueError as exc:
            raise SectorMappingError(f"INVALID_{provider}_HISTORY_DATE") from exc
        if isinstance(close, bool) or not isinstance(close, (int, float)):
            raise SectorMappingError(f"INVALID_{provider}_HISTORY_CLOSE")
        close = float(close)
        if not math.isfinite(close) or close <= 0:
            raise SectorMappingError(f"INVALID_{provider}_HISTORY_CLOSE")
        if date in closes:
            raise SectorMappingError(f"DUPLICATE_{provider}_HISTORY_DATE")
        closes[date] = close
    return closes


def _correlation(left: list[float], right: list[float]) -> float:
    left_mean = statistics.mean(left)
    right_mean = statistics.mean(right)
    left_var = sum((value - left_mean) ** 2 for value in left)
    right_var = sum((value - right_mean) ** 2 for value in right)
    if left_var == 0 or right_var == 0:
        return 1.0 if left == right else 0.0
    covariance = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right)
    )
    return covariance / math.sqrt(left_var * right_var)


def evaluate_history_alignment(
    wind_rows: list[dict[str, Any]], hithink_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Qualify a current-membership candidate using price-history agreement."""

    wind = _validated_close_map(wind_rows, "WIND")
    hithink = _validated_close_map(hithink_rows, "HITHINK")
    common_dates = sorted(set(wind) & set(hithink))
    if len(common_dates) < 2:
        raise SectorMappingError("INSUFFICIENT_COMMON_HISTORY")
    first_date, last_date = common_dates[0], common_dates[-1]
    wind_window = {date for date in wind if first_date <= date <= last_date}
    hithink_window = {date for date in hithink if first_date <= date <= last_date}
    common_count = len(common_dates)
    wind_coverage = common_count / len(wind_window)
    hithink_coverage = common_count / len(hithink_window)

    wind_returns = [
        wind[current] / wind[previous] - 1
        for previous, current in zip(common_dates, common_dates[1:])
    ]
    hithink_returns = [
        hithink[current] / hithink[previous] - 1
        for previous, current in zip(common_dates, common_dates[1:])
    ]
    correlation = _correlation(wind_returns, hithink_returns)
    absolute_differences = [
        abs(wind_return - hithink_return) * 100
        for wind_return, hithink_return in zip(wind_returns, hithink_returns)
    ]
    direction_matches = [
        (wind_return == 0 and hithink_return == 0)
        or wind_return * hithink_return > 0
        for wind_return, hithink_return in zip(wind_returns, hithink_returns)
    ]
    mean_absolute_difference = statistics.mean(absolute_differences)
    direction_agreement = sum(direction_matches) / len(direction_matches)

    windows: dict[str, dict[str, float]] = {}
    failed_gates: list[str] = []
    if common_count < 250:
        failed_gates.append("minimumCommonCloses")
    if wind_coverage < 0.95:
        failed_gates.append("windDateCoverage")
    if hithink_coverage < 0.95:
        failed_gates.append("hithinkDateCoverage")
    if correlation < 0.95:
        failed_gates.append("dailyReturnCorrelation")
    if mean_absolute_difference > 0.25:
        failed_gates.append("meanAbsoluteDailyReturnDifference")
    if direction_agreement < 0.85:
        failed_gates.append("dailyDirectionAgreement")
    for size in (20, 60, 250):
        if common_count <= size:
            continue
        wind_change = wind[common_dates[-1]] / wind[common_dates[-1 - size]] - 1
        hithink_change = hithink[common_dates[-1]] / hithink[common_dates[-1 - size]] - 1
        difference = abs(wind_change - hithink_change) * 100
        windows[str(size)] = {
            "windPct": round(wind_change * 100, 6),
            "hithinkPct": round(hithink_change * 100, 6),
            "absDiffPp": round(difference, 6),
        }
        if difference > 2.0:
            failed_gates.append(f"windowReturnDifference{size}")

    return {
        "schemaVersion": "sector-history-qualification-v1",
        "gateVersion": "sector-history-gate-v1",
        "status": "history_qualified" if not failed_gates else "history_rejected",
        "firstCommonDate": first_date,
        "lastCommonDate": last_date,
        "windCount": len(wind),
        "hithinkCount": len(hithink),
        "commonCount": common_count,
        "windOnlyDates": len(set(wind) - set(hithink)),
        "hithinkOnlyDates": len(set(hithink) - set(wind)),
        "windDateCoverage": round(wind_coverage, 6),
        "hithinkDateCoverage": round(hithink_coverage, 6),
        "dailyReturnCorrelation": round(correlation, 6),
        "meanAbsoluteDailyReturnDifferencePp": round(mean_absolute_difference, 6),
        "medianAbsoluteDailyReturnDifferencePp": round(
            statistics.median(absolute_differences), 6
        ),
        "maxAbsoluteDailyReturnDifferencePp": round(max(absolute_differences), 6),
        "dailyDirectionAgreement": round(direction_agreement, 6),
        "windowReturns": windows,
        "failedGates": failed_gates,
        "allowedUse": "price_history_research_only" if not failed_gates else "none",
    }


def _default_command_runner(argv: list[str], *, cwd: str | None, timeout: int):
    return subprocess.run(
        argv,
        cwd=cwd,
        timeout=timeout,
        capture_output=True,
        text=True,
        check=False,
    )


def _parse_command_json(result: Any, error_code: str) -> dict[str, Any]:
    if getattr(result, "returncode", None) != 0:
        raise SectorMappingError(error_code)
    stdout = getattr(result, "stdout", None)
    if not isinstance(stdout, str):
        raise SectorMappingError(error_code)
    try:
        return _require_dict(json.loads(stdout), error_code)
    except json.JSONDecodeError as exc:
        raise SectorMappingError(error_code) from exc


def make_wind_runner(
    skill_dir: str,
    *,
    command_runner=_default_command_runner,
    timeout: int = 120,
):
    """Return a single-target Wind constituent collector."""

    if not isinstance(skill_dir, str) or not skill_dir:
        raise SectorMappingError("INVALID_WIND_SKILL_DIR")

    def run(candidate: dict[str, Any]) -> dict[str, Any]:
        wind = _require_dict(candidate.get("wind"), "INVALID_CANDIDATE")
        code = wind.get("code")
        name = wind.get("name")
        _validate_index_code(code, _WIND_INDEX_CODE, "INVALID_WIND_CODE")
        if not isinstance(name, str) or not name.strip():
            raise SectorMappingError("INVALID_CONCEPT_NAME")
        params = json.dumps(
            {"question": f"查询Wind{name}{code}的全部当前成份股代码、简称和成份数量"},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        argv = [
            "node",
            "scripts/cli.mjs",
            "call",
            "index_data",
            "get_index_basicinfo",
            params,
        ]
        try:
            result = command_runner(argv, cwd=skill_dir, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SectorMappingError("WIND_CLI_FAILED") from exc
        return _parse_command_json(result, "WIND_CLI_FAILED")

    return run


def make_hithink_runner(
    cli_path: str,
    *,
    command_runner=_default_command_runner,
    timeout: int = 120,
):
    """Return a single-target Hithink constituent collector."""

    if not isinstance(cli_path, str) or not cli_path:
        raise SectorMappingError("INVALID_HITHINK_CLI")

    def run(candidate: dict[str, Any]) -> dict[str, Any]:
        hithink = _require_dict(candidate.get("hithink"), "INVALID_CANDIDATE")
        code = hithink.get("code")
        _validate_index_code(code, _HITHINK_INDEX_CODE, "INVALID_HITHINK_CODE")
        argv = [
            cli_path,
            "index",
            "constituents",
            "--thscode",
            code,
            "--max-rows",
            "0",
            "--format",
            "json",
        ]
        try:
            result = command_runner(argv, cwd=None, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SectorMappingError("HITHINK_CLI_FAILED") from exc
        return _parse_command_json(result, "HITHINK_CLI_FAILED")

    return run


def collect_overlap_audit(
    candidates: list[dict[str, Any]],
    wind_runner,
    hithink_runner,
) -> dict[str, Any]:
    """Collect and evaluate candidates while retaining safe per-item failures."""

    if not isinstance(candidates, list) or not candidates:
        raise SectorMappingError("INVALID_CANDIDATE_LIST")
    wind_codes: set[str] = set()
    hithink_codes: set[str] = set()
    output: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate = _require_dict(candidate, "INVALID_CANDIDATE")
        wind = _require_dict(candidate.get("wind"), "INVALID_CANDIDATE")
        hithink = _require_dict(candidate.get("hithink"), "INVALID_CANDIDATE")
        wind_code = wind.get("code")
        hithink_code = hithink.get("code")
        _validate_index_code(wind_code, _WIND_INDEX_CODE, "INVALID_WIND_CODE")
        _validate_index_code(hithink_code, _HITHINK_INDEX_CODE, "INVALID_HITHINK_CODE")
        if wind_code in wind_codes or hithink_code in hithink_codes:
            raise SectorMappingError("DUPLICATE_CANDIDATE_CODE")
        wind_codes.add(wind_code)
        hithink_codes.add(hithink_code)
        try:
            wind_snapshot = parse_wind_constituents(
                wind_runner(candidate), expected_code=wind_code
            )
            hithink_snapshot = parse_hithink_constituents(
                hithink_runner(candidate), expected_code=hithink_code
            )
            output.append(evaluate_overlap(candidate, wind_snapshot, hithink_snapshot))
        except SectorMappingError as exc:
            error_code = str(exc)
            if not _SAFE_ERROR_CODE.fullmatch(error_code):
                error_code = "COLLECTION_FAILED"
            output.append(
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "gateVersion": GATE_VERSION,
                    "status": "invalid_evidence",
                    "wind": {"code": wind_code, "name": wind.get("name")},
                    "hithink": {"code": hithink_code, "name": hithink.get("name")},
                    "errorCode": error_code,
                    "allowedUse": "none",
                }
            )

    counts = {
        "price_history_candidate": sum(
            item["status"] == "price_history_candidate" for item in output
        ),
        "manual_review": sum(item["status"] == "manual_review" for item in output),
        "invalid_evidence": sum(item["status"] == "invalid_evidence" for item in output),
    }
    return {
        "schemaVersion": "sector-overlap-audit-v1",
        "gateVersion": GATE_VERSION,
        "summary": {
            "total": len(output),
            "priceHistoryCandidates": counts["price_history_candidate"],
            "manualReview": counts["manual_review"],
            "invalidEvidence": counts["invalid_evidence"],
        },
        "candidates": output,
    }


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise SectorMappingError("UNSAFE_OUTPUT_PATH")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def run_cli(
    argv: list[str] | None = None,
    *,
    wind_runner=None,
    hithink_runner=None,
) -> int:
    parser = argparse.ArgumentParser(description="Audit current Wind/Hithink concept overlap")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--wind-skill-dir", required=True)
    parser.add_argument("--hithink-cli", required=True)
    args = parser.parse_args(argv)
    try:
        candidate_path = Path(args.candidates)
        if candidate_path.is_symlink():
            raise SectorMappingError("UNSAFE_CANDIDATE_PATH")
        source = _require_dict(
            json.loads(candidate_path.read_text(encoding="utf-8")),
            "INVALID_CANDIDATE_FILE",
        )
        mapping_version = source.get("mappingVersion")
        candidates = source.get("candidates")
        if not isinstance(mapping_version, str) or not mapping_version:
            raise SectorMappingError("INVALID_MAPPING_VERSION")
        if wind_runner is None:
            wind_runner = make_wind_runner(args.wind_skill_dir)
        if hithink_runner is None:
            hithink_runner = make_hithink_runner(args.hithink_cli)
        audit = collect_overlap_audit(candidates, wind_runner, hithink_runner)
        audit["mappingVersion"] = mapping_version
        audit["evidenceScope"] = "current_constituents_only"
        _write_json_atomic(Path(args.output), audit)
        return 0 if audit["summary"]["invalidEvidence"] == 0 else 2
    except (OSError, json.JSONDecodeError, SectorMappingError):
        return 2


if __name__ == "__main__":
    sys.exit(run_cli())
