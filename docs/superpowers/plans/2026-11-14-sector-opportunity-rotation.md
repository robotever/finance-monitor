# Sector Opportunity and Rotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an evidence-backed sector rotation system that scores industries and concepts on strength, opportunity and risk, labels heat as a state, stores daily rankings, and renders current and historical rotation views without changing the existing global/A-share/style score semantics.

**Architecture:** Keep Wind as the authoritative sector-score provider and the existing D1 database as the public history store. A pure Python rotation engine consumes validated industry/concept observations plus earlier derived closes, emits versioned sector audit rows, and adds those rows to a `market-dashboard-v3` payload; Cloudflare validates and atomically stores both the dashboard snapshot and normalized sector rankings. The production UI remains on v2 until a data probe, historical diagnostics and a ten-trading-day shadow run pass the approved gates.

**Tech Stack:** Python 3.13, Wind MCP CLI, JSON configuration, `unittest`, Cloudflare Pages Functions and D1/SQLite, Node test runner, Vue 3, TypeScript, Vite, Playwright/Chromium for responsive QA.

**Spec:** `docs/superpowers/specs/2026-11-14-sector-opportunity-rotation-design.md`

## Global Constraints

- The new strength/opportunity/risk axes apply only to the fixed 35 industries and versioned 75-concept universe; global, A-share and six style objects keep strength/heat/risk.
- Wind supplies score inputs. MX may discover candidates but never rewrites the production universe or silently fills a missing Wind score.
- Do not store provider raw responses, credentials, model prose or local paths in D1, state, logs or public APIs.
- Missing inputs remain missing. Reweight only the observed configured weights and disclose completeness; never fill zero or median.
- Industry and concept universes normalize separately. Current-day values never enter their own trailing baseline.
- Public sector axes use 0–100 integers, while ranks use unrounded values, then completeness and stable sector ID to break ties.
- High opportunity (`>= 70`) requires at least two of funds, breadth and momentum improvement to score `>= 60`.
- Heat is one of `cold`, `warming`, `active`, `crowded`; it is not a fourth public score.
- Preserve every v2 record. v2 and v3 histories are never joined into score changes.
- First production opportunity output requires at least 20 valid closes, a 15-close matrix and the release gates in the spec; fewer than 60 closes remains cold start.
- All schedule times are Asia/Shanghai. Intraday windows have ten-minute tolerance; close collection requires source timestamps at or after 15:00 and may catch up only through 15:30.
- Serialized publish request remains at or below 256 KiB. If full derived audit rows exceed that limit, reduce repeated labels/provenance representation rather than raising the limit or dropping validation.

## Review Focus

- Historical price exists but historical flow or breadth does not: preserve the price history, mark the missing components and withhold opportunity until the 20-close/70%-completeness gate passes.
- A sector identity is renamed, duplicated or absent between current and historical batches: reject the affected universe version rather than merging identities by display name.
- A late batch arrives after a key window or a close batch has a pre-15:00 timestamp: do not backdate or advance the official close leaderboard.
- An object qualifies for more than one current view: apply the documented view predicates independently and keep deterministic per-view sorting; do not invent a hidden composite score.
- A D1 transaction inserts the dashboard row but fails a sector row: fail the whole batch so latest dashboard and rotation history cannot diverge.

---

## File Structure

- `config/market-dashboard.json` — v0.2 sector weights, thresholds, schedules, completeness gates and version identifiers.
- `config/market-concepts.json` — unchanged 75-concept universe plus its existing version identifier.
- `tools/market_dashboard/rotation.py` — pure normalization, atomic components, three-axis scoring, heat state, rankings and leaderboard counters.
- `tools/market_dashboard/rotation_probe.py` — safe live capability/latency/history probe that prints metadata only.
- `tools/market_dashboard/rotation_store.py` — validated local derived close history, v2-to-v3 isolation and 90-day recovery state.
- `tools/market_dashboard/sources.py` — current sector fields and explicit historical index K-line adapters.
- `tools/market_dashboard/job.py` — key-window scheduling, shadow-mode orchestration, v3 payload assembly and publication.
- `tools/market_dashboard/fixtures/rotation-history.json` — sanitized derived close history for deterministic tests.
- `tools/market_dashboard/tests/test_rotation*.py` — pure formulas, probe, store, scheduler, payload and failure tests.
- `migrations/0002_sector_rotation.sql` — normalized D1 ranking/audit table and query indexes.
- `functions/_lib/market-dashboard.js` — mixed legacy/sector v3 validation and safe audit-field validation.
- `functions/api/market-dashboard/{publish,latest,history}.js` — atomic v3 publication and compact v3 history.
- `functions/api/sector-rotation/{latest,history,detail}.js` — current views, daily matrix and one-sector audit history.
- `src/features/market-dashboard/{types.ts,api.mjs,model.mjs}` — v3 browser contracts and sector presentation model.
- `src/components/SectorRotationBoard.vue` — current potential/main/risk views and daily rotation matrix.
- `src/components/SectorRotationDetail.vue` — 60-close score/rank/audit detail.
- Existing sector components and styles — opportunity axis, heat label and responsive integration.
- Verification docs — data probe, shadow ledger and final production evidence.

### Task 1: Wind data feasibility and history probe

**Files:**
- Create: `tools/market_dashboard/rotation_probe.py`
- Create: `tools/market_dashboard/tests/test_rotation_probe.py`
- Create: `docs/verification/2026-11-14-sector-rotation-data-feasibility.md`
- Modify: `tools/market_dashboard/sources.py`
- Modify: `tools/market_dashboard/tests/test_sources.py`

**Interfaces:**
- Produces: `collect_index_history(runner, windcode: str, begin_date: str, end_date: str, period: str = "1d") -> list[dict]`
- Produces: `summarize_rotation_capability(batches: dict[str, SourceBatch], histories: dict[str, list[dict]], requested_at: datetime) -> dict`
- Produces CLI: `python3 -m tools.market_dashboard.rotation_probe --scope sample|full --metadata-only`

- [ ] **Step 1: Write failing history-adapter tests**

Add tests that assert `get_index_kline` receives exactly one verified Wind code plus explicit `begin_date`, `end_date`, `period="1d"`; malformed dates, wrong identity, duplicate dates, non-finite OHLC, future dates and raw provider errors return a safe `SourceError`. Confirm raw rows are never printed or persisted.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `python3 -m unittest tools.market_dashboard.tests.test_rotation_probe tools.market_dashboard.tests.test_sources -v`  
Expected: FAIL because the history adapter and probe do not exist.

- [ ] **Step 3: Implement the safe historical adapter and metadata probe**

Use Wind `index_data.get_index_kline` for daily point history and the existing batched `get_index_price_indicators` collectors for current fields. The probe records only group counts, identity coverage, earliest/latest dates, field coverage, unit sets, source timestamps, request duration and safe error codes. Sample mode uses six industries and six concepts spread across size/activity profiles; full mode checks all 35/75 current identities and estimates historical call cost before attempting full backfill.

- [ ] **Step 4: Add field-availability assertions**

Verify current batches expose 1/5/20-day returns, amount, turnover, 1/5/20-day main flow, up/down/flat counts and timestamps. Separately report which of price, flow and breadth can be reconstructed historically; do not equate current rolling fields with dated historical observations.

- [ ] **Step 5: Run the live sample probe without production writes**

Run the probe from the installed Wind environment with `--scope sample --metadata-only`. Expected: no payload values or credentials printed; the report states latency, coverage and exact history limits. If auth, quota or runtime fails, follow the provider's safe error action and stop this task without changing score code.

- [ ] **Step 6: Write the feasibility report and gate Task 2**

Record whether price, flow and breadth support 20/60/250 closes, whether the 110-object current universe fits quota, and which components must begin as forward-collected history. Mark every claim verified, unavailable or still to confirm. Task 2 may proceed with missing historical components, but Task 4 must withhold public opportunity output until the spec gates pass.

- [ ] **Step 7: Run focused regressions and commit**

Run:

```bash
python3 -m unittest tools.market_dashboard.tests.test_rotation_probe tools.market_dashboard.tests.test_sources -v
git diff --check
```

Expected: PASS and no secret/raw data in tracked files.

Commit: `feat: probe sector rotation data feasibility`

### Task 2: Pure sector scoring and heat-state engine

**Files:**
- Create: `tools/market_dashboard/rotation.py`
- Create: `tools/market_dashboard/fixtures/rotation-history.json`
- Create: `tools/market_dashboard/tests/test_rotation.py`
- Modify: `config/market-dashboard.json`
- Modify: `tools/market_dashboard/scoring.py`

**Interfaces:**
- Produces: `position_curve(percentile: float | None) -> float | None`
- Produces: `derive_sector_components(current: dict, prior_closes: list[dict], universe_current: list[dict], config: dict) -> dict`
- Produces: `score_sector(current: dict, prior_closes: list[dict], universe_current: list[dict], config: dict) -> dict`
- Produces: `rank_sector_scores(rows: list[dict], axis: str) -> list[dict]`
- Produces: `classify_heat(components: dict, config: dict) -> str | None`
- Produces: `derive_current_views(rows: list[dict], config: dict) -> dict[str, list[dict]]`

- [ ] **Step 1: Write failing normalization and position tests**

Pin 5/95 winsorization, midpoint ties, reverse indicators, no-current-day baseline, the position curve (`<10 => 0`, `10..35 => 0..100`, `35..70 => 100..0`, `>=70 => 0`) and missing 250-day history reducing completeness rather than being filled.

- [ ] **Step 2: Write failing atomic-component tests**

Assert every formula in spec section 5.6: 1/5/20 price weights, net-flow ratios and weights, breadth denominator, five-close persistence, 20-day relative-strength series, funds/breadth/momentum improvement, activity warming and all five risk components. Include zero denominators, missing periods, short history and extreme-but-finite values.

- [ ] **Step 3: Write failing score, gate and heat tests**

Assert exact top-level weights; high opportunity requires two improvement components at 60; fewer than two caps the score at 69; fewer than 20 closes or completeness below 70 yields `opportunity=None`; heat thresholds produce cold/warming/active/crowded with crowded priority; risk never subtracts from strength/opportunity.

- [ ] **Step 4: Write failing ranking/view tests**

Pin unrounded-score ordering, completeness/ID tie-breaks and exact predicates/sorts for potential rotation, confirmed mainline and rising risk. Test one object appearing in multiple applicable views without a composite score.

- [ ] **Step 5: Run focused tests and confirm failure**

Run: `python3 -m unittest tools.market_dashboard.tests.test_rotation -v`  
Expected: FAIL because the rotation engine and v0.2 config do not exist.

- [ ] **Step 6: Add versioned configuration and implement pure functions**

Add `sectorScoringVersion`, `sectorUniverseVersion`, component weights, heat thresholds, evidence gates and view predicates to JSON. Keep existing global/A-share/style families unchanged. Implement the interfaces without provider I/O, filesystem writes or mutable globals; preserve raw floating scores privately and expose rounded integers plus normalized component audit fields.

- [ ] **Step 7: Pass pure tests and existing score regressions**

Run:

```bash
python3 -m unittest tools.market_dashboard.tests.test_rotation tools.market_dashboard.tests.test_scoring tools.market_dashboard.tests.test_concepts -v
```

Expected: PASS; existing global/A-share/style fixture scores are unchanged.

- [ ] **Step 8: Commit**

Commit: `feat: add sector opportunity scoring engine`

### Task 3: Derived history, backfill and leaderboard continuity

**Files:**
- Create: `tools/market_dashboard/rotation_store.py`
- Create: `tools/market_dashboard/tests/test_rotation_store.py`
- Modify: `tools/market_dashboard/job.py`
- Modify: `tools/market_dashboard/tests/test_job.py`

**Interfaces:**
- Produces: `load_rotation_state(path: Path, config: dict) -> dict`
- Produces: `append_rotation_close(state: dict, payload: dict, config: dict) -> dict`
- Produces: `leaderboard_stats(closes: list[dict], universe: str, axis: str, sector_id: str) -> dict`
- Produces: `build_price_backfill(histories: dict[str, list[dict]], universe_version: str) -> list[dict]`

- [ ] **Step 1: Write failing state isolation tests**

Assert v2 payloads never become v3 comparisons, wrong scoring/universe versions are skipped, malformed derived components reject the state, only validated derived rows persist and local recovery history is trimmed to 90 calendar days.

- [ ] **Step 2: Write failing leaderboard tests**

Assert only official close top 10 advances strength/opportunity streaks; intraday/risk views do not; holidays do not break trading-day continuity; rank change compares the previous valid close; near-15-day count uses exactly the previous 15 official closes and names its axis.

- [ ] **Step 3: Write failing backfill tests**

Assert price backfill is identity/version checked, sorted and deduplicated; missing historical flow/breadth stays absent; no current rolling flow value is copied backward; fewer than 20 valid closes withholds opportunity.

- [ ] **Step 4: Implement atomic private state**

Use same-directory temporary files, `fsync`, mode 0600 and symlink rejection consistent with the existing job. Store only derived price history, normalized components, ranks, heat state, missing reasons, versions and safe provenance.

- [ ] **Step 5: Integrate leaderboard history into sector inputs**

At an official close, compute rankings from the full 35/75 universe, append once per successful close bucket and derive axis-specific streak/count/rank-change fields. Failed collection, validation or publication does not advance local history.

- [ ] **Step 6: Run focused and job regressions**

Run:

```bash
python3 -m unittest tools.market_dashboard.tests.test_rotation_store tools.market_dashboard.tests.test_job -v
```

Expected: PASS including duplicate bucket, lock and failure-state preservation tests.

- [ ] **Step 7: Commit**

Commit: `feat: persist derived sector rotation history`

### Task 4: Shadow scheduler and `market-dashboard-v3` local payload

**Files:**
- Modify: `config/market-dashboard.json`
- Modify: `tools/market_dashboard/job.py`
- Modify: `tools/market_dashboard/tests/test_job.py`
- Modify: `tools/market_dashboard/tests/test_operations.py`
- Modify: `ops/macos/run-market-dashboard.sh`
- Modify: `README.md`

**Interfaces:**
- Produces: `scheduled_rotation_session(now: datetime, state: dict, config: dict) -> str | None`
- Produces: `build_rotation_block(batches: dict, prior_closes: list[dict], config: dict) -> dict`
- Produces CLI flags: `--rotation-shadow`, `--rotation-report`, `--skip-rotation-publish`
- Produces payload: `market-dashboard-v3` with legacy global/A-share/style axes and sector `strength/opportunity/risk/heatState` rows.

- [ ] **Step 1: Write failing schedule tests**

Pin Beijing windows 09:45–09:55, 11:30–11:40, 14:00–14:10 and close catch-up 15:00–15:30; missed intraday windows do not backfill; close requires every Wind sector batch timestamp at or after 15:00; a successful close cannot advance twice.

- [ ] **Step 2: Write failing mixed-axis v3 payload tests**

Assert global/A-share/styles retain heat, while all 35 industries and all 75 rotation concepts use opportunity plus heatState and derived audit components. Require exact identities, versions, completeness gates, no forbidden raw keys and total body `<=256 KiB`.

- [ ] **Step 3: Write failing shadow-safety tests**

Assert shadow mode collects/scores and writes private shadow state/health but never calls the production publisher or changes v2 success state. `--rotation-report` prints only counts, versions, coverage, latency and safe codes.

- [ ] **Step 4: Implement v3 assembly and scheduler**

Keep the existing five-minute LaunchAgent interval. The job decides whether a rotation key window is open, scores the full universe, emits visible core/dynamic concept subsets plus a full normalized sectorRotation block and isolates v3 history. Shadow state lives under `state/market-dashboard-shadow/` and logs remain private.

- [ ] **Step 5: Update operator docs and wrapper tests**

Document that the LaunchAgent remains loaded, shadow mode is reversible, v2 production stays active during validation and no test/fixture payload may be published.

- [ ] **Step 6: Run Python regression suite**

Run: `python3 -m unittest discover -s tools/market_dashboard/tests -v`  
Expected: PASS.

- [ ] **Step 7: Commit**

Commit: `feat: generate sector rotation v3 snapshots in shadow`

### Task 5: D1 migration, atomic publication and rotation APIs

**Files:**
- Create: `migrations/0002_sector_rotation.sql`
- Create: `functions/api/sector-rotation/latest.js`
- Create: `functions/api/sector-rotation/history.js`
- Create: `functions/api/sector-rotation/detail.js`
- Modify: `functions/_lib/market-dashboard.js`
- Modify: `functions/api/market-dashboard/publish.js`
- Modify: `functions/api/market-dashboard/latest.js`
- Modify: `functions/api/market-dashboard/history.js`
- Modify: `tests/market-dashboard-functions.test.mjs`
- Create: `tests/sector-rotation-functions.test.mjs`

**Interfaces:**
- Produces D1 table: `sector_rotation_snapshots`
- Produces GET: `/api/sector-rotation/latest?universe=industry|concept&view=potential|main|risk`
- Produces GET: `/api/sector-rotation/history?universe=industry|concept&axis=strength|opportunity&days=15`
- Produces GET: `/api/sector-rotation/detail?universe=industry|concept&id=<verified-id>&days=60`

- [ ] **Step 1: Write failing migration tests**

Assert the table primary key is `(observed_at, universe, sector_id, scoring_version)`, accepted universes are industry/concept, axes and heat states are constrained, audit JSON columns are non-null, and indexes cover latest, market-date/universe and each rank query.

- [ ] **Step 2: Write failing server-validation tests**

Pin `market-dashboard-v3`, mixed legacy/sector axes, exact 35/75 identities, heat-state enum, normalized components, source timestamps, missing reasons, rank bounds, official-close flags, versions and the 256 KiB body limit. Reject raw provider-looking keys, duplicate IDs, NaN and future observations.

- [ ] **Step 3: Write failing transaction tests**

Mock D1 batch/transaction behavior and assert dashboard plus all 110 sector rows succeed together; any invalid/failed row yields no visible v3 latest. Repeating the same observation is idempotent.

- [ ] **Step 4: Write failing API tests**

Cover enum/query validation, default limits, v3-only filtering, deterministic order, 15-close matrix, compact list responses and detail audit fields. Assert no raw provider fields, source bodies, credentials or local paths appear.

- [ ] **Step 5: Implement migration, validators and APIs**

Store rounded public scores, unrounded rank keys, ranks, heat state, completeness and compact derived audit JSON. `latest/history` list endpoints stay compact; `detail` returns contributors, components, missing reasons, heat evidence, safe provenance and versions.

- [ ] **Step 6: Add retention without deleting audit versions**

After a successful insert, prune intraday derived rows older than 90 calendar days and retain official closes for at least 250 trading dates per scoring/universe version. Never delete v2 market snapshots or old scoring-version closes as part of routine publication.

- [ ] **Step 7: Run Node Functions tests**

Run:

```bash
node --test tests/market-dashboard-functions.test.mjs tests/sector-rotation-functions.test.mjs
```

Expected: PASS.

- [ ] **Step 8: Commit**

Commit: `feat: store and serve sector rotation history`

### Task 6: Browser contracts and presentation model

**Files:**
- Modify: `src/features/market-dashboard/types.ts`
- Modify: `src/features/market-dashboard/api.mjs`
- Modify: `src/features/market-dashboard/api.d.mts`
- Modify: `src/features/market-dashboard/model.mjs`
- Modify: `src/features/market-dashboard/model.d.mts`
- Modify: `tests/market-dashboard-api.test.mjs`
- Modify: `tests/market-dashboard-model.test.mjs`
- Create: `tests/sector-rotation-model.test.mjs`

**Interfaces:**
- Produces types: `LegacyMarketScores`, `SectorScores`, `SectorHeatState`, `SectorRotationRow`, `SectorRotationHistory`, `SectorRotationDetail`
- Produces: `loadSectorRotationLatest(options)`, `loadSectorRotationHistory(options)`, `loadSectorRotationDetail(options)`
- Produces: `deriveSectorRotationView(latest, history, options) -> SectorRotationView`

- [ ] **Step 1: Write failing v3 loader tests**

Assert global/A-share/styles require heat and reject opportunity, while industries/concepts require opportunity/heatState and reject public heat. Validate exact identities, audit fields, versions, ranks and request enums. Preserve structured timeout/network/schema errors.

- [ ] **Step 2: Write failing rotation-model tests**

Pin view membership/sorting, leaderboard labels, axis-specific streaks, cold-start and evidence labels, 15-date matrix construction, missing-day handling, stale/close status and safe detail presentation.

- [ ] **Step 3: Implement split types and strict loaders**

Do not weaken the existing fail-closed style. Keep v2 loader support only for the production fallback path during shadow; v3 components render only after the v3 contract succeeds.

- [ ] **Step 4: Implement the pure view model**

Return potential/main/risk lists, daily matrix cells, labels and detail series without mutating API input. Do not calculate or expose a composite score.

- [ ] **Step 5: Run model/API tests**

Run:

```bash
node --test tests/market-dashboard-api.test.mjs tests/market-dashboard-model.test.mjs tests/sector-rotation-model.test.mjs
```

Expected: PASS.

- [ ] **Step 6: Commit**

Commit: `feat: model sector opportunity and rotation views`

### Task 7: Mobile-first rotation UI and sector detail

**Files:**
- Create: `src/components/SectorRotationBoard.vue`
- Create: `src/components/SectorRotationDetail.vue`
- Modify: `src/components/MarketResearchDashboard.vue`
- Modify: `src/components/IndustryHeatmap.vue`
- Modify: `src/components/ConceptRadar.vue`
- Modify: `src/components/MarketScoreCard.vue`
- Modify: `src/style.css`
- Modify: `tests/market-dashboard-components.test.mjs`
- Create: `tests/sector-rotation-components.test.mjs`

**Interfaces:**
- Consumes: Task 6 `SectorRotationView` and detail result.
- Produces props: `SectorRotationBoard<{ latest, history, initialUniverse?, initialView? }>`
- Emits: `select-sector` with `{ universe, id }` for detail loading.

- [ ] **Step 1: Write failing component tests**

Assert industry/concept tabs, potential/main/risk views, strength/opportunity matrix toggle, exact three-score labels, heat tags, rank changes, close-only streak wording, cold-start/missing states and no hidden composite value.

- [ ] **Step 2: Write failing accessibility and responsive-source tests**

Pin tablist/tabpanel relationships, table/grid labels, keyboard-focusable cells, semantic buttons, detail dialog heading/close control and CSS hooks for 1440px and 390px layouts.

- [ ] **Step 3: Implement the board**

Default to concepts + potential rotation. Render current rows above a horizontally scrollable 15-close matrix; show only top 10 per close. Preserve color for price/state meaning and show all score numbers as text.

- [ ] **Step 4: Implement detail and update existing sector cards**

Replace sector heat score with opportunity and a heat-state badge in industry/concept cards. Keep global/A-share/style cards unchanged. Detail shows actual available closes up to 60, ranks, contributors, components, missing reasons, source time and version.

- [ ] **Step 5: Integrate behind a shadow feature flag**

Do not expose v3 UI on production by default. `MarketResearchDashboard.vue` renders the existing v2 page unless the verified v3 endpoint and release flag are both active.

- [ ] **Step 6: Run component and build tests**

Run:

```bash
node --test tests/market-dashboard-components.test.mjs tests/sector-rotation-components.test.mjs
npm test
npm run build
```

Expected: PASS.

- [ ] **Step 7: Perform real-browser visual QA**

Use the production build with fixture v3 APIs. Verify desktop 1440×900 and mobile 390×844 for all tabs, horizontal matrix scrolling, long Chinese names, missing data, detail open/close and no horizontal page overflow. Save screenshots in ignored SDD artifacts, not source control.

- [ ] **Step 8: Commit**

Commit: `feat: add sector rotation dashboard`

### Task 8: Operational health, shadow ledger and release evaluation

**Files:**
- Modify: `ops/macos/run-market-dashboard.sh`
- Modify: `docs/market-dashboard-operations.md`
- Create: `docs/verification/2026-11-14-sector-rotation-shadow.md`
- Modify: `tools/market_dashboard/tests/test_operations.py`
- Modify: `README.md`

**Interfaces:**
- Produces health fields: `rotationMode`, `rotationSession`, `rotationCoverage`, `rotationUniverseCounts`, `rotationLatencySeconds`, `rotationCloseSuccesses`, `rotationSafeErrorCode`
- Produces private ledger: parent-project `state/market-dashboard-shadow/rotation-ledger.json`

- [ ] **Step 1: Write failing health/ledger tests**

Assert health exposes only safe counts/timestamps/codes, ledger updates atomically, unsuccessful closes do not count, ten-day evaluation uses distinct official market dates and v2 service state remains untouched.

- [ ] **Step 2: Implement reversible shadow operation**

Add the shadow flag to the stable LaunchAgent invocation only after local validation. Keep the same service label and interval; disabling shadow requires one config/env change and does not stop v2 production updates.

- [ ] **Step 3: Run the ten-trading-day shadow window**

For each day, record current identity coverage, median completeness, close source time/latency, publication skipped status, safe failures and opportunity-list churn. Do not report predictive validity from the ten-day run alone.

- [ ] **Step 4: Run historical diagnostics**

Using only information available as of each close, report future 1/3/5-day rank correlation, high-vs-low group spread, hit rate, maximum drawdown and list turnover separately for industries and concepts. Include all valid dates and state whether a single date/sector dominates.

- [ ] **Step 5: Evaluate the approved release gates**

Require 35/35 industries, at least 95% of 75 concepts, median completeness at least 80, candidate completeness at least 70, at least 9/10 successful closes, no identity/unit/future-time errors and positive non-dominated 3-day or 5-day high-vs-low opportunity spread. If any gate fails, leave production on v2 and document the failed gate; do not tune inside the same version.

- [ ] **Step 6: Run final full verification**

Run:

```bash
python3 -m unittest discover -s tools/market_dashboard/tests -v
npm test
npm run build
git diff --check
```

Expected: all pass. Verify the generated `dist`, latest/history/detail fixtures and representative desktop/mobile renders.

- [ ] **Step 7: Ask for production-switch approval**

Present the shadow and historical verification record. Production migration, v3 publication and feature-flag activation are external side effects and require explicit user approval after the evidence is available.

- [ ] **Step 8: Commit**

Commit: `docs: verify sector rotation shadow release`

### Task 9: Production migration, v3 publication and post-release verification

**Files:**
- Modify only if verification finds a release-specific defect; otherwise no source changes.
- Update: `docs/verification/2026-11-14-sector-rotation-shadow.md`
- Update: `docs/market-dashboard-operations.md`

**Interfaces:**
- Consumes: explicit Task 8 production approval.
- Produces: applied D1 migration, first real v3 close, enabled v3 UI and verified public APIs.

- [ ] **Step 1: Reconfirm clean, tested release target**

Verify stable `main` matches the reviewed tree, worktrees are clean, build assets are current, Wrangler targets project `newsmonitor` and binding `MARKET_DB`, and no secret values will enter arguments or logs.

- [ ] **Step 2: Apply the reviewed D1 migration**

Apply only `0002_sector_rotation.sql` to the existing `newsmonitor-market-dashboard` database. Do not create another database or delete v2 rows. Verify table/index names and schema read-only after migration.

- [ ] **Step 3: Deploy v3 code with the UI flag still off**

Deploy Pages Functions and assets to the production branch. Verify v2 latest/news/debt remain healthy and unauthenticated/invalid v3 publication is rejected.

- [ ] **Step 4: Publish the first real v3 close**

Use the existing authenticated local wrapper and an official validated close; fixtures and backdated synthetic values remain prohibited. Confirm one dashboard row plus 110 sector rows commit atomically.

- [ ] **Step 5: Enable the v3 UI and verify production**

Verify homepage load, three current views, industry/concept switch, strength/opportunity 15-close matrix, detail endpoint, mobile layout, source wording, v3 versions and no news/debt regression.

- [ ] **Step 6: Update operations and verification evidence**

Record deployment ID, first v3 observed time, counts, completeness, API summaries, visual QA and rollback boundary. Remove temporary diagnostics and keep credentials/private raw data out of the report.

- [ ] **Step 7: Merge and push the reviewed release**

Fast-forward or merge without rewriting history, run final status checks and push `main` only after production verification passes.

