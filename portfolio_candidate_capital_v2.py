from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
from statistics import mean, median

import portfolio_priority_audit as audit
import portfolio_walkforward_research as wf
import strategy_optimizer_runner as mtm
import strategy_optimizer_v2 as opt
import strategy_selection_research as selection

POOL = Path('static/replay_backtest_pool_v2.json')
OUT = Path('static/portfolio_candidate_capital_v2.json')

# V1 stays frozen. This file is a separate development-only V2 research track.
FAMILY_ID = 'confirmed_sma_donchian'
QUALITY_INTENSITY = 'loose'  # fixed top 50% within strategy, matching Frozen Challenger V1

# Pre-registered, coarse policies only. No fine-grained grid search.
POLICIES = [
    {
        'id': 'v1_flat',
        'label': 'V1 기준 · 모두 1.0% 위험',
        'description': '품질 상위 50% + 혼합 priority, 통과 후보는 모두 기존 1% 계좌위험 예산',
        'min_conviction': 0.00,
        'low_mult': 1.00,
        'mid_mult': 1.00,
        'high_mult': 1.00,
    },
    {
        'id': 'tiered_all',
        'label': '순위가중 · 0.5 / 0.75 / 1.0%',
        'description': '낮은 확신 후보도 거래하되 위험예산을 절반으로 줄이고 상위 후보에 기존 1%를 유지',
        'min_conviction': 0.00,
        'low_mult': 0.50,
        'mid_mult': 0.75,
        'high_mult': 1.00,
    },
    {
        'id': 'selective',
        'label': '선별형 · 하위 확신 제외',
        'description': '혼합 확신 50% 미만은 건너뛰고 중간 0.75%, 상위 1.0% 위험예산',
        'min_conviction': 0.50,
        'low_mult': 0.00,
        'mid_mult': 0.75,
        'high_mult': 1.00,
    },
    {
        'id': 'high_conviction',
        'label': '집중형 · 상위 확신만',
        'description': '혼합 확신 75% 이상 후보만 기존 1% 위험예산으로 거래',
        'min_conviction': 0.75,
        'low_mult': 0.00,
        'mid_mult': 0.00,
        'high_mult': 1.00,
    },
]


def conviction_tier(value: float) -> str:
    v = float(value)
    if v >= 0.75:
        return 'high'
    if v >= 0.50:
        return 'mid'
    return 'low'


def policy_multiplier(policy: dict, conviction: float) -> float:
    if conviction < float(policy['min_conviction']):
        return 0.0
    tier = conviction_tier(conviction)
    return float(policy[f'{tier}_mult'])


def fixed_pairs(family: dict, candidates: list[dict], fold: dict, executed):
    thresholds = wf.thresholds_for(
        candidates,
        family['strategies'],
        fold['train_start'],
        fold['train_end'],
    )
    allowed = set(family['strategies'])
    pairs = []
    for candidate in candidates:
        sid = candidate.get('strategy_id')
        if sid not in allowed:
            continue
        threshold = thresholds[sid][QUALITY_INTENSITY]
        if threshold is not None and candidate['_quality'] < threshold:
            continue
        row = executed(candidate)
        if row:
            pairs.append((candidate, audit._audit_row(candidate, row)))

    distributions = audit.train_distributions(
        pairs,
        fold['train_start'],
        fold['train_end'],
    )
    ranked = []
    for candidate, raw in pairs:
        row = dict(raw)
        conviction = audit.rank_value('hybrid_50', candidate, row, distributions)
        row['priority'] = conviction
        row['_v2_conviction'] = conviction
        row['_v2_tier'] = conviction_tier(conviction)
        ranked.append(row)
    return thresholds, ranked


def _equity(cash: float, open_positions: dict) -> float:
    return cash + sum(p['size'] * opt.num(p.get('mark'), 1.0) for p in open_positions.values())


def weighted_mtm_portfolio(rows: list[dict], start: date, end: date, capacity: int, policy: dict) -> dict:
    selected = []
    for raw in rows:
        if not (start <= opt.parse_day(raw['start_date']) <= end and opt.parse_day(raw['end_date']) <= end):
            continue
        conviction = float(raw.get('_v2_conviction') or 0.0)
        mult = policy_multiplier(policy, conviction)
        if mult <= 0:
            continue
        row = dict(raw)
        row['_risk_multiplier'] = mult
        selected.append(row)
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
    peak = cash
    max_drawdown = 0.0
    underwater = 0
    max_underwater = 0
    max_open = 0
    open_positions = {}
    open_symbols = set()
    accepted = []
    changes = []
    reject_capacity = 0
    reject_duplicate = 0
    reject_cash = 0
    cash_limited_entries = 0
    requested_capital = 0.0
    allocated_capital = 0.0
    capital_by_tier = defaultdict(float)
    trades_by_tier = defaultdict(int)

    for day in days:
        incoming = sorted(
            starts.get(day, []),
            key=lambda r: (-opt.num(r.get('priority')), str(r.get('key') or ''), r['_seq']),
        )
        for row in incoming:
            symbol = row.get('symbol')
            if symbol and symbol in open_symbols:
                reject_duplicate += 1
                continue
            if len(open_positions) >= capacity:
                reject_capacity += 1
                continue

            total = _equity(cash, open_positions)
            risk_fraction = max(opt.num(row.get('risk_fraction')), 0.001)
            multiplier = max(0.0, opt.num(row.get('_risk_multiplier'), 1.0))
            desired = min(
                total * opt.RISK_BUDGET * multiplier / risk_fraction,
                total * opt.MAX_SHARE,
            )
            actual = min(cash, desired)
            requested_capital += desired
            if actual < 1.0:
                if desired >= 1.0:
                    reject_cash += 1
                continue
            if actual + 1e-6 < desired:
                cash_limited_entries += 1

            tier = str(row.get('_v2_tier') or conviction_tier(row.get('_v2_conviction') or 0.0))
            open_positions[row['_seq']] = {'row': row, 'size': actual, 'mark': 1.0}
            if symbol:
                open_symbols.add(symbol)
            cash -= actual
            allocated_capital += actual
            capital_by_tier[tier] += actual
            trades_by_tier[tier] += 1
            changes.append(opt.num(row.get('change')))
            accepted.append({**row, 'size': actual})
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

        for seq, factor in mark_updates.get(day, ()):
            pos = open_positions.get(seq)
            if pos:
                pos['mark'] = factor

        total = _equity(cash, open_positions)
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
        'cash_limited_entries': cash_limited_entries,
        'underwater_days': max_underwater,
        'requested_capital': requested_capital,
        'allocated_capital': allocated_capital,
        'allocation_ratio': allocated_capital / requested_capital if requested_capital > 0 else 0.0,
        'capital_by_tier': dict(capital_by_tier),
        'trades_by_tier': dict(trades_by_tier),
        'accepted': accepted,
        'mtm': True,
    }


def outcome_values(row: dict) -> dict:
    risk = max(opt.num(row.get('risk_fraction')), 0.001)
    realized = opt.num(row.get('change'))
    mark_returns = [opt.num(x[1], 1.0) - 1.0 for x in row.get('marks') or () if len(x) >= 2]
    mark_returns.append(realized)
    return {
        'trade_pct': realized * 100.0,
        'realized_r': realized / risk,
        'mfe_close_r': max(mark_returns, default=realized) / risk,
        'mae_close_r': min(mark_returns, default=realized) / risk,
    }


def outcome_stats(rows: list[dict]) -> dict:
    vals = [outcome_values(row) for row in rows]
    if not vals:
        return {
            'signals': 0,
            'win_rate_pct': 0.0,
            'avg_trade_pct': 0.0,
            'avg_realized_r': 0.0,
            'median_realized_r': 0.0,
            'avg_mfe_close_r': 0.0,
            'avg_mae_close_r': 0.0,
            'realized_2r_plus_pct': 0.0,
            'realized_loss_08r_pct': 0.0,
        }
    return {
        'signals': len(vals),
        'win_rate_pct': round(sum(1 for x in vals if x['trade_pct'] > 0) / len(vals) * 100.0, 2),
        'avg_trade_pct': round(mean(x['trade_pct'] for x in vals), 3),
        'avg_realized_r': round(mean(x['realized_r'] for x in vals), 3),
        'median_realized_r': round(median(x['realized_r'] for x in vals), 3),
        'avg_mfe_close_r': round(mean(x['mfe_close_r'] for x in vals), 3),
        'avg_mae_close_r': round(mean(x['mae_close_r'] for x in vals), 3),
        'realized_2r_plus_pct': round(sum(1 for x in vals if x['realized_r'] >= 2.0) / len(vals) * 100.0, 2),
        'realized_loss_08r_pct': round(sum(1 for x in vals if x['realized_r'] <= -0.8) / len(vals) * 100.0, 2),
    }


def candidate_diagnostics(rows: list[dict], start: date, end: date) -> dict:
    test_rows = [
        row for row in rows
        if start <= opt.parse_day(row['start_date']) <= end and opt.parse_day(row['end_date']) <= end
    ]
    by_tier = {
        tier: outcome_stats([row for row in test_rows if row.get('_v2_tier') == tier])
        for tier in ('low', 'mid', 'high')
    }

    by_day = defaultdict(list)
    for row in test_rows:
        by_day[row['start_date']].append(row)
    daily_groups = {'rank1': [], 'rank2_3': [], 'rank4_plus': []}
    for day_rows in by_day.values():
        ordered = sorted(day_rows, key=lambda r: (-opt.num(r.get('priority')), str(r.get('key') or '')))
        for idx, row in enumerate(ordered, start=1):
            group = 'rank1' if idx == 1 else ('rank2_3' if idx <= 3 else 'rank4_plus')
            daily_groups[group].append(row)

    return {
        'by_conviction_tier': by_tier,
        'by_same_day_rank': {key: outcome_stats(value) for key, value in daily_groups.items()},
    }


def allocation_meta(result: dict) -> dict:
    total = sum(float(v) for v in (result.get('capital_by_tier') or {}).values())
    shares = {
        tier: round(float((result.get('capital_by_tier') or {}).get(tier, 0.0)) / total, 4) if total > 0 else 0.0
        for tier in ('low', 'mid', 'high')
    }
    return {
        'reject_cash': int(result.get('reject_cash') or 0),
        'reject_capacity': int(result.get('reject_capacity') or 0),
        'cash_limited_entries': int(result.get('cash_limited_entries') or 0),
        'allocation_ratio': round(float(result.get('allocation_ratio') or 0.0), 4),
        'capital_share_by_tier': shares,
        'trades_by_tier': {tier: int((result.get('trades_by_tier') or {}).get(tier, 0)) for tier in ('low', 'mid', 'high')},
    }


def family_fold(family: dict, candidates: list[dict], fold: dict, executed) -> dict:
    thresholds, rows = fixed_pairs(family, candidates, fold, executed)
    policies = {}
    for policy in POLICIES:
        train = weighted_mtm_portfolio(rows, fold['train_start'], fold['train_end'], family['capacity'], policy)
        test = weighted_mtm_portfolio(rows, fold['test_start'], fold['test_end'], family['capacity'], policy)
        policies[policy['id']] = {
            'label': policy['label'],
            'description': policy['description'],
            'train': wf.metric(train),
            'test': wf.metric(test),
            'allocation': allocation_meta(test),
        }
    return {
        'fold': fold['id'],
        'train_start': str(fold['train_start']),
        'train_end': str(fold['train_end']),
        'test_start': str(fold['test_start']),
        'test_end': str(fold['test_end']),
        'quality_intensity': QUALITY_INTENSITY,
        'thresholds': {
            sid: None if thresholds[sid][QUALITY_INTENSITY] is None else round(float(thresholds[sid][QUALITY_INTENSITY]), 6)
            for sid in family['strategies']
        },
        'policies': policies,
        'candidate_diagnostics': candidate_diagnostics(rows, fold['test_start'], fold['test_end']),
    }


def summarize_policy(folds: list[dict], policy_id: str) -> dict:
    tests = [fold['policies'][policy_id]['test'] for fold in folds]
    returns = [x['return_pct'] for x in tests]
    compound = 1.0
    for value in returns:
        compound *= 1.0 + value / 100.0
    baseline = [fold['policies']['v1_flat']['test']['return_pct'] for fold in folds]
    out = {
        'stitched_test_return_pct': round((compound - 1.0) * 100.0, 2),
        'median_test_return_pct': round(median(returns), 2) if returns else 0.0,
        'positive_test_folds': sum(1 for x in returns if x > 0),
        'worst_test_return_pct': round(min(returns), 2) if returns else 0.0,
        'worst_test_mdd_pct': round(min((x['mdd_pct'] for x in tests), default=0.0), 2),
        'total_test_trades': sum(x['trades'] for x in tests),
    }
    if policy_id != 'v1_flat':
        out['folds_beating_v1'] = sum(1 for x, y in zip(returns, baseline) if x > y + 0.01)
        out['mean_delta_vs_v1_pct'] = round(mean(x - y for x, y in zip(returns, baseline)), 2)
    return out


def summarize_diagnostics(folds: list[dict]) -> dict:
    tier_names = ('low', 'mid', 'high')
    rank_names = ('rank1', 'rank2_3', 'rank4_plus')
    tier = {}
    for name in tier_names:
        items = [f['candidate_diagnostics']['by_conviction_tier'][name] for f in folds]
        tier[name] = {
            'signals': sum(x['signals'] for x in items),
            'mean_fold_avg_realized_r': round(mean(x['avg_realized_r'] for x in items if x['signals']), 3) if any(x['signals'] for x in items) else 0.0,
            'mean_fold_avg_trade_pct': round(mean(x['avg_trade_pct'] for x in items if x['signals']), 3) if any(x['signals'] for x in items) else 0.0,
            'folds_positive_avg_r': sum(1 for x in items if x['signals'] and x['avg_realized_r'] > 0),
        }
    ranks = {}
    for name in rank_names:
        items = [f['candidate_diagnostics']['by_same_day_rank'][name] for f in folds]
        ranks[name] = {
            'signals': sum(x['signals'] for x in items),
            'mean_fold_avg_realized_r': round(mean(x['avg_realized_r'] for x in items if x['signals']), 3) if any(x['signals'] for x in items) else 0.0,
            'mean_fold_avg_trade_pct': round(mean(x['avg_trade_pct'] for x in items if x['signals']), 3) if any(x['signals'] for x in items) else 0.0,
        }
    high_beats_low = 0
    rank1_beats_rest = 0
    eligible_high_low = 0
    eligible_rank = 0
    for f in folds:
        c = f['candidate_diagnostics']['by_conviction_tier']
        if c['high']['signals'] and c['low']['signals']:
            eligible_high_low += 1
            high_beats_low += int(c['high']['avg_realized_r'] > c['low']['avg_realized_r'])
        r = f['candidate_diagnostics']['by_same_day_rank']
        if r['rank1']['signals'] and r['rank4_plus']['signals']:
            eligible_rank += 1
            rank1_beats_rest += int(r['rank1']['avg_realized_r'] > r['rank4_plus']['avg_realized_r'])
    return {
        'conviction_tiers': tier,
        'same_day_rank': ranks,
        'high_beats_low_folds': high_beats_low,
        'high_vs_low_eligible_folds': eligible_high_low,
        'rank1_beats_rank4_plus_folds': rank1_beats_rest,
        'rank_comparison_eligible_folds': eligible_rank,
    }


def main() -> None:
    pool = json.loads(POOL.read_text(encoding='utf-8'))
    if not pool.get('ready') or int(pool.get('version') or 0) < 4:
        raise SystemExit('Replay pool V4 is required')

    candidates = list(pool.get('trades') or [])
    for candidate in candidates:
        candidate['_quality'] = selection.quality_score(candidate)

    family = next((f for f in selection.FAMILIES if f['id'] == FAMILY_ID), None)
    if not family:
        raise SystemExit(f'Missing family {FAMILY_ID}')

    folds = wf.folds_for(opt.parse_day(pool['available_start']), opt.parse_day(pool['available_end']))
    if len(folds) < 3:
        raise SystemExit('Not enough rolling folds')

    cache = {}
    def executed(candidate):
        key = (candidate.get('symbol'), candidate.get('strategy_id'), candidate.get('signal_date'))
        if key not in cache:
            cache[key] = mtm.execute_candidate_mtm(candidate, pool, None, None)
        return cache[key]

    fold_rows = [family_fold(family, candidates, fold, executed) for fold in folds]
    policy_summary = {policy['id']: summarize_policy(fold_rows, policy['id']) for policy in POLICIES}

    payload = {
        'version': 1,
        'ready': True,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'pool_generated_at': pool.get('generated_at'),
        'promotion_status': 'development_only_not_fresh_holdout',
        'family': {
            'id': family['id'],
            'name': family['name'],
            'strategies': family['strategies'],
            'capacity': family['capacity'],
        },
        'method': {
            'purpose': 'candidate discrimination and coarse capital-allocation research for a future Challenger V2',
            'v1_untouched': True,
            'quality_filter': 'fixed top 50% within each strategy using each fold TRAIN distribution',
            'ranking': 'fixed hybrid_50 = 50% TRAIN-frozen current-priority percentile + 50% TRAIN-frozen signal-quality percentile',
            'policies': 'four pre-registered coarse structures; no parameter grid and no OOS-based retuning',
            'risk_budget_base_pct': round(opt.RISK_BUDGET * 100.0, 2),
            'max_position_pct': round(opt.MAX_SHARE * 100.0, 2),
            'equity': 'daily_close_mark_to_market',
            'mfe_mae_note': 'candidate MFE/MAE uses daily-close liquidation marks, not intraday extremes',
            'historical_status': 'development data already inspected in prior research; rolling TEST is useful robustness evidence but not a fresh final holdout',
        },
        'policies': [{k: v for k, v in policy.items() if k not in {'low_mult', 'mid_mult', 'high_mult'}} | {
            'risk_multiplier_by_tier': {
                'low': policy['low_mult'], 'mid': policy['mid_mult'], 'high': policy['high_mult']
            }
        } for policy in POLICIES],
        'summary': {
            'fold_count': len(fold_rows),
            'policies': policy_summary,
            'candidate_diagnostics': summarize_diagnostics(fold_rows),
        },
        'folds': fold_rows,
        'notes': [
            'Frozen Challenger V1의 규칙과 forward state는 이 연구가 수정하지 않습니다.',
            'V2 연구에서는 신호일에 알 수 있는 정보만 후보 선택/배분에 사용합니다. 미래수익·MFE·MAE는 결과 진단에만 사용합니다.',
            '상위 후보에 1%보다 더 큰 위험을 싣는 실험은 아직 하지 않습니다. 먼저 낮은 확신 후보의 자본을 줄이거나 제외하는 효과부터 봅니다.',
            '같은 날 후보 중 rank1 성과와 하위 후보 성과를 따로 보고, 점수가 실제로 자본 우선순위를 설명하는지 확인합니다.',
            'survivorship bias는 현재 77종목 과거재생 데이터에 여전히 남아 있습니다.',
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    print('\nCandidate + Capital V2')
    print(family['name'], 'folds', len(fold_rows))
    for policy in POLICIES:
        x = policy_summary[policy['id']]
        print(policy['id'], 'ret', x['stitched_test_return_pct'], 'mdd', x['worst_test_mdd_pct'], 'positive', x['positive_test_folds'], 'trades', x['total_test_trades'], 'beats_v1', x.get('folds_beating_v1'), 'delta', x.get('mean_delta_vs_v1_pct'))
    print('diagnostic', json.dumps(payload['summary']['candidate_diagnostics'], ensure_ascii=False))


if __name__ == '__main__':
    main()
