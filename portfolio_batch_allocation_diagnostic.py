from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
from statistics import mean, median

import portfolio_priority_audit as audit
import portfolio_priority_mechanism as mechanism
import portfolio_walkforward_research as wf
import strategy_optimizer_runner as mtm
import strategy_optimizer_v2 as opt
import strategy_selection_research as selection

POOL = Path('static/replay_backtest_pool_v2.json')
OUT = Path('static/portfolio_batch_allocation_diagnostic.json')

# Mechanism study only. The hybrid ranking was already observed in earlier OOS
# diagnostics, so none of these historical results are a fresh holdout.
VARIANTS = [
    ('sequential_current', '기존 순차배분 · 현재 priority', 'current', 'sequential'),
    ('batch_current', '당일 비례배분 · 현재 priority', 'current', 'batch'),
    ('sequential_hybrid', '기존 순차배분 · 혼합 priority', 'hybrid_50', 'sequential'),
    ('batch_hybrid', '당일 비례배분 · 혼합 priority', 'hybrid_50', 'batch'),
]


def desired_position(total: float, row: dict) -> float:
    risk_fraction = max(opt.num(row.get('risk_fraction')), 0.001)
    by_risk = total * opt.RISK_BUDGET / risk_fraction
    by_share = total * opt.MAX_SHARE
    return max(0.0, min(by_risk, by_share))


def batch_prorata_portfolio(rows: list[dict], start: date, end: date, capacity: int) -> dict:
    """Select top candidates for free slots, then scale same-day desired sizes pro-rata to cash."""
    selected = [
        dict(r) for r in rows
        if start <= opt.parse_day(r['start_date']) <= end and opt.parse_day(r['end_date']) <= end
    ]
    selected.sort(key=lambda r: (r['start_date'], -opt.num(r.get('priority')), str(r.get('key') or '')))

    starts = defaultdict(list)
    ends = defaultdict(list)
    marks = defaultdict(list)
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
    max_drawdown = 0.0
    underwater = 0
    max_underwater = 0
    max_open = 0
    open_positions = {}
    open_symbols = set()
    changes = []
    reject_capacity = 0
    reject_duplicate = 0
    reject_cash = 0
    scaled_days = 0
    scaled_entries = 0
    allocation_factors = []

    def equity():
        return cash + sum(p['size'] * opt.num(p.get('mark'), 1.0) for p in open_positions.values())

    for day in days:
        incoming = sorted(
            starts.get(day, []),
            key=lambda r: (-opt.num(r.get('priority')), str(r.get('key') or ''), r['_seq']),
        )
        free_slots = max(0, capacity - len(open_positions))
        chosen = []
        day_symbols = set()
        for row in incoming:
            symbol = row.get('symbol')
            if symbol and (symbol in open_symbols or symbol in day_symbols):
                reject_duplicate += 1
                continue
            if len(chosen) >= free_slots:
                reject_capacity += 1
                continue
            chosen.append(row)
            if symbol:
                day_symbols.add(symbol)

        if chosen:
            total = equity()
            desires = [desired_position(total, row) for row in chosen]
            total_desired = sum(desires)
            factor = min(1.0, cash / total_desired) if total_desired > 0 else 0.0
            if factor < 1.0 - 1e-12:
                scaled_days += 1
            allocations = [d * factor for d in desires]
            for row, size, desire in zip(chosen, allocations, desires):
                if size < 1.0:
                    reject_cash += 1
                    continue
                if size + 1e-6 < desire:
                    scaled_entries += 1
                allocation_factors.append(size / desire if desire > 0 else 1.0)
                open_positions[row['_seq']] = {'row': row, 'size': size, 'mark': 1.0}
                symbol = row.get('symbol')
                if symbol:
                    open_symbols.add(symbol)
                cash -= size
                changes.append(opt.num(row.get('change')))
                max_open = max(max_open, len(open_positions))

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
            pos = open_positions.get(seq)
            if pos:
                pos['mark'] = factor

        total = equity()
        if total >= peak:
            peak = total
            underwater = 0
        else:
            underwater += 1
            max_underwater = max(max_underwater, underwater)
            if peak > 0:
                max_drawdown = min(max_drawdown, total / peak - 1.0)

    if open_positions:
        for pos in open_positions.values():
            cash += pos['size'] * (1.0 + opt.num(pos['row'].get('change')))

    wins = sum(1 for x in changes if x > 0)
    years = max((end - start).days / 365.25, 0.25)
    cagr = (cash / opt.INITIAL_CAPITAL) ** (1.0 / years) - 1.0 if cash > 0 else -1.0
    return {
        'ending': cash,
        'return': cash / opt.INITIAL_CAPITAL - 1.0,
        'cagr': cagr,
        'mdd': max_drawdown,
        'trades': len(changes),
        'win_rate': wins / len(changes) if changes else 0.0,
        'avg_trade': mean(changes) if changes else 0.0,
        'trades_per_year': len(changes) / years,
        'max_open': max_open,
        'reject_capacity': reject_capacity,
        'reject_duplicate': reject_duplicate,
        'reject_cash': reject_cash,
        'underwater_days': max_underwater,
        'scaled_days': scaled_days,
        'scaled_entries': scaled_entries,
        'mean_allocation_factor': mean(allocation_factors) if allocation_factors else 0.0,
        'median_allocation_factor': median(allocation_factors) if allocation_factors else 0.0,
        'mtm': True,
    }


def allocation_meta(result: dict) -> dict:
    return {
        'max_open': int(result.get('max_open') or 0),
        'reject_capacity': int(result.get('reject_capacity') or 0),
        'reject_duplicate': int(result.get('reject_duplicate') or 0),
        'reject_cash': int(result.get('reject_cash') or 0),
        'scaled_days': int(result.get('scaled_days') or 0),
        'scaled_entries': int(result.get('scaled_entries') or 0),
        'mean_allocation_factor': round(float(result.get('mean_allocation_factor') or 0.0), 4),
        'median_allocation_factor': round(float(result.get('median_allocation_factor') or 0.0), 4),
    }


def family_fold(family: dict, candidates: list[dict], fold: dict, executed) -> dict:
    intensity, thresholds, _train_current, pairs = audit.choose_quality_intensity(family, candidates, fold, executed)
    distributions = audit.train_distributions(pairs, fold['train_start'], fold['train_end'])
    label = next(x[1] for x in selection.INTENSITIES if x[0] == intensity)

    variants = {}
    for vid, vlabel, ranker, allocator in VARIANTS:
        rows = mechanism.ranked_rows(pairs, ranker, distributions)
        if allocator == 'batch':
            result = batch_prorata_portfolio(rows, fold['test_start'], fold['test_end'], family['capacity'])
        else:
            result = mtm.mtm_portfolio(rows, fold['test_start'], fold['test_end'], family['capacity'])
        variants[vid] = {
            'label': vlabel,
            'test': wf.metric(result),
            'allocation': allocation_meta(result),
        }

    return {
        'fold': fold['id'],
        'train_start': str(fold['train_start']),
        'train_end': str(fold['train_end']),
        'test_start': str(fold['test_start']),
        'test_end': str(fold['test_end']),
        'selected_intensity': intensity,
        'selected_intensity_label': label,
        'thresholds': {
            sid: None if thresholds[sid][intensity] is None else round(float(thresholds[sid][intensity]), 6)
            for sid in family['strategies']
        },
        'variants': variants,
    }


def summarize_variant(folds: list[dict], vid: str) -> dict:
    tests = [f['variants'][vid]['test'] for f in folds]
    returns = [x['return_pct'] for x in tests]
    compound = 1.0
    for x in returns:
        compound *= 1.0 + x / 100.0
    alloc = [f['variants'][vid]['allocation'] for f in folds]
    return {
        'stitched_test_return_pct': round((compound - 1.0) * 100.0, 2),
        'median_test_return_pct': round(median(returns), 2) if returns else 0.0,
        'positive_test_folds': sum(1 for x in returns if x > 0),
        'worst_test_mdd_pct': round(min((x['mdd_pct'] for x in tests), default=0.0), 2),
        'total_test_trades': sum(x['trades'] for x in tests),
        'max_open_across_folds': max((x['max_open'] for x in alloc), default=0),
        'total_reject_cash': sum(x['reject_cash'] for x in alloc),
        'total_scaled_days': sum(x['scaled_days'] for x in alloc),
        'total_scaled_entries': sum(x['scaled_entries'] for x in alloc),
    }


def summarize(folds: list[dict]) -> dict:
    variants = {vid: summarize_variant(folds, vid) for vid, *_ in VARIANTS}
    for batch, seq in (('batch_current', 'sequential_current'), ('batch_hybrid', 'sequential_hybrid')):
        xs = [f['variants'][batch]['test']['return_pct'] for f in folds]
        ys = [f['variants'][seq]['test']['return_pct'] for f in folds]
        variants[batch]['folds_beating_sequential'] = sum(1 for x, y in zip(xs, ys) if x > y + 0.01)
        variants[batch]['mean_delta_vs_sequential_pct'] = round(mean(x - y for x, y in zip(xs, ys)), 2)
    y2024 = next((f for f in folds if f['fold'] == '2024'), None)
    return {
        'fold_count': len(folds),
        'variants': variants,
        'test_2024': None if not y2024 else {
            vid: {
                'return_pct': y2024['variants'][vid]['test']['return_pct'],
                'mdd_pct': y2024['variants'][vid]['test']['mdd_pct'],
                **y2024['variants'][vid]['allocation'],
            }
            for vid, *_ in VARIANTS
        },
    }


def main() -> None:
    pool = json.loads(POOL.read_text(encoding='utf-8'))
    if not pool.get('ready') or int(pool.get('version') or 0) < 4:
        raise SystemExit('Replay pool V4 is required')

    candidates = list(pool.get('trades') or [])
    for candidate in candidates:
        candidate['_quality'] = selection.quality_score(candidate)

    folds = wf.folds_for(opt.parse_day(pool['available_start']), opt.parse_day(pool['available_end']))
    cache = {}

    def executed(candidate):
        key = (candidate.get('symbol'), candidate.get('strategy_id'), candidate.get('signal_date'))
        if key not in cache:
            cache[key] = mtm.execute_candidate_mtm(candidate, pool, None, None)
        return cache[key]

    families = []
    for family in selection.FAMILIES:
        rows = [family_fold(family, candidates, fold, executed) for fold in folds]
        families.append({
            'id': family['id'],
            'name': family['name'],
            'strategies': family['strategies'],
            'capacity': family['capacity'],
            'summary': summarize(rows),
            'folds': rows,
        })

    payload = {
        'version': 1,
        'ready': True,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'pool_generated_at': pool.get('generated_at'),
        'promotion_status': 'posthoc_allocation_diagnostic_only',
        'method': {
            'type': 'same-day batch pro-rata capital allocation diagnosis',
            'warning': 'built after earlier OOS priority results; historical returns are not a fresh holdout',
            'selection': 'same frozen TRAIN-only quality intensity as prior rolling research',
            'batch_rule': 'rank candidates for currently free slots, compute risk/max-share desired sizes, and if total desired exceeds cash scale every selected same-day size by one common factor',
            'no_grid_search': True,
            'equity': 'daily_close_mark_to_market',
        },
        'families': families,
        'notes': [
            '이 실험은 같은 날 먼저 처리된 후보가 현금을 독점하는 순서효과를 줄이는 구조 하나만 비교합니다.',
            '당일 비례배분은 미래 후보를 위해 현금을 예약하지 않습니다. 그날 선택된 후보끼리만 동일 비율로 축소합니다.',
            '혼합 priority의 과거 OOS 결과는 이미 본 값이므로 이 파일은 새 검증표가 아니라 메커니즘 진단입니다.',
            'production/실거래 사이징과 priority는 자동 변경하지 않습니다.',
            'survivorship bias는 여전히 남아 있습니다.',
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    for family in families:
        print('\n', family['name'])
        for vid, *_ in VARIANTS:
            x = family['summary']['variants'][vid]
            print(vid, 'ret', x['stitched_test_return_pct'], 'mdd', x['worst_test_mdd_pct'], 'positive', x['positive_test_folds'], 'trades', x['total_test_trades'], 'beats', x.get('folds_beating_sequential'), 'delta', x.get('mean_delta_vs_sequential_pct'))
        print('2024', family['summary'].get('test_2024'))


if __name__ == '__main__':
    main()
