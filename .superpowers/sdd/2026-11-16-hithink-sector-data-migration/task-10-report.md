# Task 10 — versioned v4 public reads

Implemented four endpoints: `/api/sector-rotation/v4/latest`, `catalog`, `history`, and `detail`, with shared strict query handling and public projection in `functions/_lib/sector-rotation-v4-read.js`. Publishing library changed only to accept the scorer's four independent improvement-evidence families (0–4).

All public reads require active manifests and the exact schema/scoring/universe/feature/membership tuple. Staging-only, absent, and incompatible data return `404 NO_SNAPSHOT`; no v4 endpoint falls back to v3. Errors disclose no storage text. Existing v3 routes are unchanged.

Latest returns industry/concept potential/main/risk lists capped at 10, explicit core concepts capped at 25, and up to 10 eligible dynamic concepts. Core roles come only from published evidence; the read layer does not invent missing core mappings. Dynamic selection uses finite scores, completeness >=70, risk<70, non-crowded state, noncore membership, and deterministic opportunity/strength-change/code ordering. Ineligible rows never pad lists. Current dynamic roles are computed centrally and agree between homepage, catalog filtering, and latest detail observation. Historical detail observations retain their published role evidence; stored rows are never mutated.

Catalog supports both full universes (including ranks above 110), literal code/name search, view/role filters, pages 1–10000, and page sizes 1–100. History supports strength/opportunity/risk over up to 15 official dates and chooses a single canonical complete manifest per date. Detail supports up to 60 market dates, including intraday observations, and obtains prior-close baselines without one query per historical date. Changes only compare the preceding official close under the complete same version tuple. Responses disclose all five versions, Hithink source, membership modes, and approximate-history flags. Projection drops provider rows, constituents, internal rank keys, extra stored fields, nested private text and credential keys.

## Verification

Tests were written before endpoints: initial run failed for six missing read routes and the improvementEvidence=4 validator mismatch. Additional privacy and dynamic-role regressions were observed red before their fixes.

- `node --test tests/sector-rotation-v4-read.test.mjs` — 9 passed.
- `node --test --test-concurrency=1 tests/sector-rotation-v4-publish.test.mjs tests/sector-rotation-v4-read.test.mjs` — 16 passed, 0 failed (8.9s).
- Concurrent combined Functions run emitted 50 passing existing v2/v3 tests plus 7 passing publish tests, then stalled before the read-file result; no failure emitted. The serial focused run above completed. Parent already has the full prechange Node baseline and will own final combined verification.
- `git diff --check` — clean.

SQLite-backed tests cover 90 industries/390 concepts, staging isolation, exact five-version rejection per endpoint, canonical official closes, prior-close changes and incompatible baselines, private-field exclusion, strict queries, pagination/search/filtering, missing-score nonpadding, dynamic-role agreement, and rank 390.

No deployment, remote writes, real-data publication, or production authorization was attempted. No claim of live provider validation or financial score effectiveness is made. Existing privately collected payloads predating producer core-role annotation may legitimately expose fewer than 25 core rows; producer configuration must supply the reviewed core identities before a complete core UI is expected.
