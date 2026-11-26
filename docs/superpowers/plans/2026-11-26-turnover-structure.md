# Turnover Structure Implementation Plan

> For agentic workers: scoped subagents implement independent data and UI tasks; root integrates contracts and final review. Follow TDD and verify both actual endpoints.

**Goal:** Five market rows with same-time change and one-year daily chart.
**Architecture:** Existing observation pipeline, optional strict nested turnover payload, private native-market history and bounded public minutes. Existing scores unchanged.
**Tech Stack:** Python, Vue/TypeScript, Node validation, Pages/D1.
**Spec:** ../specs/2026-11-26-turnover-structure-design.md

- [x] Data: prove board scope, collect strictly validated native full-year market daily amounts, exact-minute previous-day comparison or null with reason; tests for scope/CDR/missing/gaps/future.
- [x] Contract: strict nested turnover model/types, compatibility with legacy payload, numeric/time/unit and source invariants; API roundtrip tests.
- [x] UI: two numeric columns/five rows, market switch and accessible one-year chart, preserve old four quantities folded, compact/mobile.
- [x] Integrate producer optional enrichment and nonregressing publication, real candidate, tests/build and independent review.
- [ ] Preview then production, stable service update and desktop entry; actual local/online desktop/mobile, refresh/chart/failure data checks; preserve static492; docs/PR/merge/restore deployment settings.
