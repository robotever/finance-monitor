# Homepage live terminal implementation plan

> **For agentic workers:** Use superpowers:executing-plans; complete all tasks without intermediate approval.

**Goal:** Ship the approved deep-blue homepage, eight fixed market charts and fresh cross-source tickers.
**Architecture:** Vue homepage and shared normalized news stream; bounded Cloudflare feed endpoint; market source adapters and official widgets where verified. Existing sector data/score pipeline remains unchanged.
**Tech Stack:** Vue 3, TypeScript, Pages Functions, node:test; no paid services.
**Spec:** docs/superpowers/specs/2026-11-21-home-live-terminal-design.md

## Global Constraints
- News window 2 hours; refresh checks 60 seconds; never substitute fetch time for publication time.
- Fixed eight assets, accurate instrument labels, no Wind credit consumption or added accounts.
- Preserve radar, debt research, sector entry; source cards max10. No reinstating previously removed sources.
- Authorized autonomous development, tests, documentation, push of development branch and deployment to existing site.

## Review Focus
- Missing/future timestamps and stale cache must not enter tickers.
- One failed source cannot block healthy sources; bounded waits and response sizes.
- Duplicate syndicated stories should not overwhelm the shared stream.
- Chart source unsupported/closed/delayed states must not become fake real-time claims.
- Desktop/mobile overflow, keyboard pause and reduced motion must remain usable.

### Task 1: Normalized news and shared stream
Files: functions/_lib/live-news.js, functions/api/news/live.js, src/features/live-news/*, src/stores/news.ts, src/types/index.ts, tests/live-news.test.mjs.
- [x] Write failing tests for real timestamp parsing, sorting, 2h expiry, future rejection, dedupe and failed adapters.
- [x] Implement source allowlist, bounded fetching, Cloudflare short caching, response {items,sources,fetchedAt}; items {id,title,url,source,sourceName,publishedAt,important}.
- [x] Share fresh items between tickers, interval clock expires items without reload, preserve separate source cards and cap10.
- [x] Run focused tests and commit.

### Task 2: Fixed charts and homepage visual system
Files: src/components/FixedMarketCharts.vue, src/features/market-watch/*, functions/api/market-watch/* if required, src/views/HomeView.vue, src/components/AppHeader.vue, NewsTicker.vue, VerticalTicker.vue, NewsCard.vue, src/style.css.
- [x] Probe actual quote/chart endpoints; record exact instrument mapping and truthful timing/closure status.
- [x] Write failing tests for instrument allowlist, quote validation and derived chart coordinates if used.
- [x] Build fixed8 switchable charts, source attribution, delay/unavailable states, shared ticker pause and reduced-motion behavior.
- [x] Apply unified navy/cyan colors, prominent charts and sector entry, narrower right news rail, responsive layout.
- [x] Run focused tests and production build.

### Task 3: Verify and deploy
- [x] Fresh whole-change independent review; fix important findings.
- [x] Browser desktop/mobile verify page, chart switching, news timestamp ordering, expiry/error states, sector link.
- [x] Update changelog, ops and actual evidence including source limitations.
- [x] Build production, preserve static sector fallback, deploy existing Cloudflare project and verify real URLs, push dev branch.
