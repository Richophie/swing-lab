from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import json
from pathlib import Path
from statistics import mean, median

import capital_mechanism_audit as cma
import portfolio_candidate_capital_v2 as v2
import portfolio_walkforward_research as wf
import strategy_optimizer_runner as mtm
import strategy_optimizer_v2 as opt
import strategy_selection_research as selection

POOL = Path('static/replay_backtest_pool_v2.json')
OUT = Path('static/capital_velocity_research.json')

# Pre-registered portfolio structures. This is intentionally NOT a parameter grid.
# All variants use the same family, top-50% quality gate, hybrid_50 ordering,
# natural exits and daily-close MTM. Only portfolio-level capital deployment changes.
POLICIES = {
    'ref_075_cap10': {
        'label': '기준 · 0.75% / 최대 10개',
        'risk_pct': .75, 'capacity': 10, 'cash_floor_pct': 0.0,
    },
    'cap15_075': {
        'label': '슬롯 확대 · 0.75% / 최대 15개',
        'risk_pct': .75, 'capacity': 15, 'cash_floor_pct': 0.0,
    },
    'cap20_075': {
        'label': '슬롯 확대 · 0.75% / 최대 20개',
        'risk_pct': .75, 'capacity': 20, 'cash_floor_pct': 0.0,
    },
    'broad060_cap15': {
        'label': '넓게 분산 · 0.60% / 최대 15개',
        'risk_pct': .60, 'capacity': 15, 'cash_floor_pct': 0.0,
    },
    'broad050_cap20': {
        'label': '최대 분산 · 0.50% / 최대 20개',
        'risk_pct': .50, 'capacity': 20, 'cash_floor_pct': 0.0,
    },
    'reserve15_075_cap20': {
        'label': '현금버퍼 · 0.75% / 최대 20개 / 현금 15%',
        'risk_pct': .75, 'capacity': 20, 'cash_floor_pct': .15,
    },
    'adaptive075_050_cap20': {
        'label': '유동형 · 0.75→0.50% / 최대 20개',
        'risk_pct': .75, 'capacity': 20, 'cash_floor_pct': 0.0,
        'throttle_cash_pct': .25, 'throttle_risk_pct': .50,
    },
}


def risk_budget(policy: dict, cash: float, equity: float) -> float:
    pct = float(policy['risk_pct'])
    threshold = policy.get('throttle_cash_pct')
    if threshold is not None and equity > 0 and cash / equity < float(threshold):
        pct = float(policy.get('throttle_risk_pct', pct))
    return pct / 100.0


def velocity_portfolio(rows: list[dict], start: date, end: date, policy: dict) -> dict:
    selected = [
        dict(r) for r in rows
        if start <= opt.parse_day(r['start_date']) <= end and opt.parse_day(r['end_date']) <= end
    ]
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
    holding_days = []
    reject_cash = reject_capacity = reject_duplicate = cash_limited = 0
    attempts = 0
    desired_total = allocated_total = 0.0
    exposure_samples, cash_samples, open_samples, equity_samples = [], [], [], []
    throttle_entries = 0

    def exposure_value():
        return sum(p['size'] * opt.num(p.get('mark'), 1.0) for p in open_positions.values())

    def equity():
        return cash + exposure_value()

    for day in days:
        incoming = sorted(starts.get(day, []), key=lambda r: (-opt.num(r.get('priority')), str(r.get('key') or ''), r['_seq']))
        for row in incoming:
            attempts += 1
            symbol = row.get('symbol')
            if symbol and symbol in open_symbols:
                reject_duplicate += 1
                continue
            if len(open_positions) >= int(policy['capacity']):
                reject_capacity += 1
                continue

            total = equity()
            rf = max(opt.num(row.get('risk_fraction')), .001)
            rb = risk_budget(policy, cash, total)
            if rb + 1e-12 < float(policy['risk_pct']) / 100.0:
                throttle_entries += 1
            desired = min(total * rb / rf, total * opt.MAX_SHARE)
            floor = total * float(policy.get('cash_floor_pct', 0.0))
            available = max(0.0, cash - floor)
            actual = min(available, desired)
            desired_total += desired
            if actual < 1.0:
                if desired >= 1.0:
                    reject_cash += 1
                continue
            if actual + 1e-6 < desired:
                cash_limited += 1

            open_positions[row['_seq']] = {'row': row, 'size': actual, 'mark': 1.0}
            if symbol:
                open_symbols.add(symbol)
            cash -= actual
            allocated_total += actual
            changes.append(opt.num(row.get('change')))
            try:
                holding_days.append(max(0, (opt.parse_day(row['end_date']) - opt.parse_day(row['start_date'])).days))
            except Exception:
                pass

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
            equity_samples.append(total)
        open_samples.append(len(open_positions))
        peak = max(peak, total)
        if peak > 0:
            mdd = min(mdd, total / peak - 1.0)

    if open_positions:
        for pos in open_positions.values():
            cash += pos['size'] * (1.0 + opt.num(pos['row'].get('change')))

    years = max((end - start).days / 365.25, .25)
    cagr = (cash / opt.INITIAL_CAPITAL) ** (1.0 / years) - 1.0 if cash > 0 else -1.0
    avg_equity = mean(equity_samples) if equity_samples else opt.INITIAL_CAPITAL
    return {
        'ending': cash,
        'return': cash / opt.INITIAL_CAPITAL - 1.0,
        'cagr': cagr,
        'mdd': mdd,
        'trades': len(changes),
        'win_rate': sum(1 for x in changes if x > 0) / len(changes) if changes else 0.0,
        'avg_trade': mean(changes) if changes else 0.0,
        'trades_per_year': len(changes) / years,
        'notional_turns_per_year': allocated_total / max(avg_equity, 1.0) / years,
        'avg_holding_days': mean(holding_days) if holding_days else 0.0,
        'median_holding_days': median(holding_days) if holding_days else 0.0,
        'max_open': max(open_samples, default=0),
        'avg_open_positions': mean(open_samples) if open_samples else 0.0,
        'reject_cash': reject_cash,
        'reject_capacity': reject_capacity,
        'reject_duplicate': reject_duplicate,
        'cash_limited_entries': cash_limited,
        'candidate_attempts': attempts,
        'miss_rate': (reject_cash + reject_capacity) / attempts if attempts else 0.0,
        'allocation_ratio': allocated_total / desired_total if desired_total else 0.0,
        'allocated_capital': allocated_total,
        'avg_exposure_pct': mean(exposure_samples) * 100.0 if exposure_samples else 0.0,
        'avg_cash_pct': mean(cash_samples) * 100.0 if cash_samples else 100.0,
        'throttle_entries': throttle_entries,
    }


def compact(x: dict) -> dict:
    base = wf.metric(x)
    base.update({
        'trades_per_year': round(x['trades_per_year'], 1),
        'notional_turns_per_year': round(x['notional_turns_per_year'], 2),
        'avg_holding_days': round(x['avg_holding_days'], 1),
        'median_holding_days': round(x['median_holding_days'], 1),
        'max_open': int(x['max_open']),
        'avg_open_positions': round(x['avg_open_positions'], 2),
        'reject_cash': int(x['reject_cash']),
        'reject_capacity': int(x['reject_capacity']),
        'reject_duplicate': int(x['reject_duplicate']),
        'cash_limited_entries': int(x['cash_limited_entries']),
        'candidate_attempts': int(x['candidate_attempts']),
        'miss_rate_pct': round(x['miss_rate'] * 100.0, 1),
        'allocation_ratio_pct': round(x['allocation_ratio'] * 100.0, 1),
        'avg_exposure_pct': round(x['avg_exposure_pct'], 1),
        'avg_cash_pct': round(x['avg_cash_pct'], 1),
        'throttle_entries': int(x['throttle_entries']),
    })
    return base


def fold_result(family: dict, candidates: list[dict], fold: dict, executed) -> dict:
    _, rows = v2.fixed_pairs(family, candidates, fold, executed)
    return {
        'fold': fold['id'],
        'test_start': str(fold['test_start']),
        'test_end': str(fold['test_end']),
        'variants': {
            key: compact(velocity_portfolio(rows, fold['test_start'], fold['test_end'], policy))
            for key, policy in POLICIES.items()
        },
    }


def summarize(folds: list[dict], key: str) -> dict:
    vals = [f['variants'][key] for f in folds]
    returns = [x['return_pct'] for x in vals]
    compound = 1.0
    for value in returns:
        compound *= 1.0 + value / 100.0
    ref = [f['variants']['ref_075_cap10']['return_pct'] for f in folds]
    result = {
        'stitched_test_return_pct': round((compound - 1.0) * 100.0, 2),
        'positive_folds': sum(x > 0 for x in returns),
        'median_test_return_pct': round(median(returns), 2),
        'worst_test_return_pct': round(min(returns), 2),
        'worst_mdd_pct': round(min(x['mdd_pct'] for x in vals), 2),
        'total_trades': sum(x['trades'] for x in vals),
        'mean_trades_per_year': round(mean(x['trades_per_year'] for x in vals), 1),
        'mean_notional_turns_per_year': round(mean(x['notional_turns_per_year'] for x in vals), 2),
        'mean_avg_holding_days': round(mean(x['avg_holding_days'] for x in vals), 1),
        'total_cash_rejects': sum(x['reject_cash'] for x in vals),
        'total_capacity_rejects': sum(x['reject_capacity'] for x in vals),
        'mean_miss_rate_pct': round(mean(x['miss_rate_pct'] for x in vals), 1),
        'mean_avg_exposure_pct': round(mean(x['avg_exposure_pct'] for x in vals), 1),
        'mean_avg_cash_pct': round(mean(x['avg_cash_pct'] for x in vals), 1),
        'mean_avg_open_positions': round(mean(x['avg_open_positions'] for x in vals), 2),
    }
    if key != 'ref_075_cap10':
        result['folds_beating_reference'] = sum(x > y + .01 for x, y in zip(returns, ref))
        result['mean_delta_vs_reference_pct'] = round(mean(x - y for x, y in zip(returns, ref)), 2)
    return result


def mechanism(summary: dict) -> dict:
    ref = summary['ref_075_cap10']
    cap15 = summary['cap15_075']
    cap20 = summary['cap20_075']
    broad60 = summary['broad060_cap15']
    broad50 = summary['broad050_cap20']
    reserve = summary['reserve15_075_cap20']
    adaptive = summary['adaptive075_050_cap20']
    return {
        'more_slots_help_at_same_risk': max(cap15['stitched_test_return_pct'], cap20['stitched_test_return_pct']) > ref['stitched_test_return_pct'] and max(cap15.get('folds_beating_reference', 0), cap20.get('folds_beating_reference', 0)) >= 4,
        'smaller_positions_increase_breadth': broad60['total_trades'] > ref['total_trades'] and broad50['total_trades'] > broad60['total_trades'],
        'over_fragmentation_warning': broad50['total_trades'] > ref['total_trades'] and broad50['stitched_test_return_pct'] < ref['stitched_test_return_pct'],
        'hard_cash_floor_adds_value': reserve['stitched_test_return_pct'] > cap20['stitched_test_return_pct'] and reserve.get('folds_beating_reference', 0) >= 4,
        'adaptive_throttle_adds_value': adaptive['stitched_test_return_pct'] > cap20['stitched_test_return_pct'] and adaptive.get('folds_beating_reference', 0) >= 4,
        'note': 'Development-only mechanism evidence. These policies were created after prior history was already inspected and are not a fresh holdout.',
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
        'promotion_status': 'development_only_capital_velocity_not_fresh_holdout',
        'family': {'id': family['id'], 'name': family['name'], 'strategies': family['strategies']},
        'method': {
            'same_signal_and_exit_rules': True,
            'quality_gate': 'fixed top50 within strategy using each fold TRAIN',
            'ranking': 'fixed hybrid_50 using TRAIN distributions only',
            'policies_are_pre_registered_controls': True,
            'grid_search': False,
            'equity': 'daily_close_mark_to_market',
            'purpose': 'measure breadth, cash reserve, slot capacity and capital velocity without changing signal or exit logic',
            'v1_v2_forward_untouched': True,
        },
        'policies': POLICIES,
        'summary': summary,
        'mechanism': mechanism(summary),
        'folds': results,
        'notes': [
            'Higher trade count is not automatically better; return, MDD and missed-signal rate must improve together.',
            'Natural strategy exits are unchanged here. Early winner harvesting / partial exits are intentionally reserved for the later exit research stage.',
            'Current-universe survivorship bias remains in the historical replay pool.',
            'Frozen Forward V1 and V2 are not mutated by this research.',
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print('\nCapital velocity research')
    for key, x in summary.items():
        print(key, 'ret', x['stitched_test_return_pct'], 'mdd', x['worst_mdd_pct'], 'trades', x['total_trades'], 'turns', x['mean_notional_turns_per_year'], 'miss', x['mean_miss_rate_pct'], 'cash', x['mean_avg_cash_pct'], 'beat_ref', x.get('folds_beating_reference'))
    print('mechanism', payload['mechanism'])


if __name__ == '__main__':
    main()
