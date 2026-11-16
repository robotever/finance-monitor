# Market Dashboard Runtime Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent AC-powered idle sleep from skipping A-share dashboard windows and make private payload validation failures safely diagnosable.

**Architecture:** A detached, lock-guarded macOS helper holds an AC-only `caffeinate` assertion through the Shanghai trading session, while the existing wrapper and five-minute LaunchAgent remain unchanged in responsibility. Validation errors gain an enum-like rule identifier written only to private health state; publication remains fail-closed.

**Tech Stack:** Python 3 standard library, Bash wrapper, macOS launchd/caffeinate, unittest, Node test runner.

**Spec:** `docs/superpowers/specs/2026-11-16-market-dashboard-runtime-resilience-design.md`

## Global Constraints

- Preserve the 15:30 Asia/Shanghai close availability boundary.
- Never log credentials, provider responses, raw values, or full payloads.
- AC-only sleep prevention; battery operation remains unchanged.
- Do not change providers, scoring, refresh frequency, or Cloudflare schemas.

## Review Focus

- DST/local timezone differences must not change Shanghai session calculation.
- Multiple five-minute launches must create at most one active assertion.
- Symlinked state or lock paths must fail closed.
- A helper failure must not block the dashboard job.
- Validation diagnostics must remain a fixed safe rule name, never arbitrary exception text.

---

### Task 1: AC-only session wake guard

**Files:**
- Create: `ops/macos/market_dashboard_awake.py`
- Modify: `ops/macos/run-market-dashboard.sh`
- Modify: `tools/market_dashboard/tests/test_operations.py`

**Interfaces:**
- Produces: `session_seconds(now: datetime) -> int` and `hold_awake(state_root: Path, now: datetime | None = None, runner=...) -> str`.
- Wrapper starts the helper before executing the existing CLI; helper status never changes CLI arguments or exit status.

- [ ] Add failing tests for Shanghai window boundaries, weekend, lock exclusivity, symlink rejection, and wrapper integration.
- [ ] Run the focused operations tests and confirm failures are caused by the missing helper.
- [ ] Implement the helper and minimal wrapper launch.
- [ ] Run the focused operations tests and confirm they pass.
- [ ] Commit `fix: keep powered dashboard host awake during trading`.

### Task 2: Safe validation rule diagnostics

**Files:**
- Modify: `tools/market_dashboard/job.py`
- Modify: `tools/market_dashboard/tests/test_job.py`
- Modify: `docs/market-dashboard-operations.md`
- Modify: `docs/verification/2026-11-16-sector-production-rollout.md`

**Interfaces:**
- Produces: `ValidationError.rule: str` from an allowlisted rule vocabulary.
- Private health JSON may contain `validationRule`; public payloads and CLI summaries do not.

- [ ] Add failing tests for an object with no usable score and for health-state rule recording/clearing.
- [ ] Run focused job tests and confirm the expected failures.
- [ ] Implement minimal rule propagation without exposing exception text.
- [ ] Run focused job tests and confirm they pass.
- [ ] Document the power requirement and safe diagnostic field.
- [ ] Commit `fix: expose safe dashboard validation diagnostics`.

### Task 3: Full verification and activation

**Files:**
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes Tasks 1–2; produces a verified stable runtime update.

- [ ] Run the complete Python suite.
- [ ] Run the complete Node suite.
- [ ] Run the production build.
- [ ] Inspect the diff for secrets, raw provider data and accidental contract changes.
- [ ] Update changelog and commit documentation.
- [ ] Merge/fast-forward the stable checkout, reload only the existing dashboard LaunchAgent, and verify its next outside-session wake exits cleanly.
