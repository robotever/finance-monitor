# Sector Production Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a clearly labelled real-data sector-rotation beta without duplicate Wind collection and preserve the v2 fallback.

**Architecture:** Add a single-process combined scheduler with a lazy shared collector, source-date trading-day evidence and fail-closed v3 publication. Deploy the existing D1 schema/API and enable a production observation UI that does not alter `releaseEligible` or score semantics.

**Tech Stack:** Python 3 standard library, Bash wrapper, Vue 3/TypeScript, Cloudflare Pages Functions and D1, Node test runner.

**Spec:** `docs/superpowers/specs/2026-11-15-sector-production-rollout-design.md`

## Global Constraints

- No synthetic payload may be published to production.
- One combined wake may call `collect_batches` at most once.
- Credentials and provider responses never enter logs, CLI arguments, reports or Git.
- `releaseEligible=false` remains authoritative; production visibility means observation beta, not validated signal.
- v2 remains independently readable and deploy rollback never drops D1 data.

## Review Focus

- A shared collection that fails must not be silently retried by the second consumer in the same wake; Task 2 pins exception/result caching.
- A stale prior-trading-day Wind batch on a weekday must create only safe local non-trading evidence and publish nothing; Task 1 pins date mismatch.
- v3 publish success followed by local persistence failure must be safely idempotent on retry; Task 3 pins server duplicate behavior and local advancement.
- Production UI must not confuse observation visibility with `releaseEligible`; Task 4 pins the banner and fallback.
- Disabling either rotation flag must restore the existing v2-only behavior without a service reinstall; Task 2 and Task 5 pin flags and wrapper arguments.

---

### Task 1: Data-confirmed trading calendar

**Files:**
- Modify: `tools/market_dashboard/job.py`
- Modify: `tools/market_dashboard/tests/test_job.py`
- Modify: `tools/market_dashboard/tests/test_operations.py`

**Interfaces:**
- Produces: private per-date negative calendar evidence and `verify_market_date(batches, now)` used before scoring/publication.

- [ ] Write tests for current-date acceptance, stale-date rejection, same-day skip after negative evidence, and valid close ledger counting.
- [ ] Run focused tests and observe the expected failures.
- [ ] Implement strict source-date proof and atomic private cache without new provider calls.
- [ ] Run focused tests and the Python suite.
- [ ] Commit `feat: verify trading sessions from market evidence`.

### Task 2: One collection per combined wake

**Files:**
- Modify: `tools/market_dashboard/job.py`
- Modify: `ops/macos/run-market-dashboard.sh`
- Modify: `tools/market_dashboard/tests/test_job.py`
- Modify: `tools/market_dashboard/tests/test_operations.py`

**Interfaces:**
- Consumes: Task 1 market-date verification.
- Produces: `run_combined_cycle(args, deps=None)` and `--with-rotation` CLI orchestration with a lazy cached collector.

- [ ] Write tests proving one collector call at overlap, one call at rotation-only time, no second call after error, and v2-only behavior when disabled.
- [ ] Run focused tests and observe the expected failures.
- [ ] Implement rotation-first orchestration and replace the wrapper's two-process branch.
- [ ] Run focused tests and the Python suite.
- [ ] Commit `feat: share provider batches across dashboard jobs`.

### Task 3: Controlled v3 publication

**Files:**
- Modify: `tools/market_dashboard/job.py`
- Modify: `ops/macos/run-market-dashboard.sh`
- Modify: `tools/market_dashboard/tests/test_job.py`
- Modify: `tools/market_dashboard/tests/test_operations.py`
- Modify: `docs/market-dashboard-operations.md`

**Interfaces:**
- Consumes: Task 2 combined cycle and existing `publish_payload`.
- Produces: `--rotation-publish` selected only by `MARKET_DASHBOARD_ROTATION_PUBLISH=1`.

- [ ] Write tests for disabled publication, authenticated success, failed publish without bucket advancement, retry/idempotency, and redacted summaries.
- [ ] Run focused tests and observe the expected failures.
- [ ] Implement publish-before-commit with existing transport and safe health metadata.
- [ ] Run focused tests, Python suite and Functions publication tests.
- [ ] Commit `feat: add controlled sector rotation publication`.

### Task 4: Production observation UI

**Files:**
- Modify: `src/components/MarketResearchDashboard.vue`
- Modify: `tests/market-dashboard-components.test.mjs`
- Modify: `tests/sector-rotation-components.test.mjs`
- Modify: `vite.config.ts`
- Modify: `package.json`

**Interfaces:**
- Consumes: v3 latest/rotation APIs already defined.
- Produces: `build:production-rotation` and a visible real-data observation banner while preserving v2 fallback.

- [ ] Write tests for production v3 activation, persistent observation wording, `releaseEligible=false` disclosure, malformed-v3 fallback and acceptance isolation.
- [ ] Run focused tests and observe the expected failures.
- [ ] Implement production observation mode without loopback restriction or fixture fallback.
- [ ] Run Node suite and both ordinary/rotation production builds.
- [ ] Commit `feat: expose real sector rotation observation beta`.

### Task 5: Operations, deployment and first-day acceptance

**Files:**
- Modify: `docs/market-dashboard-operations.md`
- Create: `docs/verification/2026-11-16-sector-production-rollout.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: Tasks 1-4, migration `0002_sector_rotation.sql`, stable checkout and existing Cloudflare project.
- Produces: deployed Pages/D1, stable service flags and a safe first-day evidence checklist.

- [ ] Run full Python/Node suites and production build; record exact results.
- [ ] Apply remote D1 migrations, deploy the production rotation build, and record deployment ID.
- [ ] Verify public v2/v3 endpoints, unauthorized publish rejection, HTML metadata and no fixture markers without invoking Wind.
- [ ] Merge to stable `main`, push GitHub, then atomically enable `MARKET_DASHBOARD_ROTATION_SHADOW=1` and `MARKET_DASHBOARD_ROTATION_PUBLISH=1` in the private parent `.env`; do not kickstart.
- [ ] Verify LaunchAgent remains loaded, interval unchanged, paths stable and next natural session is armed.
- [ ] At the first natural trading snapshot, record counts/completeness/quota/publish outcome; if unavailable in this session, leave the automated service armed and document the exact pending evidence rather than claiming success.
- [ ] Commit `docs: record sector production rollout` and complete final review.
