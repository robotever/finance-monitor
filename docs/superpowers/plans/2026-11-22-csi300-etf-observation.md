# CSI300 ETF Observation Implementation Plan

> For agentic workers: execute inline using executing-plans; independent source probes and final review use focused agents.

**Goal:** Add verified four-core ETF flow card and daily circulating-cap ratio history to both homepages.
**Architecture:** Shared strict daily model, isolated read-only producer/cache, authenticated D1 JSON transport, shared Vue interactive SVG.
**Tech Stack:** Node/Python, Vue3/TS, Cloudflare Pages/D1, macOS launchd.
**Spec:** ../specs/2026-11-22-csi300-etf-observation-design.md

## Constraints and review focus
- No state/score changes to existing sector/radar pipeline. 4fixed ETFs, CNY/shares units, same effective dates.
- Missing NAV/cap cannot become zero or carry forward; no ordinary/free/adjusted cap substitution.
- Calendar gaps, duplicate/conflicting rows and unit errors fail closed.
- Split discontinuities must suppress false subscriptions; no holder attribution.
- Publishing must retain existing static sector archive and generation. No browser credentials.

## Tasks
- [ ] Source probes: official SSE+SZSE shares, NAV history and ordinary circulating cap history; save normalized private inputs.
- [ ] Model: tests first for alignment, units, 1/5/20 windows, split safety, missing values and payload validation; implement src/features/etf-observation/model.mjs and types.
- [ ] Producer/transport: tests for strict fixed identities, cache/date validation, auth, stale-write rejection. New isolated D1 table + functions API, local route and scheduled producer, no existing writes.
- [ ] UI: observation table + adjacent SVG chart, ranges/crosshair/zoom/fullscreen; share module refresh, error/cached dates, mobile compact layout.
- [ ] Run model/API/full Node tests, production build and independent review; fix findings.
- [ ] Collect real history, install automatic daily updates, validate actual local5184, preserve archive then preview/deploy production and validate actual online. Record both outcomes, update docs and changelog, sync source.
