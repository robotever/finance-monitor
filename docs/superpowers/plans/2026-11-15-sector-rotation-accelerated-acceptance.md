# Sector Rotation Accelerated Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a temporary, clickable desktop/mobile acceptance page backed only by clearly labelled synthetic sector-rotation data, then prepare the one-real-close beta gate without changing the production v2 page.

**Architecture:** Add an explicit `sector-acceptance` Vite mode whose client-side fetch adapter serves validated embedded fixtures and never calls production APIs. The existing dashboard remains the single UI, with a prominent acceptance banner and test-data wording. Build and browser checks happen locally first; a Cloudflare Pages preview-branch deployment is a separate external step requiring approval and never applies D1 migrations or production feature flags.

**Tech Stack:** Vue 3, TypeScript, Vite, Node test runner, Playwright CLI, Cloudflare Pages preview deployment.

**Spec:** `docs/superpowers/specs/2026-11-15-sector-rotation-accelerated-acceptance-design.md`

## Global Constraints

- Production `newsmonitor.pages.dev` must remain on v2 during acceptance.
- Acceptance data must be synthetic, visibly labelled, and must never be described as a market signal.
- Acceptance mode must make zero requests to production market-dashboard or sector-rotation APIs.
- No D1 migration, v3 publication, GitHub push, production deployment, or production feature activation is authorized.
- Cloudflare preview deployment requires explicit approval after local verification.
- One-real-close beta evaluation remains separate from interface acceptance.

## Review Focus

- Opening an ordinary production build must never activate acceptance fixtures or the v3 board; pin this in Task 1 bundle and browser tests.
- Directly opening a preview route, refreshing it, or changing viewport must preserve the test-data banner and interactive state; pin this in Task 2 browser tests.
- Every universe/view/axis/detail combination must resolve from fixtures without an API request; pin this in Task 1 loader tests and Task 2 browser request assertions.
- Missing or malformed fixture data must fail closed with a visible acceptance error rather than fall back to production APIs; pin this in Task 1 tests.
- The preview must not be indexed or confused with the production site; pin `noindex,nofollow`, preview metadata and visible environment wording in Task 1 tests.

---

### Task 1: Isolated acceptance data mode and visible environment banner

**Files:**
- Create: `src/features/market-dashboard/acceptance.mjs`
- Create: `src/features/market-dashboard/acceptance.d.mts`
- Create: `src/features/market-dashboard/acceptance-fixtures.mjs`
- Modify: `src/components/MarketResearchDashboard.vue`
- Modify: `src/features/market-dashboard/api.mjs`
- Modify: `src/features/market-dashboard/api.d.mts`
- Modify: `src/style.css`
- Modify: `index.html`
- Modify: `package.json`
- Create: `tests/market-dashboard-acceptance.test.mjs`
- Modify: `tests/sector-rotation-components.test.mjs`

**Interfaces:**
- Produces: `isSectorAcceptanceMode(): boolean`.
- Produces: `acceptanceFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response>` for the exact latest/history/rotation latest/history/detail routes already consumed by `api.mjs`.
- Produces: `acceptanceMetadata` with immutable `{ environment: 'acceptance', dataKind: 'synthetic', generatedAt: string }`.
- Consumes: the existing strict v2/v3 and rotation validators in `api.mjs`; fixture payloads must pass them rather than bypass them.

- [ ] **Step 1: Write failing acceptance-isolation tests**

Add tests asserting that `sector-acceptance` plus `VITE_SECTOR_ROTATION_ACCEPTANCE=true` selects the fixture adapter; ordinary/default/`rotation-shadow` modes do not. Assert all supported routes return schema-valid fixtures, unknown or malformed requests fail locally, and an injected network fetch spy remains at zero calls.

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `node --test tests/market-dashboard-acceptance.test.mjs tests/sector-rotation-components.test.mjs`

Expected: FAIL because the acceptance module, mode gate and banner do not exist.

- [ ] **Step 3: Implement deterministic synthetic fixtures and the local adapter**

Implement the interfaces above with exact 35-industry/75-concept v3 identity coverage, 15 supplied history dates, all three current views, both matrix axes and representative detail audit. Do not include provider responses, credentials or copied live observations. Unsupported paths and invalid query enums return safe local errors and never fall through to `fetch`.

- [ ] **Step 4: Add the acceptance-only presentation boundary**

In `MarketResearchDashboard.vue`, use acceptance mode to activate the existing v3 presentation independently of `releaseEligible`, inject `acceptanceFetch` into all dashboard/rotation loaders, and render a persistent banner: `临时验收环境 · 全部为测试数据 · 不代表真实市场信号`. Add `data-environment="sector-acceptance"` for browser assertions. Keep the current loopback-only shadow gate unchanged.

- [ ] **Step 5: Add acceptance build metadata and no-indexing**

Add `npm run build:acceptance` using `vite build --mode sector-acceptance`. In acceptance mode, set document title/description and `robots` to `noindex,nofollow`; default `npm run build` must retain its current metadata and contain no active acceptance marker.

- [ ] **Step 6: Run focused and production-isolation verification**

Run:

```bash
node --test tests/market-dashboard-acceptance.test.mjs tests/sector-rotation-components.test.mjs
npm run build:acceptance
npm run build
```

Expected: all tests and both builds pass; acceptance build contains the banner/noindex and makes no API calls at runtime; ordinary build remains v2.

- [ ] **Step 7: Commit**

Commit: `feat: add isolated sector acceptance preview`

### Task 2: Desktop/mobile acceptance QA and feedback record

**Files:**
- Create: `docs/verification/2026-11-15-sector-rotation-user-acceptance.md`
- Modify only if QA finds an acceptance-specific defect in Task 1 files.

**Interfaces:**
- Consumes: the acceptance build and fixture adapter from Task 1.
- Produces: a local QA record, representative screenshots and an explicit list of user-review prompts.

- [ ] **Step 1: Write the acceptance checklist before browser execution**

Record pending checks for desktop `1440×900` and mobile `390×844`: persistent banner, no horizontal page overflow, industry/concept switching, potential/main/risk switching, strength/opportunity matrix switching, horizontal matrix scrolling, detail open/close, keyboard navigation, refresh/deep-link behavior and zero production API requests.

- [ ] **Step 2: Run the acceptance build on loopback**

Serve only the generated acceptance `dist` on a loopback port. Do not start provider collectors, D1, Functions or production publishers.

- [ ] **Step 3: Execute the full browser checklist**

Use Playwright CLI to exercise all `2 universes × 3 views × 2 axes`, representative details, keyboard focus and both viewports. Capture screenshots for the initial board, concept opportunity view, matrix and detail. Assert every request is a static acceptance asset and zero requests target `/api/market-dashboard` or `/api/sector-rotation`.

- [ ] **Step 4: Verify fallback and failure states**

Run a deliberately malformed local fixture build or injected adapter failure. Assert a visible test-environment error, preserved banner and no fallback to production APIs.

- [ ] **Step 5: Complete the user acceptance record**

Document what is ready for review, what is synthetic, how to report issues, and the still-blocked actions: D1 migration, v3 publication, production UI activation and predictive-validity claims.

- [ ] **Step 6: Run regression verification**

Run:

```bash
npm test
npm run build
git diff --check
```

Expected: all pass and the ordinary production build remains v2.

- [ ] **Step 7: Commit**

Commit: `test: verify sector acceptance experience`

### Task 3: Approved Cloudflare preview-branch publication

**Files:**
- Update: `docs/verification/2026-11-15-sector-rotation-user-acceptance.md`
- No source change unless preview verification finds a deployment-only defect.

**Interfaces:**
- Consumes: the reviewed acceptance `dist` from Task 2.
- Produces: one temporary Cloudflare Pages preview URL, not the production alias.

- [ ] **Step 1: Stop for explicit preview-deployment approval**

Present local QA evidence and request one approval for the external preview deployment. Do not infer approval from design confirmation.

- [ ] **Step 2: Deploy only the acceptance build to a preview branch**

Run the project’s authenticated Wrangler CLI against the existing `newsmonitor` Pages project using a unique non-production branch name. Do not run D1 migrations, do not deploy Functions state changes, do not bind production feature flags, and do not update the production alias.

- [ ] **Step 3: Verify the returned URL and production separation**

Open the preview URL at desktop and mobile sizes. Confirm the banner/noindex, fixture-only behavior and zero market API requests. Separately verify `https://newsmonitor.pages.dev/` still shows the v2 production boundary.

- [ ] **Step 4: Record the preview evidence and hand it to the user**

Record preview URL, deployment identifier, verification time, screenshots, production-separation checks, expiry/removal boundary and an issue checklist. Provide the clickable URL for user acceptance.

- [ ] **Step 5: Commit the verification record**

Commit: `docs: record sector acceptance preview`
