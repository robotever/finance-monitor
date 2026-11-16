# Hithink Historical Data Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a strict read-only adapter and audit command for the verified local Hithink daily-price database without changing production scoring.

**Architecture:** A focused Python module constructs only allowlisted paginated SELECT statements and invokes the official Hithink CLI through an injectable runner. It validates and minimizes every response, while a separate audit projection exposes coverage and quality without raw provider envelopes.

**Tech Stack:** Python 3 standard library, `unittest`, installed Hithink Financial API CLI.

**Spec:** `docs/superpowers/specs/2026-11-16-hithink-history-adapter-design.md`

## Global Constraints

- Do not change score formulas, online providers, Cloudflare storage, UI or schedules.
- Do not add a Python DuckDB dependency or accept arbitrary SQL.
- Never read, print or persist the Hithink API Key or raw provider error message.
- Fail closed on malformed, truncated, duplicated, out-of-range or non-finite data.
- Do not aggregate stock rows into Wind industry/concept histories without point-in-time membership evidence.

## Review Focus

- A malicious or malformed symbol/date must be rejected before a runner is called.
- Pagination must neither duplicate nor omit a boundary row and must stop after a short final page.
- A successful-looking response with `truncated=true`, mismatched count or an out-of-range row must fail closed.
- A valid requested symbol with no returned rows must remain visible as missing rather than becoming silent success.
- CLI failure output must expose only a stable safe code, never the external stderr or response envelope.

---

### Task 1: Strict paginated daily-history adapter

**Files:**
- Create: `tools/market_dashboard/hithink_history.py`
- Create: `tools/market_dashboard/tests/test_hithink_history.py`

**Interfaces:**
- Consumes: `runner(argv)`, absolute CLI/database paths, `symbols: list[str]`, ISO start/end dates, `adjustment: str`, `page_size: int`.
- Produces: `load_daily_closes(...) -> dict` with schema `hithink-daily-history-v1`, minimized rows and explicit coverage metadata.

- [ ] **Step 1: Write failing validation, pagination and response-contract tests**

Tests use literal complete CLI envelopes and prove allowlisted SQL, two-page stable ordering, missing-symbol disclosure, malformed/truncated/count-mismatched response rejection, duplicate rejection and runner-not-called input rejection.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python3 -m unittest tools.market_dashboard.tests.test_hithink_history -v`

Expected: FAIL because `hithink_history` does not exist.

- [ ] **Step 3: Implement `load_daily_closes` and safe response parsing**

Implement fixed view mapping `none -> v_daily`, `qfq -> v_daily_qfq`, `hfq -> v_daily_hfq`; validate `^[0-9]{6}\.(SH|SZ|BJ)$`, canonical ISO dates and page size `1..1000`; emit only lower-case read-only SELECT with deterministic `order by date, thscode`, `limit` and `offset`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python3 -m unittest tools.market_dashboard.tests.test_hithink_history -v`

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

Commit: `feat: add hithink historical data adapter`

### Task 2: Safe audit CLI and operating documentation

**Files:**
- Modify: `tools/market_dashboard/hithink_history.py`
- Modify: `tools/market_dashboard/tests/test_hithink_history.py`
- Modify: `docs/DATA_SOURCES.md`
- Modify: `docs/PROJECT_STRUCTURE.md`
- Modify: `docs/market-dashboard-operations.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: Task 1 `hithink-daily-history-v1` batch.
- Produces: `audit_history(batch: dict) -> dict` with schema `hithink-history-audit-v1`; CLI `python3 -m tools.market_dashboard.hithink_history --cli ... --db ... --symbols ... --start ... --end ... [--adjustment ...]`.

- [ ] **Step 1: Write failing audit and real CLI behavior tests**

Tests prove a complete batch produces hand-checked counts/date bounds, a missing symbol produces incomplete audit and nonzero CLI exit, invalid external output returns only `HITHINK_HISTORY_ERROR`, and no price rows/raw envelopes appear in audit JSON.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python3 -m unittest tools.market_dashboard.tests.test_hithink_history -v`

Expected: FAIL because audit and CLI contracts are absent.

- [ ] **Step 3: Implement audit, CLI and documentation**

Add aggregate-only JSON output, safe exception handling and explicit operational commands. Document that the adapter is available but production sector integration is blocked on point-in-time identity mapping.

- [ ] **Step 4: Run complete verification**

Run: `python3 -m unittest discover -s tools/market_dashboard/tests -v`

Run: `npm test`

Run: `npm run build`

Expected: all commands exit 0.

- [ ] **Step 5: Commit Task 2**

Commit: `docs: add hithink history audit workflow`
