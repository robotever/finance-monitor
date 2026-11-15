# Sector Score Evaluation Framework Design

## Intent

Build a read-only, point-in-time evaluation framework for the sector rotation model while live observations continue to accumulate. The framework must answer whether strength, opportunity and risk contain useful forward information, whether they beat simple baselines, and whether any apparent result is stable rather than driven by one date or one sector.

The first version evaluates the existing `sector-score-v0.2`; it does not change weights, tune thresholds, collect provider data, publish dashboard payloads or authorize trading decisions.

## Goals

- Evaluate industry and concept universes separately.
- Evaluate 1, 3, 5 and 10 official-trading-day horizons without look-ahead.
- Keep the three axes semantically distinct:
  - strength: continuation and forward relative return;
  - opportunity: forward relative return from early improvement;
  - risk: subsequent downside, drawdown and loss avoidance.
- Compare the model with simple, reproducible baselines available in the same point-in-time rows.
- Report coverage, sample maturity and missing outcomes explicitly.
- Produce deterministic JSON for machines and Markdown for human review.
- Preserve score and universe versions in every report so incompatible histories cannot be mixed.

## Non-goals

- No automatic weight optimization or machine-learning fit.
- No live Wind/MX calls, writes to private history, D1 publication or UI changes.
- No claim of predictive validity from synthetic fixtures or a small number of live dates.
- No transaction-cost-adjusted portfolio backtest in the first version.
- No attempt to remove overlap between concept-board constituents until constituent history is available point in time.

## Constraints

- Consume only validated official-close rows already stored by the rotation pipeline.
- A score at date `t` may use only information whose `availableAt <= observedAt <= 15:30 Asia/Shanghai`.
- Outcomes begin on the next exact official date; missing dates or identities are never bridged.
- Industry and concept rows are never ranked together.
- Version mismatch, duplicate close identity or malformed input fails closed.
- Use Python standard library only; do not add a heavy research dependency to production.
- Existing `rotation_diagnostics.py` remains compatible because it is part of the release-evidence path.

## Approaches considered

### 1. Extend the existing release diagnostic in place

This minimizes files, but mixes a narrow release gate with exploratory model comparison. A future methodology change could accidentally alter historical release evidence. Rejected.

### 2. Add a separate lightweight evaluator beside the release diagnostic — selected

Create a pure evaluation module that reuses the same point-in-time validation rules and state envelope but has its own versioned output schema. It compares multiple signals and baselines, supports robustness slices, and renders a Markdown report. This keeps operational release evidence stable and is small enough to audit.

### 3. Adopt Qlib/Alphalens directly

These offer broader research tooling but add dependencies and data-shape adaptation before the project has enough observations. Their metrics inform this design, but direct adoption is deferred.

## Input contract

The evaluator consumes:

- a canonical rotation state envelope or `last-success.json` containing `rotation.closes`;
- an explicit JSON array of verified official market dates;
- the current scoring configuration.

Each eligible row must contain the current score/universe versions, official-close status, valid Shanghai timestamps, universe identity, axis scores and daily return. Components and metrics are optional per signal, but missing values reduce that signal's coverage rather than changing group membership after outcomes are observed.

Canonical stored rows do not carry a separate `availableAt`; when absent it equals `observedAt`. Upstream canonical-state validation establishes source freshness. This evaluator checks score-time availability but cannot independently re-prove provider arrival time and must disclose that boundary.

Axis eligibility requires a finite raw axis score and `axisCompleteness[axis] >= 70`. Opportunity additionally requires `validCloses >= 20`. A baseline requires a finite source metric/component. Each signal reports native coverage; a direct model-versus-baseline comparison uses the same-date intersection of eligible identities so unequal coverage cannot masquerade as performance.

## Signals and baselines

The first version evaluates:

| Key | Direction | Source | Purpose |
|---|---:|---|---|
| `strength` | higher is better | `_rawScores.strength` | continuation |
| `opportunity` | higher is better | `_rawScores.opportunity` | early improvement |
| `risk` | higher is worse | `_rawScores.risk` | loss/drawdown warning |
| `return5d` | higher is better | `metrics.return5d` | short momentum baseline |
| `return20d` | higher is better | `metrics.return20d` | medium momentum baseline |
| `relativeStrength20d` | higher is better | `metrics.relativeStrength20d` | relative-momentum baseline |
| `position` | higher is better | `components.position.value` | current opportunity-position leg |

For return-oriented comparisons, risk is sign-adjusted so a higher evaluation signal means safer/lower risk. Its dedicated loss and drawdown diagnostics retain the original risk direction.

Baseline comparisons are fixed in v1: strength is compared with `return5d`, `return20d` and `relativeStrength20d`; opportunity is compared with `position`, `return5d` and `return20d`; risk has no claimed return baseline and is judged through sign-adjusted return metrics plus its dedicated loss/drawdown diagnostics.

## Evaluation metrics

For each universe, signal and horizon:

- valid score dates and matured score dates;
- eligible sector count and outcome coverage;
- daily Spearman rank IC and its mean;
- IC positive-rate and IC information ratio, defined as mean daily IC divided by sample standard deviation (`n-1`), null with fewer than two finite ICs or zero variance;
- top-quintile minus bottom-quintile compounded forward-return spread;
- top-quintile hit rate against the same-date eligible-universe mean;
- signal-specific top-quintile turnover between adjacent score dates that both contain eligible scores;
- worst buy-and-hold drawdown inside the selected top group;
- leave-one-date and leave-one-sector minimum spread;
- chronological early/middle/late summaries formed from valid samples, balanced contiguously with remainders assigned to earlier slices;
- explicit status for immature, missing-forward-return and insufficient-score cases.

Risk also reports the top raw-risk quintile minus bottom raw-risk quintile for negative-forward-return rate and path maximum drawdown. Positive spreads mean the risk score identifies worse outcomes. Return-oriented risk IC uses `100 - raw risk`, so positive IC means safer sectors subsequently outperform. These are diagnostics, not calibrated probabilities.

## Comparison and interpretation

The report compares model axes against baselines without selecting a winner automatically. It highlights:

- whether the sign is consistent with the signal definition;
- whether the model beats the corresponding simple baseline on mean rank IC and spread;
- whether the result remains positive in each chronological slice;
- whether leave-one-date and leave-one-sector checks remain positive;
- whether sample size and matured coverage are sufficient to interpret.

No hard production threshold is introduced in this version. Fewer than 20 valid matured score dates for a universe/signal/horizon, or fewer than three valid samples for chronological slicing, is labeled `INSUFFICIENT_EVIDENCE`, not passed or failed; metrics remain visible.

## Outputs

- JSON schema `sector-score-evaluation-v1` with methodology, versions, input audit, per-universe results and limitations.
- Markdown report generated from that JSON with a concise executive table, evidence warnings and metric definitions.
- CLI requires `--state` and `--calendar`, accepts optional `--config`, writes JSON to stdout by default and Markdown with `--format markdown`.
- CLI exits non-zero with a format-appropriate safe error and no traceback for invalid inputs; v1 performs no output-file writes.
- Every output declares `evidenceStatus: CALCULATION_ONLY` and `liveVerified: false`; it cannot authorize a production gate. Tests may additionally identify synthetic fixture input.

## Testing strategy

- Hand-computed fixtures prove compounding, IC direction, spread, hit rate and drawdown units.
- A deliberately future-dated `availableAt` proves point-in-time exclusion.
- Missing a future sector return invalidates the whole score-date sample rather than cherry-picking survivors.
- Duplicate identities, incompatible versions and malformed calendars fail closed.
- Synthetic data is visibly labeled and cannot become live evidence.
- Markdown rendering is tested through parsed evaluation output, not source-text inspection.

## Documentation and change control

The methodology document must distinguish formula definition, evaluation metric, evidence status and current limitations. Any future change to signal extraction, outcome definition, horizon, grouping or interpretation increments the evaluation schema version. Any score-weight change remains a separate score version and is evaluated side by side rather than overwriting `v0.2`.
