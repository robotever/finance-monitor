# Sector rotation shadow release record

Status: **NOT RELEASE ELIGIBLE — local implementation and synthetic verification only**. Production remains v2. This record does not authorize migration, deployment, v3 publication, persistent feature activation or external LaunchAgent changes.

## Evidence boundaries

- Local code can collect private shadow snapshots, write safe health metadata and an atomic private ledger, run offline historical calculations, and assess release evidence without changing v2 state.
- No real ten-trading-day shadow window has been executed for this release. A fabricated or replayed date is not an observed trading day. Default weekday scheduling does not establish an official calendar.
- Wind live historical schema, quotas, and full-universe 20/60/250-close coverage remain unverified. Historical flow and breadth must be dated observations available at that close; current rolling fields cannot reconstruct them.
- Stable LaunchAgent/env activation and user production-switch approval remain outstanding external steps. The existing label and 300-second interval must be retained. This task changes neither.
- Synthetic diagnostics below establish arithmetic and failure behavior only. They do not establish predictive validity, live coverage or release eligibility. Ten live days alone would establish operational evidence, not predictive validity.

## Private runtime artifacts

All paths are relative to the real parent project's `state/market-dashboard-shadow/`, never this checkout's public assets:

| Artifact | Meaning |
| --- | --- |
| `last-success.json` | Committed private v3 snapshot, derived close history and `shadowOperation` recovery proof |
| `health.json` | Allowlisted counts, coverage, sessions, timestamps, latency, versions and safe codes |
| `rotation-ledger.json` | Versioned daily/session operational events, safe failures, private top-ten opportunity IDs/churn and distinct official successful close dates |

Directory mode is 0700; files are 0600. Ledger replacement uses a same-directory temporary file, file `fsync`, atomic replacement and directory `fsync`. Symlinked state root, shadow directory and ledger file are rejected. Caller holds the existing provider lock. A failed snapshot commit never records a successful close. A post-commit ledger failure returns `LEDGER_WRITE_FAILED` while preserving the committed close; the next writable run repairs the ledger from `shadowOperation` before replacing that proof. A duplicate run does not collect or publish. A read-only report never repairs or writes state.

`rotationCloseSuccesses` counts distinct successful dates from explicit `schedule.tradingDates`; without a verified official calendar it remains zero. Its lifetime count is not the release-window denominator. The evaluator derives the exact ten-date window's successes from events. Successful retries do not erase failed attempts. Version mismatch rejects the ledger rather than silently combining versions.

## Ten official trading days — pending live evidence

Before starting, record the official calendar source/retrieval time, window start/end, stable checkout commit, score/universe versions, operator, Wind schema/units/identity evidence and quota budget in the private evidence bundle. Configure the official dates; do not substitute weekdays or synthetic fixture dates. Use the same version and every scheduled observation throughout. Do not tune within this version.

| Day | Official date | Industry/concept identities | Median / minimum candidate completeness | Close source time / max latency | Publication skipped | Safe failures | Industry/concept top-ten churn | Close committed / evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| 2 | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| 3 | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| 4 | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| 5 | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| 6 | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| 7 | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| 8 | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| 9 | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |
| 10 | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending |

Each day's private ledger covers 09:45, 11:30, 14:00 and close attempts. Close timestamps must be at least 15:00 Shanghai; the oldest contributing source determines maximum latency. Close catch-up stops at 15:30. Release requires latency at most 600 seconds even if later catch-up succeeds. `rotationCoverage` is the median completeness across all 110 sectors; per-candidate minimum completeness is recorded separately. Empty candidate lists are explicitly zero-count, not evidence of candidate quality. Churn is `1 - intersection/max(previous_count,current_count)` for each universe's top ten potential-rotation candidates; both empty lists produce zero, first close is null.

## Historical diagnostics — pending live inputs

The read-only tool consumes canonical private derived close records and an ordered official-calendar JSON array. It does not collect, refit, rescore from future data or publish:

```bash
python3 -m tools.market_dashboard.rotation_diagnostics \
  --state "$MARKET_DASHBOARD_STATE_ROOT/market-dashboard-shadow/last-success.json" \
  --calendar /absolute/private/official-history-dates.json > /absolute/private/historical-diagnostics.json
```

A canonical row has fixed sector identity/universe, both sector versions, `marketDate`, `session=close`, `officialClose=true`, timezone-aware `observedAt`, optional `availableAt` and `_rawScores.opportunity`, `opportunity`, `completeness`, `validCloses` and derived `metrics.return1d` in percent. `availableAt` defaults to the recorded close observation; historical replays must supply actual availability. Only scores available by that observation (15:00–15:30 Shanghai), with at least 20 closes and completeness at least 70, enter the ranking. Existing live private scoring state is the intended source; unsupported price-only backfills cannot manufacture opportunity scores. Missing data and null opportunities remain missing.

For industries and concepts separately, every calendar date appears under each 1/3/5-day horizon with `VALID`, `NO_PIT_SCORES`, `UNMATURED_OUTCOME` or `MISSING_FORWARD_RETURNS`. Exact next official dates are used; no missing date is bridged and no constituent is dropped because its future return is missing. Scores are ordered by unrounded opportunity, completeness, stable ID; absent private precision uses the recorded public score and must be disclosed in a live audit. Top and bottom quintiles use `max(1,floor(N/5))` sectors. Metrics are:

- Mean daily cross-sectional Spearman rank correlation, with midpoint ties; undefined correlations remain null.
- Mean high-minus-low buy-and-hold compounded forward return, in percentage points.
- High-group constituent hit rate relative to the eligible universe's mean forward return (fraction).
- Worst high-group equal-weight buy-and-hold drawdown within any horizon, in percent. Overlapping horizon outcomes are not chained into a fictitious equity curve.
- Top-ten opportunity-list turnover by score date, independent of future outcome availability.
- Minimum spread after leaving out each date and each sector. `nonDominated=true` requires at least two valid dates and positive spread after every deletion; a sole usable date cannot pass.

This is opportunity diagnostics only. It does not validate strength continuation or risk drawdown forecasts, compare against momentum/position baselines, account for fees, correct overlapping observations, or remove concept overlap. Report those limits with the live result. Live audit must also verify score-date full-universe coverage, timestamp/unit/identity lineage and archived PIT provenance; calculation code cannot prove those upstream facts.

The CLI always marks `liveVerified=false`. A later operator-reviewed live evidence bundle must attach the actual provenance, schema/quota/20/60/250 coverage, historical dates, metrics and domination checks before a separately signed historical report can state `liveVerified=true`. Editing that boolean without evidence is not verification.

| Universe | 1d IC / spread / hit / MDD | 3d IC / spread / hit / MDD | 5d IC / spread / hit / MDD | Turnover | Date/sector domination | Live evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Industries | Pending | Pending | Pending | Pending | Pending | Not available |
| Concepts | Pending | Pending | Pending | Pending | Pending | Not available |

## Release gate evaluation — fail closed

```bash
python3 -m tools.market_dashboard.rotation_operations \
  --ledger "$MARKET_DASHBOARD_STATE_ROOT/market-dashboard-shadow/rotation-ledger.json" \
  --calendar /absolute/private/exact-ten-official-dates.json \
  --historical /absolute/private/reviewed-historical-diagnostics.json
```

Optional `--config` selects the same versioned configuration. Calendar JSON must contain exactly ten unique ordered officially verified dates, including missing/failed days; never select ten successful dates after the fact. The program reads only, exits 1 on failed/missing evidence, and returns `productionMode=v2`, `productionSwitchApproved=false` even if all evidence gates pass. Operator review must confirm that these are consecutive official dates and that the historical evidence is genuine.

| Required gate | Current result |
| --- | --- |
| 35/35 industries at each successful formal observation | Pending live evidence |
| At least 95% of 75 concepts (at least 72 identities) | Pending live evidence |
| Universe median completeness ≥80 | Pending live evidence |
| Each opportunity candidate completeness ≥70, with actual candidates observed | Pending live evidence |
| ≥9 successful official closes in the exact ten-date window | **Not satisfied: no live window** |
| No identity, unit or future-time errors | Pending live evidence; retained failures cannot be erased by retries |
| Close max source latency ≤600 seconds; publication always skipped | Pending live evidence |
| All 1/3/5-day diagnostics disclosed, matching versions and reviewed live provenance | **Not satisfied: historical data unverified** |
| Positive, non-dominated 3d or 5d high-minus-low opportunity spread separately in both universes | Pending live evidence |
| User approval after the evidence is presented | **Not requested / not granted** |

Any failed gate leaves v2 in production. A version that fails is not tuned against the same evaluation window; create a new version and new verification record. After all evidence exists, present the full live ledger, historical report and rollback plan for explicit user production-switch approval. D1 migration, deployment, v3 publication and feature activation remain separately controlled external effects.

## Local verification evidence

Task 8 local execution logs and synthetic historical JSON live under ignored `.superpowers/sdd/2026-11-14-sector-opportunity-rotation/task-8-artifacts/`; the local task report records actual test counts, build and desktop/mobile QA evidence. Do not copy the private runtime ledger or raw provider data into this document. Local fixtures do not populate the live ten-day table above.
