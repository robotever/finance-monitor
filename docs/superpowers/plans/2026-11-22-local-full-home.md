# Local full homepage implementation

User authorized the full local homepage with the existing desktop entry and automatic completion.

- [x] Reuse HomeView/App/router, loopback5184, local sector manifest/document APIs; retain old board URL.
- [x] Direct-only bounded public HTTP transport, durable caches, news aggregation and fixed-source recovery, no Cloudflare dependency.
- [x] Independent local radar/risk with strict real local input and preserved source failure/date semantics.
- [x] Eight local native market charts, real provider/time/CFD labels and persistent fallback.
- [x] Offline UI explains cached data, expired news only in archive; seed successful raw sequences and verify live/offline/restart.
- [x] Desktop app opens root homepage; login service retains loopback restriction. Verify main/sector pages, save docs and sync main.

Approach: Vite reuses source frontend and local-only flag; Node server owns read-only APIs and cache under data/local-home. Existing Mac data collector/publisher and online score formulas unchanged. No secrets to browser. Only fixed upstreams/known routes; mutations denied. Online assets stay unchanged unless shared bug fixes are independently verified.
