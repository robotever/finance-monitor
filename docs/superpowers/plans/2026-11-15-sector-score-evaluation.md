# Sector Score Evaluation Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, read-only point-in-time framework that evaluates sector strength, opportunity and risk against simple baselines over 1/3/5/10 official trading days.

**Architecture:** Add a separate pure-Python evaluator beside the unchanged release diagnostic. It consumes canonical official-close rows, constructs exact forward outcomes, computes native and common-sample factor statistics, and renders versioned JSON or Markdown without provider access or persistence.

**Tech Stack:** Python 3 standard library, `unittest`, existing rotation state/config contracts.

**Spec:** `docs/superpowers/specs/2026-11-15-sector-score-evaluation-design.md`

## Global Constraints

- Do not change online score formulas, data collection, publication, D1 schema or UI.
- Keep `rotation_diagnostics.py` behavior unchanged.
- Never bridge missing official dates or drop identities based on future outcomes.
- Keep industry and concept universes separate and fail closed on mixed versions, duplicates or malformed inputs.
- Use no new runtime dependency and perform no output-file writes.
- Every result remains `CALCULATION_ONLY`, `liveVerified=false`.

## Review Focus

- Future-dated availability must exclude a score before any outcome metric is calculated.
- A missing forward return for one eligible identity must invalidate the whole score-date sample.
- Risk direction must be positive for safer-return IC and positive for worse-outcome raw-risk spreads.
- Model/baseline comparisons must use same-date identity intersections while native coverage remains disclosed.
- Fewer than 20 valid matured samples must retain metrics but report `INSUFFICIENT_EVIDENCE`.

---

### Task 1: Point-in-time outcome and signal evaluation core

**Files:**
- Create: `tools/market_dashboard/rotation_evaluation.py`
- Create: `tools/market_dashboard/tests/test_rotation_evaluation.py`

**Interfaces:**
- Consumes: canonical close rows, official date list and config.
- Produces: `evaluate(rows: list[dict], official_dates: list[str], config: dict) -> dict` with `sector-score-evaluation-v1` output; pure helpers remain private.

- [ ] **Step 1: Write failing tests for hand-computed return metrics and exact-date PIT behavior**

Tests must prove 1/3/5/10 horizons, compounded returns, rank IC direction, quintile spread, hit rate, top-group drawdown, future availability exclusion and whole-date invalidation on one missing identity.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python3 -m unittest tools.market_dashboard.tests.test_rotation_evaluation -v`

Expected: FAIL because `rotation_evaluation` does not exist.

- [ ] **Step 3: Implement strict validation, signal extraction, exact forward paths and native summaries**

Implement `evaluate(rows, official_dates, config)` using finite raw axes, axis completeness, opportunity close gate, baseline fields and exact next official dates. Return per-date statuses and native coverage without modifying inputs.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python3 -m unittest tools.market_dashboard.tests.test_rotation_evaluation -v`

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

Commit: `feat: add point-in-time sector score evaluation core`

### Task 2: Fair baseline comparisons, robustness slices and risk diagnostics

**Files:**
- Modify: `tools/market_dashboard/rotation_evaluation.py`
- Modify: `tools/market_dashboard/tests/test_rotation_evaluation.py`

**Interfaces:**
- Consumes: Task 1 evaluation samples.
- Produces: common-sample model/baseline comparisons, chronological slices, leave-one-out checks, IC information ratio, signal turnover and dedicated raw-risk diagnostics.

- [ ] **Step 1: Write failing tests for unequal coverage, slice balance, risk direction and evidence labels**

Use literal fixtures to prove common identity intersections, sample-standard-deviation ICIR, earlier-slice remainder assignment, raw-risk loss/drawdown spreads, and `<20` matured sample interpretation.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python3 -m unittest tools.market_dashboard.tests.test_rotation_evaluation -v`

Expected: FAIL on missing comparison and robustness fields.

- [ ] **Step 3: Implement comparison and robustness outputs**

Add fixed baseline mapping, native coverage, common-sample comparisons, contiguous three-slice summaries, leave-one-date/sector minimum spread, adjacent-date top-quintile turnover and risk-specific diagnostics.

- [ ] **Step 4: Run focused and existing diagnostic tests**

Run: `python3 -m unittest tools.market_dashboard.tests.test_rotation_evaluation tools.market_dashboard.tests.test_operations -v`

Expected: PASS with unchanged release-diagnostic behavior.

- [ ] **Step 5: Commit Task 2**

Commit: `feat: compare sector scores with robust baselines`

### Task 3: JSON/Markdown CLI and operating documentation

**Files:**
- Modify: `tools/market_dashboard/rotation_evaluation.py`
- Modify: `tools/market_dashboard/tests/test_rotation_evaluation.py`
- Create: `docs/sector-score-evaluation.md`
- Modify: `docs/PROJECT_STRUCTURE.md`
- Modify: `docs/market-dashboard-operations.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: Task 2 report dictionary and canonical state envelope.
- Produces: `render_markdown(report: dict) -> str` and CLI `python3 -m tools.market_dashboard.rotation_evaluation --state ... --calendar ... [--config ...] [--format json|markdown]`.

- [ ] **Step 1: Write failing CLI and renderer tests**

Tests must execute the real CLI, parse default JSON, inspect user-visible Markdown tables/warnings, and prove invalid inputs return exit 1 with safe format-appropriate output and no traceback.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python3 -m unittest tools.market_dashboard.tests.test_rotation_evaluation -v`

Expected: FAIL because the renderer/CLI contract is absent.

- [ ] **Step 3: Implement renderer and CLI, then document use and interpretation**

Document metric definitions, commands, evidence limits, baseline mapping, data maturity states and version-change rules. Do not add an automated weight recommendation.

- [ ] **Step 4: Run complete verification**

Run: `python3 -m unittest discover -s tools/market_dashboard/tests -v`

Run: `npm test`

Run: `npm run build`

Expected: all commands exit 0.

- [ ] **Step 5: Commit Task 3**

Commit: `docs: add sector score evaluation workflow`
