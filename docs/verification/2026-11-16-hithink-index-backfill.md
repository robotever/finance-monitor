# Hithink private index backfill — 2026-11-16

Usable normalized history exists for all 90 primary industries and all 390 qualified concepts: **429,190 bars**. Requested window is 2023-01-01 through 2026-11-13 in Asia/Shanghai. No scores were calculated or published; v3 scheduling and data remain intact.

| Valid observation threshold | Sectors meeting threshold |
| --- | ---: |
| 20 | 480 / 480 |
| 60 | 479 / 480 |
| 250 | 475 / 480 |

Full requested-window completeness is **false**: `886082.TI` has missing volume/turnover on its earliest provider observation, 2023-12-29. The strict adapter rejected the full response, including after retry. A separately checkpointed strict subwindow retained 693 valid bars from 2024-01-02 through 2026-11-13; no fields were imputed and the original failure remains recorded. All other 479 requested-window checkpoints succeeded. Row thresholds do not establish exchange-calendar completeness or pre-inception history.

Five short histories are retained without inflation: `886108.TI` 202 rows, `886110.TI` 93, `886111.TI` 92, `886112.TI` 70 and `886113.TI` 25.

The full resumed pass used 479 logical CLI requests in 126.098 seconds, paced at least 0.25 seconds apart, with 1,916 conservative reserved remote attempts. Across initial network validation, full pass, retry, safe schema diagnostic and strict subwindow recovery there were 484 logical history dispatches. Opaque CLI retry counts are unknown. Hithink fee/point gates were not applied.

Implementation: `7018a71`. Latest focused verification: 74 tests passed; earlier integration with operations: 96 tests passed. Live writes committed at most 250 bars at a time under the shared private-store lock. The provider stock database remained unopened. Raw responses, credentials and constituent rows were not retained in Git. Public release remains separately gated and is not authorized by this evidence.

[Per-sector normalized coverage](2026-11-16-hithink-index-backfill.json)
