# Sector rotation data feasibility — 2026-11-14

## Decision

**Live status: `BLOCKED_RUNTIME`; exact safe provider code: `NETWORK_ERROR`.**
The first sample request failed. No current observations or historical closes
were verified in this run. Stop live collection here; do not change production
scoring or publish opportunity output based on this evidence.

Task 2 may implement the pure engine with explicitly missing components. This
probe does not satisfy the production data-feasibility gate. Task 4 must continue
withholding public opportunity output until the approved evidence and release
gates pass, including 20 same-method trading-day observations, the applicable
70% completeness requirement and 15 official closes for the history matrix.
The later ten-trading-day shadow verification remains required. Less than 60
days remains cold start; missing 250-day history stays missing.

## Live evidence

Command: `python3 -m tools.market_dashboard.rotation_probe --scope sample --metadata-only`

| Item | Result | Evidence status |
| --- | --- | --- |
| Request start | 2026-11-14T06:01:26.417942+00:00 | Verified metadata |
| Exit status | 1 | Verified |
| Terminal status / safe code | `BLOCKED_RUNTIME` / `NETWORK_ERROR` | Verified |
| First request duration / total elapsed | 1.390 s / 1.390 s | Verified metadata; failed-request latency only |
| Requests attempted | 1 industry price-indicator batch containing 6 verified identities | Verified |
| Industry observations returned | 0 | Verified |
| Concept/history requests attempted | 0 / 0 | Verified |
| Source timestamps and unit sets | None returned | Unavailable in this run |
| Earliest/latest historical dates | None returned | Unavailable in this run |
| Authentication and remaining quota | Not established by a network failure | Still to confirm |

No retry, alternate provider, concurrency, full probe or full backfill followed
the failed request. No raw response, provider message, numeric market payload,
source body or credential was printed or saved. The CLI retained the response
only in memory and emitted counts, allowlisted field names/units, dates, timing
and safe codes. The final CLI also reports requested identity counts and
minimum/maximum observed close counts; these metadata additions were validated
offline after the one live attempt, without another provider request.

## Sampling and call budget

The sample fixes six existing industry codes: `882100.WI`, `882115.WI`,
`882120.WI`, `882125.WI`, `882130.WI`, `882136.WI`; and six existing concepts:
`884201.WI`, `8841349.WI`, `8841699.WI`, `8841049.WI`, `8841432.WI`,
`8841201.WI`. These spread across defensive, cyclical, technology, broad and
niche themes. Their relative size/activity profiles are sampling hypotheses,
**still to confirm**, rather than measured liquidity classifications.

Current fields use the existing serial batched `get_index_price_indicators`
collector path. Historical calls use `index_data.get_index_kline`, exactly one
verified code per call, explicit ISO dates and `period="1d"`. The sample would
request the 550-calendar-day interval ending on the prior Shanghai calendar day;
that range is not a guarantee of 250 trading closes and does not fabricate an
exchange calendar. The summary counts only actually validated dated closes.

| Scope | Current requests | Historical requests | Evidence status |
| --- | --- | --- | --- |
| Sample: 6 industries + 6 concepts | 2 batches | Up to 12 serial calls after successful current batches | Verified offline control flow |
| Full: 35 industries + 75 concepts | 3 batches: 35 / 50 / 25 | 110 estimated single-code calls; not executed by full mode | Verified offline count/limit behavior |
| Monetary/points cost and remaining quota | Unknown | Unknown | Still to confirm with provider/account evidence |

Full mode prints its call estimate before any provider request, checks the
current universe only, and never starts a full historical backfill. The 110
call estimate covers one interval request per identity, not pagination or
provider billing. The 110-object universe respects the documented per-request
limit of 50 identities, but fitting quota is **still to confirm**.

## Field and historical capability

| Component | Requested/current contract | 20 closes | 60 closes | 250 closes |
| --- | --- | --- | --- | --- |
| Price | Current 1/5/20-day returns, amount and turnover; dated OHLC through daily K-line | Still to confirm live | Still to confirm live | Still to confirm live |
| Main flow | Current 1/5/20-day main-flow snapshots | Unavailable through chosen history route | Unavailable through chosen history route | Unavailable through chosen history route |
| Breadth | Current up/down/flat counts | Unavailable through chosen history route | Unavailable through chosen history route | Unavailable through chosen history route |
| Timestamps / returned units / full identity coverage | Required and summarized by current collectors | Still to confirm live | Still to confirm live | Still to confirm live |

The field request and offline assertions cover all required current fields and
timestamps for both groups. Industry requests now include the missing 5/20-day
main flow and flat count. No scoring formula, score weights, public API, UI,
Cloudflare resource or production state was changed.

Current rolling flow/return fields are not dated historical observations.
The documented K-line route supplies price history and does not establish
historical flow or component breadth. Those components must start as
forward-collected, same-method observations unless a separate approved and
verified historical source is established. This is a route limitation, not a
claim that every Wind service lacks historical flow/breadth. Corporate
classification changes, historical constituent comparability, trading-time
latency/stability, actual K-line response schema and achievable history length
remain **still to confirm**.

## Validation

- TDD first cycle: focused command ran 36 tests with 8 expected failures before
  implementation (missing adapter/probe and missing industry requested fields).
- Second metadata cycle: probe command ran 10 tests with 2 expected assertion
  failures for missing close-count metadata and per-request timing. Both were
  implemented only after observing those failures.
- `python3 -m unittest tools.market_dashboard.tests.test_rotation_probe tools.market_dashboard.tests.test_sources -v`: 39 passed.
- `python3 -m unittest discover -s tools/market_dashboard/tests -v`: 118 passed.
- `npm test`: 65 passed.
- `git diff --check`: passed. Changed-file review and a credential/raw-data scan
  found only synthetic test values, source code and safe metadata documentation.

Adapter tests cover a single verified identity, exact daily parameters, invalid
dates and periods, future/out-of-window dates, duplicates, wrong identities,
missing/non-finite OHLC and safe provider-error propagation. Probe tests cover
serial 12-history sample success, immediate stop on first current/history error,
35/50/25 full-universe batching, pre-request estimation, no full backfill,
metadata-only output and no probe file writes.

Data source route: Wind Financial Data Service. No successful live market data
was returned by this attempt.
