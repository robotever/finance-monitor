"""Fail-closed current-constituent overlap evaluation for sector mappings."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any


SCHEMA_VERSION = "sector-overlap-evidence-v1"
GATE_VERSION = "sector-overlap-gate-v1"
_A_SHARE_CODE = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
_WIND_INDEX_CODE = re.compile(r"^[0-9]+\.WI$")
_HITHINK_INDEX_CODE = re.compile(r"^[0-9]{6}\.TI$")
_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


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
    if not isinstance(data, list) or len(data) != 1:
        raise SectorMappingError("INVALID_WIND_TABLE")
    table = _require_dict(data[0], "INVALID_WIND_TABLE")
    columns = table.get("columns")
    rows = table.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list) or not rows:
        raise SectorMappingError("INVALID_WIND_TABLE")
    names = []
    for column in columns:
        names.append(_require_dict(column, "INVALID_WIND_COLUMNS").get("name"))
    required = {"指数成份代码", "指数成份简称", "Wind代码", "证券简称", "日期"}
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
