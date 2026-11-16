# Task 10 fix 1 — canonical detail observations

Fixed the review finding where two activated batches with the same `observedAt` produced duplicate detail observations. The frontend correctly requires strictly increasing timestamps and uses each observation timestamp as a unique key.

Detail now ranks complete active manifests by observation timestamp and descending batch ID, using the same deterministic tie choice as `latest`. It selects one whole canonical batch per timestamp before filtering sector identity or selecting the requested date window. A superseded batch cannot reappear when the corrected catalog omits that identity. The exact five-version tuple and active-only restriction remain in the canonical CTE; the original immutable stored rows are unchanged.

Regression tests seed corrected and original publications in reverse tie-preference order, plus a staged higher batch ID. They verify both industry and concept responses, prior-close changes, one-day windows, agreement with latest, and successful validation by the real frontend `validateDetail`. A second regression changes catalog membership in the canonical batch and confirms the detail window chooses the preceding valid date rather than a superseded observation.

Red: both added regressions failed before the change (five observations instead of three; superseded November 13 date instead of November 12).

Green: `node --test tests/sector-rotation-v4-read.test.mjs` — 11 passed, 0 failed, 3.9 seconds. `git diff --check` — clean. Only focused local tests were run; no full suite, live calls, publication, or deployment.
