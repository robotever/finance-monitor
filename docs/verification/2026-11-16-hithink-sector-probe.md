# Hithink sector migration probe — 2026-11-16

One authorized live invocation through `--hithink-probe --max-calls 25` completed.
The checked-in JSON is an aggregate-only copy of the private safe summary.

- Logical CLI data requests: **25**; elapsed: **4.089 seconds**.
- Remote data-request attempt upper bound: **50**, reserving a possible hidden
  OAuth retry for each CLI request. Actual HTTP attempts are not exposed.
- Provider points: **unknown** (zero metered responses); `reportedPoints=0` is
  only the sum of reported charges, not evidence of zero actual consumption.
- Catalog coverage: **90** primary industries and **390** concepts.
- Historical sample completed: **10/10 industries, 13/20 concepts**. All **23**
  completed sectors returned at least 250 valid daily bars in the configured
  2023-01-01 through 2026-11-13 window.
- Budget stop: `PROBE_CALL_BUDGET`. The remaining 7 concept histories, batch
  capability, index snapshots and stock paging were **not tested live**.
- Full initial-run estimate: **at least 963 logical data requests**: 2 catalogs,
  480 single-index histories, 480 memberships, 1 shared index snapshot, plus
  unmeasured stock snapshot pages. Index-only history estimate: **480**.
- Full-run point estimate: **unknown**. Rough observed-mean elapsed projection:
  **157.499 seconds**, excluding unmeasured snapshot paging and future recurring
  refreshes; this is an estimate, not an acceptance timing result.
- Provider authorization: **unknown**; public release eligible: **false**.
- `continueAutomatically=false`; migration **stops at Task 3**. No full backfill,
  production feature database, deployment, publishing or schedule change occurred.

The 30-history sample target is deliberately incomplete because the absolute
remote-attempt budget takes precedence. The reusable library retains the planned
50-call budget for injected providers; the live entry point enforces at most 25
logical calls. No credentials were inspected to select a looser authentication
path, and the probe was not rerun after its budget stop.

Offline tests cover the full 10+20 sample, missing/reported point metadata,
50-call exhaustion, hidden-retry live cap, full-market paging, early rejection
of 100-row paging, empty history-batch detection, authorization gates, safe
private persistence and wrapper isolation. Those tests are not live coverage.
