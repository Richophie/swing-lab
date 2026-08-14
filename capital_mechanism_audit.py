from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import json
from pathlib import Path
from statistics import mean, median

import portfolio_candidate_capital_v2 as v2
import portfolio_walkforward_research as wf
import strategy_optimizer_runner as mtm
import strategy_optimizer_v2 as opt
import strategy_selection_research as selection

POOL = Path('static/replay_backtest_pool_v2.json')
OUT = Path('static/capital_mechanism_audit.json')

# Pre-registered controls. These are mechanism tests, not an optimization grid.
POLICIES = {
    'flat_100': {'label': '균등 1.00%', 'low': 1.0, 'mid': 1.0, 'high': 1.0},
    'flat_075': {'label': '균등 0.75%', 'low': .75, 'mid': .75, 'high': .75},
    'flat_050': {'label': '균등 0.50%', 'low': .50, 'mid': .50, 'high': .50},
    'tiered': {'label': '점수순 0.50/0.75/1.00%', 'low': .50, 'mid': .75, 'high': 1.0},
    'reversed': {'label': '역순 1.00/0.75/0.50%', 'low': 1.0, 'mid': .75, 'high': .50},
}


def multiplier(policy: dict, row: dict) -> float:
    tier = str(row.get('_v2_tier') or v2.conviction_tier(row.get('_v2_conviction') or 0.0))
    return float(policy[tier])


def mechanism_portfolio(rows: list[dict], start: date, end: date, capacity: int, policy: dict) -> dict:
    selected = [dict(r) for r in rows if start <= opt.parse_day(r['start_date']) <= end and opt.parse_day(r['end_date']) <= end]
    selected.sort(key=lambda r: (r['start_date'], -opt.num(r.get('priority')), str(r.get('key') or '')))

    starts, ends, marks = defaultdict(list), defaultdict(list), defaultdict(list)
    for seq, row in enumerate(selected):
        row['_seq'] = seq
        starts[row['start_date']].append(row)
        ends[row['end_date']].append(row)
        for mark in row.get('marks') or ():
            if len(mark) >= 2 and str(mark[0]):
                marks[str(mark[0])].append((seq, opt.num(mark[1], 1.0)))
    days = sorted(set(starts) | set(ends) | set(marks))

    cash = opt.INITIAL_CAPITAL
    peak = cash
    mdd = 0.0
    open_positions = {}
    open_symbols = set()
    changes = []
    reject_cash = reject_capacity = reject_duplicate = cash_limited = 0
    desired_total = allocated_total = 0.0
    exposure_samples, cash_samples, open_samples = [], [], []
    tier_capital = defaultdict(float)
    tier_trades = defaultdict(int)

    def exposure_value():
        return sum(p['size'] * opt.num(p.get('mark'), 1.0) for p in open_positions.values())

    def equity():
        return cash + exposure_value()

    for day in days:
        incoming = sorted(starts.get(day, []), key=lambda r: (-opt.num(r.get('priority')), str(r.get('key') or ''), r['_seq']))
        for row in incoming:
            symbol = row.get('symbol')
            if symbol and symbol in open_symbols:
                reject_duplicate += 1
                continue
            if len(open_positions) >= capacity:
                reject_capacity += 1
                continue
            total = equity()
            rf = max(opt.num(row.get('risk_fraction')), .001)
            mult = multiplier(policy, row)
            desired = min(total * opt.RISK_BUDGET * mult / rf, total * opt.MAX_SHARE)
            actual = min(cash, desired)
            desired_total += desired
            if actual < 1.0:
                if desired >= 1.0:
                    reject_cash += 1
                continue
            if actual + 1e-6 < desired:
                cash_limited += 1
            tier = str(row.get('_v2_tier') or 'low')
            open_positions[row['_seq']] = {'row': row, 'size': actual, 'mark': 1.0}
            if symbol:
                open_symbols.add(symbol)
            cash -= actual
            allocated_total += actual
            tier_capital[tier] += actual
            tier_trades[tier] += 1
            changes.append(opt.num(row.get('change')))

        for row in sorted(ends.get(day, []), key=lambda r: r['_seq']):
            pos = open_positions.get(row['_seq'])
            if not pos:
                continue
            cash += pos['size'] * (1.0 + opt.num(row.get('change')))
            symbol = pos['row'].get('symbol')
            if symbol:
                open_symbols.discard(symbol)
            del open_positions[row['_seq']]

        for seq, factor in marks.get(day, ()):
            if seq in open_positions:
                open_positions[seq]['mark'] = factor

        total = equity()
        expo = exposure_value()
        if total > 0:
            exposure_samples.append(expo / total)
            cash_samples.append(cash / total)
        open_samples.append(len(open_positions))
        peak = max(peak, total)
        if peak > 0:
            mdd = min(mdd, total / peak - 1.0)

    if open_positions:
        for pos in open_positions.values():
            cash += pos['size'] * (1.0 + opt.num(pos['row'].get('change')))

    years = max((end - start).days / 365.25, .25)
    cagr = (cash / opt.INITIAL_CAPITAL) ** (1.0 / years) - 1.0 if cash > 0 else -1.0
    return {
        'ending': cash,
        'return': cash / opt.INITIAL_CAPITAL - 1.0,
        'cagr': cagr,
        'mdd': mdd,
        'trades': len(changes),
        'win_rate': sum(1 for x in changes if x > 0) / len(changes) if changes else 0.0,
        'avg_trade': mean(changes) if changes else 0.0,
        'trades_per_year': len(changes) / years,
        'max_open': max(open_samples, default=0),
        'reject_cash': reject_cash,
        'reject_capacity': reject_capacity,
        'reject_duplicate': reject_duplicate,
        'cash_limited_entries': cash_limited,
        'allocation_ratio': allocated_total / desired_total if desired_total else 0.0,
        'avg_exposure_pct': mean(exposure_samples) * 100.0 if exposure_samples else 0.0,
        'median_exposure_pct': median(exposure_samples) * 100.0 if exposure_samples else 0.0,
        'avg_cash_pct': mean(cash_samples) * 100.0 if cash_samples else 100.0,
        'avg_open_positions': mean(open_samples) if open_samples else 0.0,
        'capital_by_tier': dict(tier_capital),
        'trades_by_tier': dict(tier_trades),
    }


def compact(x: dict) -> dict:
    base = wf.metric(x)
    base.update({
        'reject_cash': int(x['reject_cash']),
        'cash_limited_entries': int(x['cash_limited_entries']),
        'reject_capacity': int(x['reject_capacity']),
        'allocation_ratio_pct': round(x['allocation_ratio'] * 100.0, 1),
        'avg_exposure_pct': round(x['avg_exposure_pct'], 1),
        'median_exposure_pct': round(x['median_exposure_pct'], 1),
        'avg_cash_pct': round(x['avg_cash_pct'], 1),
        'avg_open_positions': round(x['avg_open_positions'], 2),
    })
    return base


def fold_result(family: dict, candidates: list[dict], fold: dict, executed) -> dict:
    _, rows = v2.fixed_pairs(family, candidates, fold, executed)
    variants = {
        key: mechanism_portfolio(rows, fold['test_start'], fold['test_end'], family['capacity'], policy)
        for key, policy in POLICIES.items()
    }
    return {
        'fold': fold['id'],
        'test_start': str(fold['test_start']),
        'test_end': str(fold['test_end']),
        'variants': {key: compact(value) for key, value in variants.items()},
    }


def summarize(folds: list[dict], key: str) -> dict:
    vals = [f['variants'][key] for f in folds]
    returns = [x['return_pct'] for x in vals]
    compound = 1.0
    for value in returns:
        compound *= 1.0 + value / 100.0
    baseline = [f['variants']['flat_100']['return_pct'] for f in folds]
    flat75 = [f['variants']['flat_075']['return_pct'] for f in folds]
    reversed_ = [f['variants']['reversed']['return_pct'] for f in folds]
    result = {
        'stitched_test_return_pct': round((compound - 1.0) * 100.0, 2),
        'positive_folds': sum(x > 0 for x in returns),
        'median_test_return_pct': round(median(returns), 2),
        'worst_test_return_pct': round(min(returns), 2),
        'worst_mdd_pct': round(min(x['mdd_pct'] for x in vals), 2),
        'total_trades': sum(x['trades'] for x in vals),
        'total_cash_rejects': sum(x['reject_cash'] for x in vals),
        'total_cash_limited_entries': sum(x['cash_limited_entries'] for x in vals),
        'mean_avg_exposure_pct': round(mean(x['avg_exposure_pct'] for x in vals), 1),
        'mean_avg_cash_pct': round(mean(x['avg_cash_pct'] for x in vals), 1),
        'mean_avg_open_positions': round(mean(x['avg_open_positions'] for x in vals), 2),
    }
    if key != 'flat_100':
        result['folds_beating_flat100'] = sum(x > y + .01 for x, y in zip(returns, baseline))
        result['mean_delta_vs_flat100_pct'] = round(mean(x - y for x, y in zip(returns, baseline)), 2)
    if key == 'tiered':
        result['folds_beating_flat075'] = sum(x > y + .01 for x, y in zip(returns, flat75))
        result['mean_delta_vs_flat075_pct'] = round(mean(x - y for x, y in zip(returns, flat75)), 2)
        result['folds_beating_reversed'] = sum(x > y + .01 for x, y in zip(returns, reversed_))
        result['mean_delta_vs_reversed_pct'] = round(mean(x - y for x, y in zip(returns, reversed_)), 2)
    return result


def interpretation(summary: dict) -> dict:
    tiered = summary['tiered']
    flat75 = summary['flat_075']
    reversed_ = summary['reversed']
    reserve_effect = flat75['stitched_test_return_pct'] > summary['flat_100']['stitched_test_return_pct']
    score_adds = tiered.get('folds_beating_flat075', 0) >= 4 and tiered['stitched_test_return_pct'] > flat75['stitched_test_return_pct']
    direction_matters = tiered.get('folds_beating_reversed', 0) >= 4 and tiered['stitched_test_return_pct'] > reversed_['stitched_test_return_pct']
    if score_adds and direction_matters:
        verdict = 'capital_reserve_plus_score_ordering'
    elif reserve_effect:
        verdict = 'mostly_capital_reserve'
    else:
        verdict = 'inconclusive'
    return {
        'verdict': verdict,
        'uniform_075_beats_flat_100': reserve_effect,
        'tiered_adds_over_uniform_075': score_adds,
        'tier_direction_beats_reversed': direction_matters,
        'note': 'Six rolling folds are diagnostic, not enough for a formal statistical claim.',
    }


def main() -> None:
    pool = json.loads(POOL.read_text(encoding='utf-8'))
    if not pool.get('ready') or int(pool.get('version') or 0) < 4:
        raise SystemExit('Replay pool V4 is required')
    candidates = list(pool.get('trades') or [])
    for c in candidates:
        c['_quality'] = selection.quality_score(c)
    family = next(f for f in selection.FAMILIES if f['id'] == v2.FAMILY_ID)
    folds = wf.folds_for(opt.parse_day(pool['available_start']), opt.parse_day(pool['available_end']))
    cache = {}
    def executed(c):
        key = (c.get('symbol'), c.get('strategy_id'), c.get('signal_date'))
        if key not in cache:
            cache[key] = mtm.execute_candidate_mtm(c, pool, None, None)
        return cache[key]
    results = [fold_result(family, candidates, fold, executed) for fold in folds]
    summary = {key: summarize(results, key) for key in POLICIES}
    payload = {
        'version': 1,
        'ready': True,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'pool_generated_at': pool.get('generated_at'),
        'promotion_status': 'mechanism_diagnostic_only_not_fresh_holdout',
        'family': {'id': family['id'], 'name': family['name'], 'strategies': family['strategies']},
        'method': {
            'quality_gate': 'fixed top50 within strategy using each fold TRAIN',
            'ranking': 'fixed hybrid_50 using TRAIN distributions only',
            'controls': 'flat 1.0%, flat 0.75%, flat 0.5%, score-tiered 0.5/0.75/1.0%, and reversed-tier 1.0/0.75/0.5%',
            'purpose': 'separate score alpha from lower exposure / cash-reserve effect',
            'grid_search': False,
            'equity': 'daily_close_mark_to_market',
            'v1_untouched': True,
        },
        'summary': summary,
        'interpretation': interpretation(summary),
        'folds': results,
        'notes': [
            'If uniform 0.75% matches tiered sizing, most benefit is capital reserve rather than candidate discrimination.',
            'If tiered sizing beats both uniform 0.75% and reversed sizing repeatedly, score direction contributes incremental value.',
            'This historical sample has already been inspected and retains current-universe survivorship bias.',
            'Frozen Challenger V1 is not changed.',
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print('\nCapital mechanism audit')
    for key, x in summary.items():
        print(key, 'ret', x['stitched_test_return_pct'], 'mdd', x['worst_mdd_pct'], 'pos', x['positive_folds'], 'trades', x['total_trades'], 'cashrej', x['total_cash_rejects'], 'cashlimited', x['total_cash_limited_entries'], 'exposure', x['mean_avg_exposure_pct'], 'cash', x['mean_avg_cash_pct'], 'vs075', x.get('folds_beating_flat075'), 'vsrev', x.get('folds_beating_reversed'))
    print('interpretation', payload['interpretation'])
    for f in results:
        print(f['fold'], {k: v['return_pct'] for k, v in f['variants'].items()})


if __name__ == '__main__':
    main()
