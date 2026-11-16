# Task 11 — Hithink sector UI

Implemented an isolated v4 adapter and presenters. Global/A-share cards and styles retain their existing source. Only the sector module changes when `VITE_HITHINK_SECTOR_V4=true` and a validated v4 snapshot exists. The flag defaults off and is excluded from the synthetic acceptance environment. `NO_SNAPSHOT` or an incompatible snapshot restores the existing complete v3 sector chain; v4 endpoints never supply v3 rows.

The homepage shows all three industry views, each capped at ten, and separate core-25/dynamic-10 concept choices. Empty qualifying lists remain empty. The full directory at `/sectors/hithink` supports literal name/code search, industry/concept selection, view/role filters, 25/50/100-row pages, previous/next controls, rank-based history matrices and sector detail. Request cancellation prevents older searches from replacing newer results. Scores and changes retain nulls as em dashes. Source, five versions, observation time, freshness, incomplete lists and current-membership history warnings are visible. Returns display two decimals; missing-input families have readable Chinese descriptions.

## Verification

- Ten new model/API/component tests passed, including real mounted dashboard flag-off, `NO_SNAPSHOT`, ready-snapshot switching and preservation of global cards.
- `npm run build:production-rotation` passed after the final UI change. The existing Browserslist age notice remains informational.
- Browser review used all 480 actual normalized local rows: 90 industries and 390 concepts, reviewed core25 and dynamic10.
- Literal `885522.TI` search returned one actual concept (`养老概念`); actual `小家电` detail opened through the v4 read handler. On a 390px viewport, document width was 386px, with no horizontal page overflow.
- Screenshots remain private, untracked artifacts: desktop overview, detail, phone cards and phone page top under `output/playwright/`. They are not bundled or committed.

## Actual-data preview and limitation

The actual data represents market date 2026-11-16 reconstructed after midnight on 2026-11-17. The original arrival time and `officialClose=false` are preserved. That payload cannot meet the production manifest's same-market-date observation contract. Production validation was not relaxed and no timestamps were fabricated.

A temporary, loopback-only reconstructed-data inspector at `http://127.0.0.1:5184/__hithink-preview` renders the same production sector-card components, uses actual public row projections and the actual read handlers, and supports core/dynamic choices, full-directory search/paging and details. A persistent warning distinguishes historical reconstruction from natural-session acceptance. Its private SQLite bridge and temporary entry are outside the repository. This inspector is review evidence, not an enabled production board or a natural trading-day acceptance result. The actual payload has no official close history yet; that absence is shown explicitly.

Publishing, enabling the production flag and the natural trading-day acceptance remain outside Task 11. No public deployment or data upload was performed.

## Fifteen-date reconstruction follow-up

The private inspector was updated to read the authoritative `current-snapshot.json` bundle exactly once. Its matching `closeHistory` and `historyChunks` contain 15 actual market dates (2026-10-27 through 2026-11-16), 7,200 sector rows and 150 chunks. Compatibility files are not read by this inspector.

The local reconstruction route displays a 15-column, ten-rank matrix built from actual scores/ranks, plus producer-computed changes against the preceding reconstructed market date. All original arrival times and `officialClose=false` are preserved. The first visible date has no prior comparison and displays missing changes as em dashes. No reconstructed day is inserted as an official close.

A browser click on the first-ranked `信托概念` cell dated 2026-10-27 opened a detail panel with all 15 market dates and the selected date highlighted first. The complete 15-column matrix, selected historical detail and 390px mobile view were captured in private screenshots. The browser also reconfirmed core25, dynamic10 and literal `885522.TI` returning exactly one match. The phone check rejected horizontal page overflow and passed.

The production detail handler correctly canonicalizes batches sharing an arrival timestamp, so it does not present these reconstructed days as 15 separate contemporaneous observations. The inspector's explicitly local reconstruction adapter uses the matching published projections per actual market date for this view; production handlers and contracts remain unchanged. New screenshots are `hithink-actual-15date-matrix-expanded.png`, `hithink-actual-15date-history-detail.png` and `hithink-actual-15date-mobile-top.png` under the private, untracked screenshot directory.
