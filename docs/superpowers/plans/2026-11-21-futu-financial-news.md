# Futu financial news implementation plan

> Execute autonomously; user explicitly approved source changes, cloud validation and deployment.

**Goal:** Favor company, industry and intraday market events in the existing shared news stream, with Futu first.
**Architecture:** Fixed public Futu flash/search adapters, deterministic finance classification before dedup/limit, and a bounded monitor over existing index quotes. Retain existing timestamps, two-hour expiry, frame-driven scrolling, and source fault isolation. No Wind calls, paid accounts, trading permissions, or LLM runtime.
**Spec:** User-approved recommendation in current conversation: Futu priority, company/industry/market additions, reduce ordinary international affairs, cloud verification before production.

## Constraints and decisions
- Futu flash:10items; search:20items each for fixed keywords 公司/行业/异动, news_type1, langzh-CN, sort_type2.
- Keep qualified finance messages from Wallstreetcn/Jin10. Drop ordinary political/military/social headlines lacking a concrete financial linkage.
- Preserve newest-first order and two-hour window; empty is acceptable. Do not invent finance stories or relax expiry to fill categories.
- Monitor only existing shanghai/chinext/hstech quotes when current and intraday; absolute daily change>=1% A-share or>=2% HSTECH. Label as system observation/snapshot, never first crossing or media news.
- Native quote timestamps become monitor observation timestamps; do not use polling time as event time. Source URLs carry stable observation identifiers.
- Frontend category buttons filter shared top/right stream; existing compact rows and RAF behavior remain.
- Query and hash route article ids must survive dedup. Search errors are isolated per channel. Cloudflare20s cache key changes with policy version.

## Tasks
- [x] Regression tests first: Futu shapes/business codes/time/link cleanup, semantic hash ids, positive and negative finance classification, partial failure/expiry, intraday alert guards.
- [x] Implement source adapters and finance policy, category types and monitor. Keep request budgets and upstream limits.
- [x] Integrate API/policy metadata and browser category filters; verify compact scrolling unchanged.
- [x] Focused tests/build, independent review; fix important findings.
- [x] Preview cloud deployment: Futu endpoints healthy, real items/time/category, no ordinary affairs, fresh monitor guards; browser desktop/mobile/filter/scroll.
- [x] Document exact sources, rule limitations and measured results; deploy production, verify and push development branch.
