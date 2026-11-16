# Hithink Sector Data Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the sector-rotation module's Wind identities and inputs with a versioned Hithink industry/concept history and 15-minute real-time pipeline while preserving v3 as a complete rollback.

**Architecture:** Hithink official sector indexes are the authoritative price/turnover series; Hithink memberships plus the existing local A-share database supply reproducible breadth and participation features. A private SQLite feature store feeds `market-dashboard-v4`/`sector-score-v0.3`; Cloudflare receives chunked derived rows behind an atomic manifest, and the UI switches only after one natural trading-day acceptance run.

**Tech Stack:** Python 3.13 standard library (`sqlite3`, `subprocess`, `zoneinfo`, `unittest`), Hithink Finance CLI 0.2.4, Node 22, Cloudflare Pages Functions/D1, Vue 3/TypeScript/Vite.

**Spec:** `docs/superpowers/specs/2026-11-16-hithink-sector-data-migration-design.md`

## Global Constraints

- Use `Asia/Shanghai` for provider timestamps, schedule buckets and market dates; never truncate Hithink `date_ms` as UTC.
- Use SQLite at `data/market-dashboard/sector-history.sqlite3`; keep the provider-managed `data/hithink/market.duckdb` read-only through the official CLI.
- New versions are exactly `market-dashboard-v4`, `sector-score-v0.3`, `sector-universe-ths-v1`, `sector-features-ths-v1`, and `sector-membership-ths-v1`.
- Industry universe is the 90 `881xxx.TI` primary industries; concept universe is the complete qualified Hithink concept catalog.
- Preserve the fixed 25 core concepts and dynamic 10 concepts; homepage industry presentation is three ranked lists of 10, with the full universe in a searchable detail view.
- Probe budget is at most 50 remote calls and, when usage is reported, 100 points. Stop after the probe if full work is estimated above 500 calls or 100 points.
- Do not publish v4 until provider authorization for locally retained normalized features and publicly displayed derived scores is recorded.
- Do not store credentials, raw provider envelopes, constituent rows or local paths in Git, D1, public payloads or ordinary logs.
- v3/Wind state, D1 rows and UI remain intact until v4 cutover; rollback changes version switches only and deletes nothing.
- Historical current-member backfills are labeled `current_members_backfill`; strict forward snapshots are `point_in_time_snapshot`.
- Individual-stock historical returns use forward-adjusted closes. Suspended, missing, insufficient-history and delisted observations stay out of breadth denominators and reduce coverage.
- Every task uses tests-first development and leaves the branch independently reviewable.

## Review Focus

- Hithink midnight timestamps that appear on the prior UTC date must resolve to the correct Shanghai trading date; Task 1 pins this with Monday/Friday and DST-independent tests.
- A successful empty `index history-batch` must not be accepted when single-index history exists; Tasks 1 and 5 pin fallback and failure semantics.
- Missing/suspended constituents must not count as declining stocks or zero return; Task 6 pins denominators and coverage.
- Partially uploaded v4 chunks must never become public latest/history data; Tasks 9 and 10 pin manifest activation and read isolation.
- Backfill work must yield to a 15-minute live bucket and stop at call/point caps; Tasks 3 and 8 pin budget exhaustion and single-write-lock preemption.

---

### Task 1: Strict Hithink sector adapter and Shanghai time contract

**Files:**
- Create: `tools/market_dashboard/hithink_cli.py`
- Create: `tools/market_dashboard/tests/test_hithink_cli.py`
- Create: `tools/market_dashboard/fixtures/hithink/`
- Modify: `tools/market_dashboard/hithink_history.py`

**Interfaces:**
- Consumes: an injectable `runner(argv: list[str]) -> CompletedProcessLike` and the existing official CLI path.
- Produces: `SectorDefinition`, `IndexDailyBar`, `IndexSnapshot`, `StockSnapshot`, `Membership`; `shanghai_market_date(date_ms: int) -> str`; `HithinkClient.catalog(tag)`, `.constituents(code)`, `.index_history(code, start_ms, end_ms)`, `.index_snapshots(codes)`, `.stock_snapshots(codes)`.

- [ ] **Step 1: Write failing adapter tests**

Add tests for exact schema acceptance, unknown/missing fields, duplicate identities, non-finite numbers, Monday Shanghai midnight resolving to Monday rather than Sunday UTC, and `history-batch` empty while single history has rows raising `HISTORY_BATCH_INCOMPLETE`.

- [ ] **Step 2: Verify the tests fail**

Run: `python3 -m unittest tools.market_dashboard.tests.test_hithink_cli -v`

Expected: FAIL because `hithink_cli` does not exist.

- [ ] **Step 3: Implement the minimal strict adapter**

Use `subprocess.run` without a shell, accept only documented CLI envelopes, normalize to frozen dataclasses, convert `date_ms` via `datetime.fromtimestamp(..., SHANGHAI).date()`, and expose only stable safe error codes. Extend `hithink_history.py` to reuse the date and numeric validators rather than duplicate them.

- [ ] **Step 4: Run adapter and existing history tests**

Run: `python3 -m unittest tools.market_dashboard.tests.test_hithink_cli tools.market_dashboard.tests.test_hithink_history -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add tools/market_dashboard/hithink_cli.py tools/market_dashboard/hithink_history.py tools/market_dashboard/tests/test_hithink_cli.py tools/market_dashboard/fixtures/hithink && git commit -m "feat: add strict hithink sector adapter"`

### Task 2: Private SQLite sector feature store

**Files:**
- Create: `tools/market_dashboard/hithink_store.py`
- Create: `tools/market_dashboard/sqlite/0001_hithink_sector_history.sql`
- Create: `tools/market_dashboard/tests/test_hithink_store.py`

**Interfaces:**
- Consumes: Task 1 dataclasses.
- Produces: `open_store(path: Path) -> sqlite3.Connection`, `migrate_store(connection)`, `store_write_lock(state_root: Path)`, `replace_catalog(...)`, `upsert_memberships(...)`, `upsert_index_daily(...)`, `upsert_sector_features(...)`, and bounded read methods used by later tasks.

- [ ] **Step 1: Write failing migration and transaction tests**

Test all nine spec tables, foreign keys, unique primary keys, WAL mode, idempotent migrations, atomic catalog replacement, rollback on a bad row, symlink rejection, and one writer lock shared by live/backfill code.

- [ ] **Step 2: Verify the tests fail**

Run: `python3 -m unittest tools.market_dashboard.tests.test_hithink_store -v`

Expected: FAIL because the store module and migration do not exist.

- [ ] **Step 3: Implement schema and store methods**

Store normalized scalar columns plus version/provenance metadata. Do not add a raw JSON response column. Set `journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout`, private file modes and explicit transactions.

- [ ] **Step 4: Run store tests**

Run: `python3 -m unittest tools.market_dashboard.tests.test_hithink_store -v`

Expected: PASS and no files outside test temporary directories.

- [ ] **Step 5: Commit**

Run: `git add tools/market_dashboard/hithink_store.py tools/market_dashboard/sqlite/0001_hithink_sector_history.sql tools/market_dashboard/tests/test_hithink_store.py && git commit -m "feat: add private sector feature store"`

### Task 3: Capability, cost and authorization probe gate

**Files:**
- Create: `tools/market_dashboard/hithink_probe.py`
- Create: `tools/market_dashboard/tests/test_hithink_probe.py`
- Create: `config/hithink-sector-dashboard.json`
- Modify: `docs/market-dashboard-operations.md`

**Interfaces:**
- Consumes: Task 1 client and Task 2 store.
- Produces: `ProbeBudget(max_calls=50, max_points=100)`, `run_probe(client, config, budget) -> ProbeReport`, `estimate_full_run(report) -> CostEstimate`, and CLI-safe JSON containing counts, elapsed time, coverage, estimated calls/points, batch support and authorization status.

- [ ] **Step 1: Write failing budget-gate tests**

Test 50-call exhaustion, reported-point exhaustion, absent point metadata, 10-industry/20-concept sample size, full-market snapshot paging, 100-row paging rejection, history-batch empty detection, and an authorization state other than `verified` blocking public-release eligibility.

- [ ] **Step 2: Verify the tests fail**

Run: `python3 -m unittest tools.market_dashboard.tests.test_hithink_probe -v`

Expected: FAIL because the probe does not exist.

- [ ] **Step 3: Implement probe and versioned configuration**

Set exact caps from Global Constraints. The probe may write its safe report under private state but must not create the production feature DB, publish data, alter schedule state or exceed budget. Add an operations command that reports only the safe summary.

- [ ] **Step 4: Run tests, then the authorized live probe once**

Run tests first: `python3 -m unittest tools.market_dashboard.tests.test_hithink_probe -v`

Then run the wrapper's documented `--hithink-probe` command once. Expected live result: a safe report with actual calls, elapsed time, coverage and a deterministic `continueAutomatically` boolean. If estimated full work exceeds 500 calls or 100 points, stop the plan here and report to the user.

- [ ] **Step 5: Commit probe code and the redacted verification summary**

Run: `git add config/hithink-sector-dashboard.json tools/market_dashboard/hithink_probe.py tools/market_dashboard/tests/test_hithink_probe.py docs/market-dashboard-operations.md docs/verification && git commit -m "feat: gate hithink migration by cost probe"`

### Task 4: Versioned Hithink industry and concept universe

**Files:**
- Create: `tools/market_dashboard/hithink_universe.py`
- Create: `tools/market_dashboard/tests/test_hithink_universe.py`
- Create: `config/hithink-core-concepts.json`
- Create: `tools/market_dashboard/fixtures/hithink/catalog-industry.json`
- Create: `tools/market_dashboard/fixtures/hithink/catalog-concept.json`

**Interfaces:**
- Consumes: Task 1 catalog rows and probe-approved remote access.
- Produces: `build_universe(industry_rows, concept_rows, core_config) -> SectorUniverse`, exactly 90 primary industries, the qualified concept set, and exactly 25 unique core Hithink concepts.

- [ ] **Step 1: Write failing universe tests**

Assert `881xxx.TI` selection yields exactly 90 on the versioned fixture, `884xxx.TI` subindustries are excluded, duplicate IDs/names fail, all 25 core IDs exist in the concept catalog, and catalog additions/removals produce a deterministic diff instead of silently changing the universe version.

- [ ] **Step 2: Verify the tests fail**

Run: `python3 -m unittest tools.market_dashboard.tests.test_hithink_universe -v`

Expected: FAIL because the universe and core mapping do not exist.

- [ ] **Step 3: Implement universe selection and rebuild the fixed core pool**

Map the existing 25 research intents to Hithink concept IDs. Any intent without one defensible Hithink concept remains an explicit unresolved mapping and fails the 25-core gate; do not substitute by fuzzy name alone.

- [ ] **Step 4: Run universe tests and emit a safe diff report**

Run: `python3 -m unittest tools.market_dashboard.tests.test_hithink_universe -v`

Expected: PASS with 90 industries, 25 core concepts and deterministic concept count.

- [ ] **Step 5: Commit**

Run: `git add config/hithink-core-concepts.json tools/market_dashboard/hithink_universe.py tools/market_dashboard/tests/test_hithink_universe.py tools/market_dashboard/fixtures/hithink && git commit -m "feat: define hithink sector universe"`

### Task 5: Resumable sector index history backfill

**Files:**
- Create: `tools/market_dashboard/hithink_backfill.py`
- Create: `tools/market_dashboard/tests/test_hithink_backfill.py`
- Modify: `tools/market_dashboard/hithink_store.py`
- Modify: `ops/macos/run-market-dashboard.sh`

**Interfaces:**
- Consumes: Task 1 client, Task 2 store, Task 3 budget gate and Task 4 universe.
- Produces: `backfill_index_history(client, store, universe, window, budget) -> BackfillReport`, resumable checkpoints and `--hithink-backfill-indexes` wrapper mode.

- [ ] **Step 1: Write failing backfill tests**

Test Shanghai dates, duplicate reruns, partial failure/resume, batch-empty-to-single fallback, 20/60/250 coverage flags, budget stop before the next call, write-lock release between batches and no mutation of v2/v3 state.

- [ ] **Step 2: Verify the tests fail**

Run: `python3 -m unittest tools.market_dashboard.tests.test_hithink_backfill -v`

Expected: FAIL because backfill support does not exist.

- [ ] **Step 3: Implement bounded backfill**

Use single-index history until the batch path passes its gate. Commit small transactions, record checkpoints in `ingest_runs`, and calculate no scores in this task.

- [ ] **Step 4: Run tests and approved full backfill**

Run tests, then only if Task 3 says `continueAutomatically=true`, run the full index backfill. Verify 90/90 industries and every qualified concept has a deterministic coverage record.

- [ ] **Step 5: Commit code and safe coverage report**

Run: `git add tools/market_dashboard/hithink_backfill.py tools/market_dashboard/hithink_store.py tools/market_dashboard/tests/test_hithink_backfill.py ops/macos/run-market-dashboard.sh docs/verification && git commit -m "feat: backfill hithink sector index history"`

### Task 6: Membership snapshots and reproducible breadth history

**Files:**
- Create: `tools/market_dashboard/hithink_breadth.py`
- Create: `tools/market_dashboard/tests/test_hithink_breadth.py`
- Modify: `tools/market_dashboard/hithink_backfill.py`
- Modify: `tools/market_dashboard/hithink_store.py`

**Interfaces:**
- Consumes: Task 1 memberships, Task 2 store, Task 4 universe and read-only forward-adjusted stock closes through the existing official CLI boundary.
- Produces: `derive_daily_breadth(membership, closes) -> BreadthRow`, membership refresh schedules and persisted `current_members_backfill`/`point_in_time_snapshot` rows.

- [ ] **Step 1: Write failing breadth tests**

Cover advancing/declining/flat counts, median return, strong diffusion, amount concentration, missing/suspended/newly listed/delisted stocks, one stock belonging to many concepts, forward-adjusted inputs only, and coverage discounts for current-member history.

- [ ] **Step 2: Verify the tests fail**

Run: `python3 -m unittest tools.market_dashboard.tests.test_hithink_breadth -v`

Expected: FAIL because breadth derivation does not exist.

- [ ] **Step 3: Implement one-pass stock panel aggregation**

Read each requested stock/date once, then join locally to memberships. Refresh 90 industry memberships daily, core/dynamic/candidate-50 concepts daily and the full concept universe weekly or on catalog diff.

- [ ] **Step 4: Run tests and a representative backfill**

Run: `python3 -m unittest tools.market_dashboard.tests.test_hithink_breadth tools.market_dashboard.tests.test_hithink_backfill -v`

Expected: PASS; representative industry and concept reports disclose valid/total membership and mode.

- [ ] **Step 5: Commit**

Run: `git add tools/market_dashboard/hithink_breadth.py tools/market_dashboard/hithink_backfill.py tools/market_dashboard/hithink_store.py tools/market_dashboard/tests/test_hithink_breadth.py && git commit -m "feat: derive hithink sector breadth history"`

### Task 7: `sector-score-v0.3` feature and replay engine

**Files:**
- Create: `tools/market_dashboard/rotation_v4.py`
- Create: `tools/market_dashboard/tests/test_rotation_v4.py`
- Modify: `config/hithink-sector-dashboard.json`
- Modify: `tools/market_dashboard/rotation_evaluation.py`
- Modify: `tools/market_dashboard/tests/test_rotation_evaluation.py`

**Interfaces:**
- Consumes: Task 2 daily index/breadth rows.
- Produces: `build_v4_features(...) -> FeatureRow`, `score_v4_sector(...) -> V4SectorScore`, `rank_v4_universe(...)`, top-decile continuity and replay datasets for evaluation.

- [ ] **Step 1: Write failing scoring tests**

Pin every axis/subweight from the spec, strict sum-to-100 validation, opportunity's two-independent-improvement gate, 60/250-day position behavior, top-decile persistence for 90 and 390 members, approximation discounts, missing propagation and deterministic ranks.

- [ ] **Step 2: Verify the tests fail**

Run: `python3 -m unittest tools.market_dashboard.tests.test_rotation_v4 -v`

Expected: FAIL because v4 scoring does not exist.

- [ ] **Step 3: Implement pure feature and score functions**

Keep functions independent of SQLite and provider calls. Replace flow components with participation/relative-turn/concentration exactly as specified; use `topDecile*` field names.

- [ ] **Step 4: Run scoring and replay evaluation tests**

Run: `python3 -m unittest tools.market_dashboard.tests.test_rotation_v4 tools.market_dashboard.tests.test_rotation_evaluation -v`

Expected: PASS; replay output separates strict PIT dates from approximate backfill dates.

- [ ] **Step 5: Commit**

Run: `git add config/hithink-sector-dashboard.json tools/market_dashboard/rotation_v4.py tools/market_dashboard/rotation_evaluation.py tools/market_dashboard/tests/test_rotation_v4.py tools/market_dashboard/tests/test_rotation_evaluation.py && git commit -m "feat: add hithink sector scoring v0.3"`

### Task 8: Fifteen-minute Hithink live producer

**Files:**
- Create: `tools/market_dashboard/hithink_job.py`
- Create: `tools/market_dashboard/tests/test_hithink_job.py`
- Modify: `ops/macos/run-market-dashboard.sh`
- Modify: `ops/macos/install-market-dashboard-service.sh`
- Modify: `docs/market-dashboard-operations.md`

**Interfaces:**
- Consumes: Tasks 1–7.
- Produces: `run_hithink_cycle(args, deps=None) -> HithinkJobResult`, 15-minute bucket state, safe health and a local v4 payload/chunk set without publishing unless explicitly enabled.

- [ ] **Step 1: Write failing scheduling and preemption tests**

Test Shanghai sessions, lunch/holiday/close behavior, one success per bucket, official close cutoff, catalog/membership refresh cadence, one stock snapshot reused across all sectors, 100-row paging rejection, budget stop, shared write lock and a waiting backfill yielding to a live cycle.

- [ ] **Step 2: Verify the tests fail**

Run: `python3 -m unittest tools.market_dashboard.tests.test_hithink_job -v`

Expected: FAIL because the v4 job does not exist.

- [ ] **Step 3: Implement shadow-only live cycle**

Write only private v4 state/SQLite and safe health. Do not alter v3 flags or publish settings. The producer must finish before the next bucket or mark the cycle failed without advancing state.

- [ ] **Step 4: Run tests and fixture shadow cycle**

Run: `python3 -m unittest tools.market_dashboard.tests.test_hithink_job tools.market_dashboard.tests.test_operations -v`

Expected: PASS; fixture mode writes no production files and live dry-run publishes nothing.

- [ ] **Step 5: Commit**

Run: `git add tools/market_dashboard/hithink_job.py tools/market_dashboard/tests/test_hithink_job.py ops/macos/run-market-dashboard.sh ops/macos/install-market-dashboard-service.sh docs/market-dashboard-operations.md && git commit -m "feat: run hithink sectors every fifteen minutes"`

### Task 9: Atomic chunked v4 D1 publication

**Files:**
- Create: `migrations/0003_hithink_sector_rotation_v4.sql`
- Create: `functions/_lib/sector-rotation-v4.js`
- Create: `functions/api/sector-rotation/v4/manifest.js`
- Create: `functions/api/sector-rotation/v4/chunk.js`
- Create: `functions/api/sector-rotation/v4/activate.js`
- Create: `tests/sector-rotation-v4-publish.test.mjs`
- Modify: `tools/market_dashboard/hithink_job.py`

**Interfaces:**
- Consumes: Task 8 local v4 sector rows.
- Produces: manifest/chunk/activate protocol, `build_publish_chunks(rows, max_rows=50, max_bytes=131072)`, and only activated v4 snapshots visible to readers.

- [ ] **Step 1: Write failing migration and publication tests**

Test rank limits through 390, unique batch/sector identities, payload limit, duplicate chunk idempotency, wrong checksum/count rejection, cross-version rejection, partial batch invisibility, activation atomicity and v3 table non-mutation.

- [ ] **Step 2: Verify the tests fail**

Run: `node --test tests/sector-rotation-v4-publish.test.mjs`

Expected: FAIL because migration and endpoints do not exist.

- [ ] **Step 3: Implement additive v4 tables and staged protocol**

Store manifest status separately from sector rows. Activation performs server-side count, uniqueness and digest checks in one request; readers filter `status='active'`. Provenance says `Hithink` and contains no membership rows.

- [ ] **Step 4: Run publication tests and local migration smoke test**

Run: `node --test tests/sector-rotation-v4-publish.test.mjs`

Expected: PASS, including a simulated interruption after any chunk.

- [ ] **Step 5: Commit**

Run: `git add migrations/0003_hithink_sector_rotation_v4.sql functions/_lib/sector-rotation-v4.js functions/api/sector-rotation/v4 tests/sector-rotation-v4-publish.test.mjs tools/market_dashboard/hithink_job.py && git commit -m "feat: publish sector v4 atomically"`

### Task 10: Versioned v4 read APIs and public projections

**Files:**
- Create: `functions/api/sector-rotation/v4/latest.js`
- Create: `functions/api/sector-rotation/v4/history.js`
- Create: `functions/api/sector-rotation/v4/detail.js`
- Create: `functions/api/sector-rotation/v4/catalog.js`
- Create: `tests/sector-rotation-v4-read.test.mjs`
- Modify: `functions/_lib/sector-rotation-v4.js`

**Interfaces:**
- Consumes: Task 9 active manifests and rows.
- Produces: paginated full-universe reads and compact homepage lists; no endpoint reads staging manifests.

- [ ] **Step 1: Write failing API tests**

Test three lists capped at 10, fixed core 25 + dynamic 10, pagination bounds, search/filter, prior-close changes, source/version disclosure, approximate membership disclosure, inactive/partial manifest isolation and absence of private fields.

- [ ] **Step 2: Verify the tests fail**

Run: `node --test tests/sector-rotation-v4-read.test.mjs`

Expected: FAIL because read endpoints do not exist.

- [ ] **Step 3: Implement strict queries and projections**

All queries bind the exact v4 scoring/universe versions. Return `NO_SNAPSHOT` until an active manifest exists; never fall back to v3 inside a v4 endpoint.

- [ ] **Step 4: Run v4 and existing Functions tests**

Run: `node --test tests/sector-rotation-v4-read.test.mjs tests/market-dashboard-functions.test.mjs tests/sector-rotation-functions.test.mjs`

Expected: PASS with v3 behavior unchanged.

- [ ] **Step 5: Commit**

Run: `git add functions/api/sector-rotation/v4 functions/_lib/sector-rotation-v4.js tests/sector-rotation-v4-read.test.mjs && git commit -m "feat: serve hithink sector v4 data"`

### Task 11: Hithink v4 homepage and full-universe UI

**Files:**
- Create: `src/features/sector-rotation-v4/api.mjs`
- Create: `src/features/sector-rotation-v4/model.mjs`
- Create: `src/features/sector-rotation-v4/types.ts`
- Create: `src/components/sector-rotation/HithinkSectorBoard.vue`
- Create: `src/views/HithinkSectorExplorerView.vue`
- Create: `tests/sector-rotation-v4-ui.test.mjs`
- Modify: `src/components/MarketResearchDashboard.vue`
- Modify: `src/router/index.ts`

**Interfaces:**
- Consumes: Task 10 public APIs.
- Produces: feature-flagged v4 homepage, three industry lists, core/dynamic concept tabs and searchable/paginated full-universe explorer.

- [ ] **Step 1: Write failing model/component tests**

Test v4 contract rejection, source/version labels, three lists of 10, core 25, dynamic 10, approximate-history warning, missing/stale states, pagination/search and v3 remaining visible when the v4 flag is off or returns `NO_SNAPSHOT`.

- [ ] **Step 2: Verify the tests fail**

Run: `node --test tests/sector-rotation-v4-ui.test.mjs`

Expected: FAIL because v4 frontend files do not exist.

- [ ] **Step 3: Implement isolated v4 adapter and UI**

Do not extend v3 types with optional v4 fields. The production flag selects one complete adapter; it must not merge v3 and v4 histories in the browser.

- [ ] **Step 4: Run UI tests and production build**

Run: `node --test tests/sector-rotation-v4-ui.test.mjs tests/market-dashboard-components.test.mjs && npm run build:production-rotation`

Expected: PASS; build contains no fixture or acceptance fallback.

- [ ] **Step 5: Commit**

Run: `git add src/features/sector-rotation-v4 src/components/sector-rotation/HithinkSectorBoard.vue src/views/HithinkSectorExplorerView.vue src/components/MarketResearchDashboard.vue src/router/index.ts tests/sector-rotation-v4-ui.test.mjs && git commit -m "feat: add hithink sector dashboard ui"`

### Task 12: Full verification, one-day shadow acceptance and reversible cutover

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/DATA_SOURCES.md`
- Modify: `docs/PROJECT_STRUCTURE.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/market-dashboard-operations.md`
- Create: `docs/verification/2026-11-xx-hithink-sector-v4.md`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: evidence-backed go/no-go record, disabled-by-default production flag, rollback exercise and final cutover only after user acceptance.

- [ ] **Step 1: Run complete offline verification**

Run: `python3 -m unittest discover -s tools/market_dashboard/tests`

Run: `npm test`

Run: `npm run build:production-rotation`

Expected: all pass; `git diff --check` is clean.

- [ ] **Step 2: Apply additive D1 migration and deploy v4 endpoints with the UI flag off**

Verify old v3 latest/history/detail responses before and after migration. Do not enable v4 producer publication until authorization is recorded and the deployment is healthy.

- [ ] **Step 3: Run one natural trading-day dual-track acceptance**

Record 09:45, 11:30, 14:00 and close; 15-minute bucket success; latency; calls/points; industry/concept/stock coverage; official-close reconciliation; score completeness; safe errors; and that v3 stayed available. Do not substitute forced runs for missing natural evidence.

- [ ] **Step 4: Exercise rollback, then request final user acceptance**

Turn the v4 flag on in preview, verify UI/API, turn it off, and verify v3 returns without deleting data. Present screenshots and the verification record; production cutover requires explicit final user acceptance.

- [ ] **Step 5: Cut over and commit final documentation**

After acceptance, enable v4 production reads and publication, disable Wind sector collection while retaining its configuration/state, then update all listed docs and commit with: `git commit -m "docs: complete hithink sector migration"`.

## Self-Review Record

- Spec coverage: all intent, universe, storage, membership bias, score weights, schedule, budget, authorization, chunk publication, UI, acceptance and rollback requirements map to Tasks 1–12.
- Step scan: each task has one test action, one implementation action, one verification action and one commit; live external actions are isolated behind Tasks 3 and 12 gates.
- Type consistency: Task 1 dataclasses feed Tasks 2/5/6; Task 2 rows feed Task 7; Task 8 produces Task 9 rows; Task 10 is the sole public contract consumed by Task 11.
- Review Focus: timestamp, empty batch, missing breadth, partial publication and budget/preemption each have a named owning-task test.
- Proportion: the plan fixes interfaces and gates without transcribing implementations; uncertain provider limits are resolved by Task 3 evidence before dependent live work.
