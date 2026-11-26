# Market Observation Implementation Plan

> For agentic workers: execute inline using executing-plans; independent collector/history/UI tasks and final review use scoped parallel agents.

**Goal:** Ship market breadth, trend coverage, turnover structure and seal/relay indicators to both homepages.
**Architecture:** Isolated collector and daily readonly history; strict derived payload, authenticated D1 transport and shared Vue module. Preserve raw-source provenance privately, publish aggregates/normalized public details only.
**Tech Stack:** Python, Node/Vue3/TS, Cloudflare Pages/D1, macOS launchd.
**Spec:** ../specs/2026-11-26-market-observation-design.md

## Constraints/review focus
No credentials/raw supplier envelopes in Git/browser; no writes to shared stock history. Full pagination and unique identities, same market date/bounded capture window. Missing data stays null; halted/newlylisted samples have explicit eligible denominators. Daily volume/trend not mislabeled realtime. Failure is not no-event. New module does not change existing scores. Local+cloud actual entry validation mandatory.

## Tasks
- [x] Inspect actual sources/history read-only, obtain complete live universe and enough confirmed sessions; save private real candidate.
- [x] TDD strict shared model/types: four groups, date/unit/range/coverage validation, unknown/missing behavior.
- [x] TDD isolated API and table, authenticated publication/stale-write guard, local same-contract read.
- [x] Collector/service: complete snapshots and pools, cache readonly panel, confirmed-daily calculations, failure details,15minute scheduling and safe logs.
- [x] Shared compact UI, distribution and folded institution/anomaly details, actual per-group dates and refresh/cache behavior.
- [x] Tests/build/review and fixes; local preview then actual5184/offline, preserve static archive, cloud preview then production desktop/mobile actual checks.
- [x] Enable independent update job; compare payloads and unchanged old generation; update docs, PR/merge/sync and restore deployment settings.
