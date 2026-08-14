from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
from statistics import mean, median

import portfolio_candidate_capital_v2 as v2
import portfolio_walkforward_research as wf
import strategy_optimizer_runner as mtm
import strategy_optimizer_v2 as opt
import strategy_selection_research as selection

POOL = Path('static/replay_backtest_pool_v2.json')
OUT = Path('static/exit_recycle_research.json')

BASE_RISK_PCT = 0.75
BASE_CAPACITY = 10
TRAIL_R = 1.0

# Coarse, pre-registered exit structures. This is mechanism research, not a grid.
POLICIES = {
    'natural': {
        'label': '기준 · 100% 자연청산',
        'partial_fraction': 0.0,
        'partial_trigger_r': None,
        'use_trailing': False,
    },
    'partial25_1r': {
        'label': '+1R 확인 후 다음 시가 25% 회수',
        'partial_fraction': 0.25,
        'partial_trigger_r': 1.0,
        'use_trailing': False,
    },
    'partial50_1r': {
        'label': '+1R 확인 후 다음 시가 50% 회수',
        'partial_fraction': 0.50,
        'partial_trigger_r': 1.0,
        'use_trailing': False,
    },
    'partial25_2r': {
        'label': '+2R 확인 후 다음 시가 25% 회수',
        'partial_fraction': 0.25,
        'partial_trigger_r': 2.0,
        'use_trailing': False,
    },
    'trail_after_1r': {
        'label': '+1R 이후 1R폭 종가 트레일링',
        'partial_fraction': 0.0,
        'partial_trigger_r': None,
        'use_trailing': True,
    },
    'partial25_1r_trail': {
        'label': '+1R 25% 회수 + 나머지 1R폭 트레일링',
        'partial_fraction': 0.25,
        'partial_trigger_r': 1.0,
        'use_trailing': True,
    },
}


def costs(pool: dict) -> tuple[float, float]:
    c = pool.get('costs') or {}
    commission = opt.num(c.get('commission_pct_per_side'), 0.10) / 100.0
    friction = (opt.num(c.get('slippage_bps'), 5.0) + opt.num(c.get('half_spread_bps'), 2.5)) / 10000.0
    return commission, friction


def raw_entry(candidate: dict) -> float:
    path = candidate.get('path') or []
    if not path:
        return 0.0
    if (candidate.get('entry_mode') or 'next_open') == 'intraday_trigger':
        return opt.num(candidate.get('trigger'))
    return opt.num(path[0][1])


def liquidation_factor(raw_price: float, paid: float, commission: float, friction: float) -> float:
    if raw_price <= 0 or paid <= 0:
        return 0.0
    received = raw_price * (1.0 - friction) * (1.0 - commission)
    return max(0.0, received / paid)


def milestone_next_open(candidate: dict, base_row: dict, trigger_r: float, pool: dict) -> dict | None:
    """Trigger on a completed close and sell only at the next session open.

    This deliberately avoids same-day OHLC ordering assumptions.
    """
    path = candidate.get('path') or []
    if len(path) < 2:
        return None
    entry = raw_entry(candidate)
    stop = opt.num(candidate.get('stop'))
    if entry <= 0 or stop <= 0 or entry <= stop:
        return None
    threshold = entry + trigger_r * (entry - stop)
    base_end = str(base_row.get('end_date') or '')
    commission, friction = costs(pool)
    paid = entry * (1.0 + friction) * (1.0 + commission)
    for i, bar in enumerate(path[:-1]):
        day = str(bar[0])
        if base_end and day >= base_end:
            break
        if opt.num(bar[4]) < threshold:
            continue
        nxt = path[i + 1]
        sell_day = str(nxt[0])
        if base_end and sell_day > base_end:
            return None
        factor = liquidation_factor(opt.num(nxt[1]), paid, commission, friction)
        if factor <= 0:
            return None
        return {
            'trigger_date': day,
            'date': sell_day,
            'factor': factor,
            'trigger_r': trigger_r,
        }
    return None


def close_trail_exit(candidate: dict, base_row: dict, pool: dict) -> dict | None:
    """After +1R is confirmed at a close, trail by one original R using closes.

    The trailing floor is formed only from completed closes. A close below the
    prior floor schedules a full exit for the next open, so there is no same-day
    high/low ordering dependency.
    """
    path = candidate.get('path') or []
    if len(path) < 3:
        return None
    entry = raw_entry(candidate)
    stop = opt.num(candidate.get('stop'))
    if entry <= 0 or stop <= 0 or entry <= stop:
        return None
    rdist = entry - stop
    activation = entry + rdist
    base_end = str(base_row.get('end_date') or '')
    commission, friction = costs(pool)
    paid = entry * (1.0 + friction) * (1.0 + commission)
    active = False
    high_close = entry
    floor = entry
    for i, bar in enumerate(path[:-1]):
        day = str(bar[0])
        if base_end and day >= base_end:
            break
        close = opt.num(bar[4])
        if not active:
            if close >= activation:
                active = True
                high_close = close
                floor = max(entry, high_close - TRAIL_R * rdist)
            continue
        # Today's close is compared with a floor known before today's close.
        if close < floor:
            nxt = path[i + 1]
            exit_day = str(nxt[0])
            if base_end and exit_day > base_end:
                return None
            factor = liquidation_factor(opt.num(nxt[1]), paid, commission, friction)
            if factor <= 0:
                return None
            return {
                'signal_date': day,
                'date': exit_day,
                'factor': factor,
                'floor': floor,
                'trail_r': TRAIL_R,
            }
        high_close = max(high_close, close)
        floor = max(floor, entry, high_close - TRAIL_R * rdist)
    return None


def enriched_execute(candidate: dict, pool: dict) -> dict | None:
    row = mtm.execute_candidate_mtm(candidate, pool, None, None)
    if not row:
        return None
    out = dict(row)
    out['_recycle'] = {
        'partial_1r': milestone_next_open(candidate, row, 1.0, pool),
        'partial_2r': milestone_next_open(candidate, row, 2.0, pool),
        'trail_1r': close_trail_exit(candidate, row, pool),
    }
    return out


def policy_plan(row: dict, policy: dict) -> dict:
    rec = row.get('_recycle') or {}
    partial = None
    if policy['partial_fraction'] > 0:
        key = 'partial_1r' if policy['partial_trigger_r'] == 1.0 else 'partial_2r'
        partial = rec.get(key)
    trail = rec.get('trail_1r') if policy['use_trailing'] else None
    return {'partial': partial, 'trail': trail}


def recycle_portfolio(rows: list[dict], start: date, end: date, policy: dict) -> dict:
    selected = [dict(r) for r in rows if start <= opt.parse_day(r['start_date']) <= end and opt.parse_day(r['end_date']) <= end]
    selected.sort(key=lambda r: (r['start_date'], -opt.num(r.get('priority')), str(r.get('key') or '')))

    starts, natural_ends, marks = defaultdict(list), defaultdict(list), defaultdict(list)
    partials, trail_exits = defaultdict(list), defaultdict(list)
    for seq, row in enumerate(selected):
        row['_seq'] = seq
        starts[row['start_date']].append(row)
        natural_ends[row['end_date']].append(row)
        for m in row.get('marks') or ():
            if len(m) >= 2:
                marks[str(m[0])].append((seq, opt.num(m[1], 1.0)))
        plan = policy_plan(row, policy)
        p = plan['partial']
        if p:
            partials[p['date']].append((seq, p, float(policy['partial_fraction'])))
        t = plan['trail']
        if t:
            trail_exits[t['date']].append((seq, t))

    days = sorted(set(starts) | set(natural_ends) | set(marks) | set(partials) | set(trail_exits))
    cash = opt.INITIAL_CAPITAL
    peak = cash
    mdd = 0.0
    open_positions = {}
    open_symbols = set()
    fresh_changes = []
    reject_cash = reject_capacity = reject_duplicate = 0
    partial_count = trail_count = 0
    partial_cash = 0.0
    opened_notional = 0.0
    cash_samples, exposure_samples, open_samples = [], [], []
    holds = []

    def exposure() -> float:
        return sum(p['size'] * p['remaining'] * opt.num(p.get('mark'), 1.0) for p in open_positions.values())

    def equity() -> float:
        return cash + exposure()

    for day in days:
        # These are explicitly next-open exits, so their cash is available to
        # same-session fresh entries. Natural exits remain later in the day.
        for seq, event in trail_exits.get(day, []):
            pos = open_positions.get(seq)
            if not pos:
                continue
            proceeds = pos['size'] * pos['remaining'] * opt.num(event.get('factor'), 0.0)
            cash += proceeds
            trail_count += 1
            row = pos['row']
            holds.append(max(0, (opt.parse_day(day) - opt.parse_day(row['start_date'])).days))
            symbol = row.get('symbol')
            if symbol:
                open_symbols.discard(symbol)
            del open_positions[seq]

        for seq, event, fraction in partials.get(day, []):
            pos = open_positions.get(seq)
            if not pos or pos['remaining'] <= 0:
                continue
            sell_fraction = min(pos['remaining'], max(0.0, fraction))
            if sell_fraction <= 0:
                continue
            proceeds = pos['size'] * sell_fraction * opt.num(event.get('factor'), 0.0)
            if proceeds <= 0:
                continue
            cash += proceeds
            partial_cash += proceeds
            partial_count += 1
            pos['remaining'] -= sell_fraction

        incoming = sorted(starts.get(day, []), key=lambda r: (-opt.num(r.get('priority')), str(r.get('key') or ''), r['_seq']))
        for row in incoming:
            symbol = row.get('symbol')
            if symbol and symbol in open_symbols:
                reject_duplicate += 1
                continue
            if len(open_positions) >= BASE_CAPACITY:
                reject_capacity += 1
                continue
            total = equity()
            rf = max(opt.num(row.get('risk_fraction')), 0.001)
            desired = min(total * (BASE_RISK_PCT / 100.0) / rf, total * opt.MAX_SHARE)
            actual = min(cash, desired)
            if actual < 1.0:
                reject_cash += 1
                continue
            open_positions[row['_seq']] = {'row': row, 'size': actual, 'remaining': 1.0, 'mark': 1.0}
            if symbol:
                open_symbols.add(symbol)
            cash -= actual
            opened_notional += actual
            fresh_changes.append(opt.num(row.get('change')))

        for row in sorted(natural_ends.get(day, []), key=lambda r: r['_seq']):
            pos = open_positions.get(row['_seq'])
            if not pos:
                continue
            cash += pos['size'] * pos['remaining'] * (1.0 + opt.num(row.get('change')))
            holds.append(max(0, (opt.parse_day(day) - opt.parse_day(row['start_date'])).days))
            symbol = pos['row'].get('symbol')
            if symbol:
                open_symbols.discard(symbol)
            del open_positions[row['_seq']]

        for seq, factor in marks.get(day, ()):
            if seq in open_positions:
                open_positions[seq]['mark'] = factor

        total = equity()
        expo = exposure()
        if total > 0:
            cash_samples.append(cash / total)
            exposure_samples.append(expo / total)
        open_samples.append(len(open_positions))
        peak = max(peak, total)
        if peak > 0:
            mdd = min(mdd, total / peak - 1.0)

    # Defensive finalization only; normal selected rows should already have ended.
    for pos in open_positions.values():
        cash += pos['size'] * pos['remaining'] * (1.0 + opt.num(pos['row'].get('change')))

    years = max((end - start).days / 365.25, 0.25)
    return {
        'ending': cash,
        'return': cash / opt.INITIAL_CAPITAL - 1.0,
        'cagr': (cash / opt.INITIAL_CAPITAL) ** (1.0 / years) - 1.0 if cash > 0 else -1.0,
        'mdd': mdd,
        'trades': len(fresh_changes),
        'win_rate': sum(x > 0 for x in fresh_changes) / len(fresh_changes) if fresh_changes else 0.0,
        'avg_trade': mean(fresh_changes) if fresh_changes else 0.0,
        'trades_per_year': len(fresh_changes) / years,
        'max_open': max(open_samples, default=0),
        'underwater_days': 0,
        'reject_cash': reject_cash,
        'reject_capacity': reject_capacity,
        'reject_duplicate': reject_duplicate,
        'partial_count': partial_count,
        'trail_exit_count': trail_count,
        'partial_cash_krw': partial_cash,
        'opened_notional_turns_per_year': opened_notional / opt.INITIAL_CAPITAL / years,
        'avg_cash_pct': mean(cash_samples) * 100.0 if cash_samples else 100.0,
        'avg_exposure_pct': mean(exposure_samples) * 100.0 if exposure_samples else 0.0,
        'avg_open_positions': mean(open_samples) if open_samples else 0.0,
        'avg_hold_days': mean(holds) if holds else 0.0,
        'median_hold_days': median(holds) if holds else 0.0,
    }


def compact(x: dict) -> dict:
    base = wf.metric(x)
    base.update({
        'reject_cash': int(x['reject_cash']),
        'reject_capacity': int(x['reject_capacity']),
        'partial_count': int(x['partial_count']),
        'trail_exit_count': int(x['trail_exit_count']),
        'partial_cash_krw': round(x['partial_cash_krw'], 2),
        'opened_notional_turns_per_year': round(x['opened_notional_turns_per_year'], 2),
        'avg_cash_pct': round(x['avg_cash_pct'], 1),
        'avg_exposure_pct': round(x['avg_exposure_pct'], 1),
        'avg_open_positions': round(x['avg_open_positions'], 2),
        'avg_hold_days': round(x['avg_hold_days'], 1),
        'median_hold_days': round(x['median_hold_days'], 1),
    })
    return base


def summarize(folds: list[dict], key: str) -> dict:
    vals = [f['variants'][key] for f in folds]
    returns = [x['return_pct'] for x in vals]
    compound = 1.0
    for r in returns:
        compound *= 1.0 + r / 100.0
    ref = [f['variants']['natural']['return_pct'] for f in folds]
    out = {
        'stitched_test_return_pct': round((compound - 1.0) * 100.0, 2),
        'positive_folds': sum(r > 0 for r in returns),
        'median_test_return_pct': round(median(returns), 2),
        'worst_test_return_pct': round(min(returns), 2),
        'worst_mdd_pct': round(min(x['mdd_pct'] for x in vals), 2),
        'total_fresh_trades': sum(x['trades'] for x in vals),
        'total_cash_rejects': sum(x['reject_cash'] for x in vals),
        'total_capacity_rejects': sum(x['reject_capacity'] for x in vals),
        'total_partial_events': sum(x['partial_count'] for x in vals),
        'total_trail_exits': sum(x['trail_exit_count'] for x in vals),
        'mean_turns_per_year': round(mean(x['opened_notional_turns_per_year'] for x in vals), 2),
        'mean_avg_cash_pct': round(mean(x['avg_cash_pct'] for x in vals), 1),
        'mean_avg_hold_days': round(mean(x['avg_hold_days'] for x in vals), 1),
    }
    if key != 'natural':
        out['folds_beating_reference'] = sum(x > y + 0.01 for x, y in zip(returns, ref))
        out['mean_delta_vs_reference_pct'] = round(mean(x - y for x, y in zip(returns, ref)), 2)
    return out


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
            cache[key] = enriched_execute(c, pool)
        return cache[key]

    results = []
    for fold in folds:
        _, rows = v2.fixed_pairs(family, candidates, fold, executed)
        variants = {
            key: compact(recycle_portfolio(rows, fold['test_start'], fold['test_end'], policy))
            for key, policy in POLICIES.items()
        }
        results.append({
            'fold': fold['id'],
            'test_start': str(fold['test_start']),
            'test_end': str(fold['test_end']),
            'variants': variants,
        })

    summary = {key: summarize(results, key) for key in POLICIES}
    payload = {
        'version': 1,
        'ready': True,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'pool_generated_at': pool.get('generated_at'),
        'promotion_status': 'development_only_exit_recycle_not_fresh_holdout',
        'family': {'id': family['id'], 'name': family['name'], 'strategies': family['strategies']},
        'method': {
            'base_risk_pct': BASE_RISK_PCT,
            'capacity': BASE_CAPACITY,
            'quality_gate': 'fixed top50 within strategy using each fold TRAIN',
            'ranking': 'fixed hybrid_50 using TRAIN distributions only',
            'partial_trigger': 'completed close confirmation, partial sell at next open',
            'trailing': 'activate after +1R completed close; 1R-wide close trail; exit next open after a later close falls below prior floor',
            'natural_exit_unchanged_when_not_preempted': True,
            'same_open_recycling': 'scheduled partial/trailing open proceeds are available to that session fresh entries',
            'grid_search': False,
            'daily_mtm': True,
            'v1_v2_forward_untouched': True,
        },
        'policies': {k: {'label': v['label']} for k, v in POLICIES.items()},
        'summary': summary,
        'folds': results,
        'notes': [
            'This asks whether early profit recycling improves the finite-account system, not whether a partial exit looks good trade-by-trade.',
            'Partial/trailing decisions use completed closes and next opens to avoid same-day OHLC ordering lookahead.',
            'Historical data is development-only, has been repeatedly inspected, and retains current-universe survivorship bias.',
            'Frozen Forward V1 and V2 are not modified.',
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print('\nExit recycle research')
    for key, s in summary.items():
        print(key, 'ret', s['stitched_test_return_pct'], 'mdd', s['worst_mdd_pct'], 'fresh', s['total_fresh_trades'], 'cashrej', s['total_cash_rejects'], 'partial', s['total_partial_events'], 'trail', s['total_trail_exits'], 'turns', s['mean_turns_per_year'], 'beat', s.get('folds_beating_reference'))
    for fold in results:
        print(fold['fold'], {k: v['return_pct'] for k, v in fold['variants'].items()})


if __name__ == '__main__':
    main()
