from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import json
from pathlib import Path
from statistics import mean, median

import portfolio_priority_audit as audit
import portfolio_walkforward_research as wf
import strategy_optimizer_runner as mtm
import strategy_optimizer_v2 as opt
import strategy_selection_research as selection

POOL = Path('static/replay_backtest_pool_v2.json')
OUT = Path('static/portfolio_priority_mechanism.json')

# Post-hoc mechanism diagnosis only. These historical comparisons MUST NOT be
# treated as a fresh holdout or used to tune a new production ranking rule.
RANKERS = [
    ('current', '현재 raw priority'),
    ('current_pct', '현재 priority · 전략별 백분위 정규화'),
    ('quality_pct', '전략별 품질 백분위'),
    ('hybrid_50', '현재+품질 백분위 50:50'),
]


def rank_value(ranker: str, candidate: dict, row: dict, distributions: dict) -> float:
    if ranker == 'current':
        return float(row.get('_audit_current_priority', row.get('priority') or 0.0))
    sid = str(candidate.get('strategy_id') or row.get('strategy_id') or '')
    dist = distributions.get(sid) or {'quality': [], 'priority': []}
    current_pct = audit.empirical_percentile(
        dist.get('priority') or [],
        float(row.get('_audit_current_priority', row.get('priority') or 0.0)),
    )
    if ranker == 'current_pct':
        return current_pct
    quality_pct = audit.empirical_percentile(
        dist.get('quality') or [],
        float(candidate.get('_quality', 0.0)),
    )
    if ranker == 'quality_pct':
        return quality_pct
    if ranker == 'hybrid_50':
        return 0.5 * current_pct + 0.5 * quality_pct
    raise KeyError(ranker)


def ranked_rows(pairs: list[tuple[dict, dict]], ranker: str, distributions: dict) -> list[dict]:
    rows = []
    for candidate, raw in pairs:
        row = dict(raw)
        row['priority'] = rank_value(ranker, candidate, row, distributions)
        row['_mechanism_ranker'] = ranker
        rows.append(row)
    return rows


def allocation_trace(rows: list[dict], start: date, end: date, capacity: int) -> dict:
    """Replay account order and separate capacity limits from cash-allocation limits."""
    selected = [
        dict(r) for r in rows
        if start <= opt.parse_day(r['start_date']) <= end and opt.parse_day(r['end_date']) <= end
    ]
    selected.sort(key=lambda r: (r['start_date'], -opt.num(r.get('priority')), str(r.get('key') or '')))

    starts = defaultdict(list)
    ends = defaultdict(list)
    mark_updates = defaultdict(list)
    for seq, row in enumerate(selected):
        row['_seq'] = seq
        starts[row['start_date']].append(row)
        ends[row['end_date']].append(row)
        for mark in row.get('marks') or ():
            if len(mark) >= 2 and str(mark[0]):
                mark_updates[str(mark[0])].append((seq, opt.num(mark[1], 1.0)))

    days = sorted(set(starts) | set(ends) | set(mark_updates))
    cash = opt.INITIAL_CAPITAL
    open_positions = {}
    open_symbols = set()
    capacity_rejects = 0
    duplicate_rejects = 0
    cash_exhausted_rejects = 0
    cash_limited_entries = 0
    accepted_entries = 0
    allocation_ratios = []
    requested_by_strategy = defaultdict(float)
    allocated_by_strategy = defaultdict(float)
    accepted_by_strategy = defaultdict(int)

    for day in days:
        incoming = sorted(
            starts.get(day, []),
            key=lambda r: (-opt.num(r.get('priority')), str(r.get('key') or ''), r['_seq']),
        )
        for row in incoming:
            symbol = row.get('symbol')
            if symbol and symbol in open_symbols:
                duplicate_rejects += 1
                continue
            if len(open_positions) >= capacity:
                capacity_rejects += 1
                continue

            total = cash + sum(p['size'] * opt.num(p.get('mark'), 1.0) for p in open_positions.values())
            risk_fraction = max(opt.num(row.get('risk_fraction')), 0.001)
            by_risk = total * opt.RISK_BUDGET / risk_fraction
            max_position = total * opt.MAX_SHARE
            desired = max(0.0, min(by_risk, max_position))
            actual = max(0.0, min(cash, desired))
            sid = str(row.get('strategy_id') or '')
            requested_by_strategy[sid] += desired

            if actual < 1.0:
                if desired >= 1.0:
                    cash_exhausted_rejects += 1
                continue
            if actual + 1e-6 < desired:
                cash_limited_entries += 1
            accepted_entries += 1
            allocation_ratios.append(actual / desired if desired > 0 else 1.0)
            allocated_by_strategy[sid] += actual
            accepted_by_strategy[sid] += 1

            open_positions[row['_seq']] = {'row': row, 'size': actual, 'mark': 1.0}
            if symbol:
                open_symbols.add(symbol)
            cash -= actual

        for row in sorted(ends.get(day, []), key=lambda r: r['_seq']):
            pos = open_positions.get(row['_seq'])
            if not pos:
                continue
            cash += pos['size'] * (1.0 + opt.num(row.get('change')))
            symbol = pos['row'].get('symbol')
            if symbol:
                open_symbols.discard(symbol)
            del open_positions[row['_seq']]

        for seq, factor in mark_updates.get(day, ()):
            pos = open_positions.get(seq)
            if pos:
                pos['mark'] = factor

    strategy_allocation = {}
    for sid in sorted(set(requested_by_strategy) | set(allocated_by_strategy)):
        requested = requested_by_strategy[sid]
        allocated = allocated_by_strategy[sid]
        strategy_allocation[sid] = {
            'accepted_entries': int(accepted_by_strategy[sid]),
            'requested_capital': round(requested, 2),
            'allocated_capital': round(allocated, 2),
            'allocation_ratio': round(allocated / requested, 4) if requested > 0 else 0.0,
        }

    return {
        'accepted_entries': accepted_entries,
        'capacity_rejects': capacity_rejects,
        'duplicate_rejects': duplicate_rejects,
        'cash_exhausted_rejects': cash_exhausted_rejects,
        'cash_limited_entries': cash_limited_entries,
        'cash_limited_share': round(cash_limited_entries / accepted_entries, 4) if accepted_entries else 0.0,
        'mean_allocation_ratio': round(mean(allocation_ratios), 4) if allocation_ratios else 0.0,
        'median_allocation_ratio': round(median(allocation_ratios), 4) if allocation_ratios else 0.0,
        'strategy_allocation': strategy_allocation,
    }


def family_fold(family: dict, candidates: list[dict], fold: dict, executed) -> dict:
    intensity, thresholds, _train_current, pairs = audit.choose_quality_intensity(
        family, candidates, fold, executed
    )
    distributions = audit.train_distributions(pairs, fold['train_start'], fold['train_end'])
    label = next(x[1] for x in selection.INTENSITIES if x[0] == intensity)

    rankers = {}
    for rid, rlabel in RANKERS:
        rows = ranked_rows(pairs, rid, distributions)
        test = mtm.mtm_portfolio(rows, fold['test_start'], fold['test_end'], family['capacity'])
        rankers[rid] = {
            'label': rlabel,
            'test': wf.metric(test),
            'allocation': allocation_trace(rows, fold['test_start'], fold['test_end'], family['capacity']),
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
        'rankers': rankers,
    }


def summarize(folds: list[dict]) -> dict:
    out = {'fold_count': len(folds), 'rules': {}}
    baseline = [f['rankers']['current']['test']['return_pct'] for f in folds]
    for rid, _ in RANKERS:
        tests = [f['rankers'][rid]['test'] for f in folds]
        returns = [x['return_pct'] for x in tests]
        compound = 1.0
        for value in returns:
            compound *= 1.0 + value / 100.0
        allocations = [f['rankers'][rid]['allocation'] for f in folds]
        summary = {
            'stitched_test_return_pct': round((compound - 1.0) * 100.0, 2),
            'median_test_return_pct': round(median(returns), 2) if returns else 0.0,
            'positive_test_folds': sum(1 for x in returns if x > 0),
            'worst_test_mdd_pct': round(min((x['mdd_pct'] for x in tests), default=0.0), 2),
            'cash_limited_entries': sum(x['cash_limited_entries'] for x in allocations),
            'cash_exhausted_rejects': sum(x['cash_exhausted_rejects'] for x in allocations),
            'capacity_rejects': sum(x['capacity_rejects'] for x in allocations),
            'mean_fold_allocation_ratio': round(mean(x['mean_allocation_ratio'] for x in allocations), 4) if allocations else 0.0,
        }
        if rid != 'current':
            summary['folds_beating_current'] = sum(1 for a, b in zip(returns, baseline) if a > b + 0.01)
            summary['mean_delta_vs_current_pct'] = round(mean(a - b for a, b in zip(returns, baseline)), 2)
        out['rules'][rid] = summary

    y2024 = next((f for f in folds if f['fold'] == '2024'), None)
    if y2024:
        out['test_2024'] = {
            rid: {
                'return_pct': y2024['rankers'][rid]['test']['return_pct'],
                'mdd_pct': y2024['rankers'][rid]['test']['mdd_pct'],
                **y2024['rankers'][rid]['allocation'],
            }
            for rid, _ in RANKERS
        }
    return out


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
        'promotion_status': 'posthoc_mechanism_diagnostic_only',
        'method': {
            'type': 'priority scale and capital allocation mechanism diagnosis',
            'warning': 'designed after seeing earlier OOS priority-audit results; historical returns are not a fresh holdout',
            'current_pct': 'current priority transformed to a within-strategy empirical percentile using fold TRAIN only',
            'quality_pct': 'signal-day quality transformed to a within-strategy empirical percentile using fold TRAIN only',
            'hybrid_50': 'fixed 50:50 current_pct and quality_pct; included only to decompose the already-observed audit result',
            'allocation': 'desired position ignores remaining cash but respects risk budget and max-share cap; actual position additionally respects remaining cash',
            'equity': 'daily_close_mark_to_market',
        },
        'families': families,
        'notes': [
            '이 진단은 기존 OOS 결과를 본 뒤 원인을 분해하기 위해 추가한 사후진단이므로 새로운 검증표로 취급하지 않습니다.',
            'current_pct가 current보다 좋아진다면 전략별 raw priority의 척도 불일치가 원인 후보입니다.',
            'quality_pct가 current_pct보다 추가 개선되면 신호일 품질 feature의 정렬력이 별도로 존재할 가능성이 있습니다.',
            'cash_limited_entries는 순서가 뒤여서 목표 포지션보다 적은 금액만 배정된 체결을 뜻합니다.',
            'production/실거래 priority는 이 파일로 자동 변경하지 않습니다.',
            'survivorship bias는 여전히 남아 있습니다.',
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    for family in families:
        print('\n', family['name'])
        for rid, _ in RANKERS:
            x = family['summary']['rules'][rid]
            print(rid, 'ret', x['stitched_test_return_pct'], 'mdd', x['worst_test_mdd_pct'], 'cash_limited', x['cash_limited_entries'], 'cash_rejects', x['cash_exhausted_rejects'])
        print('2024', family['summary'].get('test_2024'))


if __name__ == '__main__':
    main()
