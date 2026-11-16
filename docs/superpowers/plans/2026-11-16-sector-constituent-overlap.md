# Sector Constituent Overlap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a fail-closed, reproducible comparison of current Wind and Hithink constituents for the 32 same-name concept candidates.

**Architecture:** A focused Python module parses minimized provider envelopes, validates snapshot identity, computes overlap metrics, and applies a versioned conservative gate. A CLI collector invokes the existing official provider CLIs and writes only aggregate, reviewable evidence to the repository.

**Tech Stack:** Python 3 standard library, `unittest`, installed Wind MCP CLI, installed Hithink Financial API CLI.

**Spec:** `docs/superpowers/specs/2026-11-16-sector-constituent-overlap-design.md`

## Global Constraints

- Do not change production scoring, providers, UI, Cloudflare storage, or schedules.
- Never commit raw constituent lists, provider envelopes, credentials, or unrestricted error output.
- Fail closed on malformed, truncated, duplicated, empty, cross-target, or cross-date evidence.
- A passed mapping is only a price-history candidate and never authorizes historical breadth, flow, or score reconstruction.

## Review Focus

- Provider columns may change order; parsing must bind by validated column names.
- A repeated constituent must invalidate evidence rather than be silently deduplicated.
- Same-name concepts with radically different population sizes must not pass.
- Partial provider failures must remain visible per candidate without converting missing evidence into zero overlap.
- Aggregate output must contain only bounded difference samples, not full proprietary member lists.

---

### Task 1: Pure overlap evaluator and provider parsers

**Files:**
- Create: `tools/market_dashboard/sector_mapping.py`
- Create: `tools/market_dashboard/tests/test_sector_mapping.py`

**Interfaces:**
- Consumes: literal Wind and Hithink response envelopes plus one candidate mapping.
- Produces: `parse_wind_constituents`, `parse_hithink_constituents`, and `evaluate_overlap` returning `sector-overlap-evidence-v1`.

- [ ] Write tests for passing overlap, low overlap, malformed/truncated/duplicate data, target mismatch and date mismatch.
- [ ] Run the focused test and verify RED because the module is absent.
- [ ] Implement the minimal validators, metrics and versioned gate.
- [ ] Run focused and complete Python tests and verify GREEN.
- [ ] Commit Task 1.

### Task 2: Reproducible collection CLI and versioned candidate file

**Files:**
- Modify: `tools/market_dashboard/sector_mapping.py`
- Modify: `tools/market_dashboard/tests/test_sector_mapping.py`
- Create: `config/sector-price-history-candidates.json`
- Modify: `docs/DATA_SOURCES.md`
- Modify: `docs/verification/2026-11-16-hithink-sector-mapping-feasibility.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: the 32 explicit Wind/Hithink code pairs and official CLI paths.
- Produces: an aggregate-only JSON result with per-candidate status and bounded difference samples.

- [ ] Write failing CLI aggregation tests using complete local fixtures and injected runners.
- [ ] Run focused tests and verify RED for the absent collector.
- [ ] Implement sequential collection with safe per-candidate failure records and no raw committed data.
- [ ] Run the real 32-candidate collection and write the versioned aggregate result.
- [ ] Update documentation with evidence and explicit limitations.
- [ ] Run all Python tests, Node tests and the production build; commit Task 2.
