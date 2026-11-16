# Hithink sector migration probe — 2026-11-16

One authorized live invocation through `--hithink-probe --max-calls 25` completed.
The checked-in JSON retains the aggregate observations and includes an offline
correction to the original attempt accounting. The private original was not rerun.

- Logical CLI data requests: **25**; elapsed: **4.089 seconds**.
- **Correction:** the previous **<=50** remote-data-attempt claim was invalid.
  The CLI permits three outer attempts plus one OAuth recovery per window, so
  these 25 single-window commands allowed **up to 100** data attempts. Actual
  attempts were unobserved; compliance with the **50-attempt cap is unverified**.
  This is not evidence that 100 attempts occurred or that the run stayed under 50.
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
- Original decision was `continueAutomatically=false`. **Superseded by the
  2026-11-16 user decision:** Hithink is fee-unrestricted; private implementation
  continues (`continueAutomatically=true`) with **complete=false** and required
  capability validation. Neither unknown points nor the 963-call estimate is a
  stop gate. The existing data/attempt observations remain unchanged. No full backfill,
  production feature database, deployment, publishing or schedule change occurred.

The 30-history target remained incomplete when the previous logical-call budget
stopped. That stop did **not** establish compliance with the absolute remote
attempt cap. The corrected implementation independently reserves up to four data
attempts per request window, accounts for possible history splits before
subprocess dispatch, and permits at most 12 live logical calls. Default library
budgets use the same four-attempt reservation; explicitly retry-free offline
providers can use one. No credentials were inspected, and **no new live probe**
was performed while correcting this evidence.

Offline tests cover the full 10+20 sample, missing/reported point metadata,
50-call exhaustion, four-attempt live reservation and split-window accounting, full-market paging, early rejection
of 100-row paging, empty history-batch detection, authorization gates, safe
private report rewrites without trailing JSON and wrapper isolation. Those tests are not live coverage.

The user decision removes economic vetoes only. Provider authorization remains
unknown and public release remains ineligible. Partial historical coverage,
unmeasured snapshots/batch behavior, and unobserved actual remote attempts remain
factual gaps. No additional live probe was performed for this policy correction.
