"""Offline point-in-time opportunity diagnostics from private derived closes only.

No collection, fitting, persistence or publication. Future returns are outcomes,
never scoring inputs. Missing official dates are never bridged. Units: returns,
spreads and drawdown are percentage points; hit rate and turnover are fractions.
"""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
from statistics import mean

from .rotation_operations import calendar_dates, timestamp, number, VERSIONS
from .scoring import load_config
from .sources import INDUSTRY_DEFINITIONS
from .concepts import concept_definitions, load_concept_config


def _ranks(values):
    return [sum(other < value for other in values)+(sum(other == value for other in values)+1)/2 for value in values]


def _correlation(scores, returns):
    x, y = _ranks(scores), _ranks(returns)
    mx, my = mean(x), mean(y)
    denominator = math.sqrt(sum((v-mx)**2 for v in x)*sum((v-my)**2 for v in y))
    return sum((a-mx)*(b-my) for a, b in zip(x, y))/denominator if denominator else None


def _drawdown(paths):
    peak, worst = 1, 0
    for wealth in [mean(point) for point in zip(*paths)]:
        peak = max(peak, wealth)
        worst = max(worst, (peak-wealth)/peak*100)
    return worst


def _spread(sample, omit=None):
    high = [value for identity, value in sample['high'] if identity != omit]
    low = [value for identity, value in sample['low'] if identity != omit]
    return mean(high)-mean(low) if high and low else None


def _summary(samples, dates):
    spreads = [_spread(sample) for sample in samples]
    leave_dates = [mean(spreads[:i]+spreads[i+1:]) for i in range(len(spreads))] if len(spreads) >= 2 else []
    identities = {identity for sample in samples for side in ('high', 'low') for identity, _ in sample[side]}
    leave_sectors = []
    for identity in identities:
        values = [_spread(sample, omit=identity) for sample in samples]
        if all(value is not None for value in values):
            leave_sectors.append(mean(values))
    correlations = [sample['correlation'] for sample in samples if sample['correlation'] is not None]
    return {'validDates': len(samples), 'dates': dates,
        'rankCorrelation': mean(correlations) if correlations else None,
        'spread': mean(spreads) if spreads else None,
        'hitRate': mean(sample['hitRate'] for sample in samples) if samples else None,
        'maximumDrawdown': max((sample['drawdown'] for sample in samples), default=None),
        'minimumLeaveOneDateSpread': min(leave_dates, default=None),
        'minimumLeaveOneSectorSpread': min(leave_sectors, default=None),
        'nonDominated': bool(len(samples) >= 2 and leave_dates and len(leave_sectors) == len(identities)
                             and min(leave_dates) > 0 and min(leave_sectors) > 0)}


def diagnose(rows, official_dates, config, *, live_verified=False):
    """Rows are immutable score-at-close records with derived metrics.return1d.

    High/low groups are top/bottom quintiles of eligible opportunity (>=70%
    completeness, >=20 prior closes). Scores must have been available by their
    close's observedAt (<=15:30 Shanghai). Same-date returns are never outcomes.
    Every 1/3/5-day result uses the next exact official dates, compounded. Hit
    rate is high-group constituent outperformance of the eligible-universe mean.
    Drawdown is the worst high-group buy-and-hold path within any horizon,
    rather than an invalid wealth series made from overlapping horizon returns.
    """
    dates = calendar_dates(official_dates)
    if not isinstance(rows, list): raise ValueError('INVALID_STATE')
    definitions = {'industry': {i for i, _ in INDUSTRY_DEFINITIONS},
                   'concept': {i for i, _ in concept_definitions(load_concept_config())}}
    versions = {key: config[key] for key in VERSIONS}
    grouped, seen = defaultdict(dict), set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('_rawScores', {}), dict) or not isinstance(row.get('metrics', {}), dict):
            raise ValueError('INVALID_STATE')
        universe, identity, day = row.get('universe'), row.get('id'), row.get('marketDate')
        if universe not in definitions or identity not in definitions[universe]: raise ValueError('IDENTITY_MISMATCH')
        if any(row.get(key) != value for key, value in versions.items()): raise ValueError('VERSION_MISMATCH')
        if day not in dates or row.get('session') != 'close' or row.get('officialClose') is not True: continue
        key = day, universe, identity
        if key in seen: raise ValueError('DUPLICATE_CLOSE')
        seen.add(key); grouped[universe, day][identity] = row

    def available(row):
        try:
            observed = timestamp(row.get('observedAt'))
            available_at = timestamp(row.get('availableAt', row.get('observedAt')))
            day = row['marketDate']
            cutoff = timestamp(day+'T15:30:00+08:00')
            start = timestamp(day+'T15:00:00+08:00')
            return start <= observed <= cutoff and available_at <= observed
        except (TypeError, ValueError, OverflowError):
            return False

    universes = {}
    for universe in definitions:
        eligible, top_lists, churn = {}, {}, []
        for day in dates:
            scored = []
            for row in grouped[universe, day].values():
                score = row.get('_rawScores', {}).get('opportunity', row.get('opportunity'))
                if available(row) and number(score) and number(row.get('completeness'), 70) and number(row.get('validCloses'), 20, 100000):
                    scored.append((row['id'], score, row['completeness']))
            scored.sort(key=lambda item: (-item[1], -item[2], item[0]))
            eligible[day] = scored
            if scored:
                current = {item[0] for item in scored[:10]}
                if top_lists:
                    old = list(top_lists.values())[-1]
                    churn.append(1-len(current & old)/max(len(current), len(old)))
                top_lists[day] = current
        horizons = {}
        for horizon in (1, 3, 5):
            samples, date_results = [], []
            for index, day in enumerate(dates):
                result = {'marketDate': day, 'status': 'NO_PIT_SCORES', 'sampleCount': 0}
                date_results.append(result)
                scored = eligible[day]
                if len(scored) < 2: continue
                if index+horizon >= len(dates):
                    result['status'] = 'UNMATURED_OUTCOME'; continue
                outcomes, paths = {}, {}
                for identity, _, _ in scored:
                    wealth, path = 1, []
                    for forward_day in dates[index+1:index+horizon+1]:
                        row = grouped[universe, forward_day].get(identity, {})
                        value = row.get('metrics', {}).get('return1d')
                        if not available(row) or not number(value, -100, 100000): break
                        wealth *= 1+value/100; path.append(wealth)
                    if len(path) == horizon:
                        outcomes[identity], paths[identity] = (wealth-1)*100, path
                # No return-based dropping or group membership changes: the exact
                # score-date sample must mature, including low-ranked losers.
                if len(outcomes) != len(scored):
                    result['status'] = 'MISSING_FORWARD_RETURNS'; continue
                group_size = max(1, len(scored)//5)
                high, low = scored[:group_size], scored[-group_size:]
                benchmark = mean(outcomes.values())
                sample = {'high': [(identity, outcomes[identity]) for identity, _, _ in high],
                    'low': [(identity, outcomes[identity]) for identity, _, _ in low],
                    'correlation': _correlation([score for _, score, _ in scored], [outcomes[identity] for identity, _, _ in scored]),
                    'hitRate': mean(outcomes[identity] > benchmark for identity, _, _ in high),
                    'drawdown': _drawdown([paths[identity] for identity, _, _ in high])}
                samples.append(sample)
                result.update(status='VALID', sampleCount=len(scored), rankCorrelation=sample['correlation'],
                              spread=_spread(sample), hitRate=sample['hitRate'], maximumDrawdown=sample['drawdown'])
            horizons[str(horizon)] = _summary(samples, date_results)
        universes[universe] = {'listTurnover': mean(churn) if churn else None,
            'scoreDateCounts': {day: len(eligible[day]) for day in dates}, 'horizons': horizons}
    return {'schemaVersion': 'rotation-historical-diagnostics-v1', 'versions': versions,
        'liveVerified': live_verified is True, 'officialDates': dates, 'universes': universes,
        'method': 'PIT opportunity quintiles; exact next official dates; buy-and-hold compounded returns; leave-one-date/sector positive spread',
        'limitations': ['OPPORTUNITY_ONLY_NOT_STRENGTH_OR_RISK_VALIDATION', 'NO_COST_OR_OVERLAP_ADJUSTMENT',
                         'TEN_DAY_RUN_IS_NOT_PREDICTIVE_VALIDITY']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True, type=Path, help='Private canonical rotation envelope or job last-success.json')
    parser.add_argument('--calendar', required=True, type=Path, help='Verified official-date JSON array')
    parser.add_argument('--config', type=Path)
    args = parser.parse_args(argv)
    try:
        state = json.loads(args.state.read_text())
        if not isinstance(state, dict) or not isinstance(state.get('rotation', state), dict):
            raise ValueError('INVALID_STATE')
        state = state.get('rotation', state)
        # Offline execution proves calculations only. An operator must separately
        # attach live schema/quota/PIT evidence; the CLI cannot assert live validity.
        result = diagnose(state.get('closes', []), json.loads(args.calendar.read_text()), load_config(args.config))
        print(json.dumps(result, allow_nan=False, separators=(',', ':')))
        return 0
    except (ValueError, TypeError, KeyError, OSError):
        print('{"liveVerified":false,"safeErrorCode":"INVALID_DIAGNOSTIC_INPUT"}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
