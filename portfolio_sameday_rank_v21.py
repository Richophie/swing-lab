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
OUT = Path('static/portfolio_sameday_rank_v21.json')

# One post-hoc structural hypothesis only, derived from V2's candidate diagnostic.
# Do not grid-search cut points: rank1=1.0%, rank2-3=0.75%, rank4+=0.5% risk budget.
RANK_RISK = {
    'rank1': 1.00,
    'rank2_3': 0.75,
    'rank4_plus': 0.50,
}


def rank_bucket(rank: int) -> str:
    if rank <= 1:
        return 'rank1'
    if rank <= 3:
        return 'rank2_3'
    return 'rank4_plus'


def same_day_rank_portfolio(rows: list[dict], start: date, end: date, capacity: int) -> dict:
    """Size by relative rank among that day's non-duplicate eligible candidates.

    Ranking uses only the already-frozen hybrid signal priority. It never uses
    future returns. Existing held symbols and duplicate same-day symbols are
    removed before assigning the effective rank. No candidate is excluded for
    a low rank; lower ranks merely receive a smaller risk budget.
    """
    selected = [
        dict(r) for r in rows
        if start <= opt.parse_day(r['start_date']) <= end and opt.parse_day(r['end_date']) <= end
    ]
    selected.sort(key=lambda r: (r['start_date'], -opt.num(r.get('priority')), str(r.get('key') or '')))

    starts = defaultdict(list)
    ends = defaultdict(list)
    mark_updates = defaultdict(list)
    for seq, raw in enumerate(selected):
        row = dict(raw)
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
    changes = []
    reject_capacity = 0
    reject_duplicate = 0
    reject_cash = 0
    cash_limited_entries = 0
    requested_capital = 0.0
    allocated_capital = 0.0
    capital_by_rank = defaultdict(float)
    trades_by_rank = defaultdict(int)

    def equity():
        return cash + sum(p['size'] * opt.num(p.get('mark'), 1.0) for p in open_positions.values())

    for day in days:
        incoming = sorted(
            starts.get(day, []),
            key=lambda r: (-opt.num(r.get('priority')), str(r.get('key') or ''), r['_seq']),
        )

        # Effective same-day rank is assigned after removing candidates that are
        # already impossible because the symbol is held or duplicated today.
        eligible = []
        day_symbols = set()
        for row in incoming:
            symbol = row.get('symbol')
            if symbol and (symbol in open_symbols or symbol in day_symbols):
                reject_duplicate += 1
                continue
            eligible.append(row)
            if symbol:
                day_symbols.add(symbol)

        for effective_rank, row in enumerate(eligible, start=1):
            if len(open_positions) >= capacity:
                reject_capacity += 1
                continue

            bucket = rank_bucket(effective_rank)
            multiplier = RANK_RISK[bucket]
            total = equity()
            risk_fraction = max(opt.num(row.get('risk_fraction')), 0.001)
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

            row['_v21_same_day_rank'] = effective_rank
            row['_v21_rank_bucket'] = bucket
            row['_v21_risk_multiplier'] = multiplier
            open_positions[row['_seq']] = {'row': row, 'size': actual, 'mark': 1.0}
            symbol = row.get('symbol')
            if symbol:
                open_symbols.add(symbol)
            cash -= actual
            allocated_capital += actual
            capital_by_rank[bucket] += actual
            trades_by_rank[bucket] += 1
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

        for seq, factor in mark_updates.get(day, ()):
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
        'cash_limited_entries': cash_limited_entries,
        'underwater_days': max_underwater,
        'requested_capital': requested_capital,
        'allocated_capital': allocated_capital,
        'allocation_ratio': allocated_capital / requested_capital if requested_capital > 0 else 0.0,
        'capital_by_rank': dict(capital_by_rank),
        'trades_by_rank': dict(trades_by_rank),
        'mtm': True,
    }


def meta(result: dict) -> dict:
    total = sum(float(v) for v in (result.get('capital_by_rank') or {}).values())
    return {
        'reject_cash': int(result.get('reject_cash') or 0),
        'reject_capacity': int(result.get('reject_capacity') or 0),
        'cash_limited_entries': int(result.get('cash_limited_entries') or 0),
        'allocation_ratio': round(float(result.get('allocation_ratio') or 0.0), 4),
        'capital_share_by_rank': {
            bucket: round(float((result.get('capital_by_rank') or {}).get(bucket, 0.0)) / total, 4) if total else 0.0
            for bucket in ('rank1', 'rank2_3', 'rank4_plus')
        },
        'trades_by_rank': {
            bucket: int((result.get('trades_by_rank') or {}).get(bucket, 0))
            for bucket in ('rank1', 'rank2_3', 'rank4_plus')
        },
    }


def family_fold(family: dict, candidates: list[dict], fold: dict, executed) -> dict:
    thresholds, rows = v2.fixed_pairs(family, candidates, fold, executed)
    v1_policy = next(x for x in v2.POLICIES if x['id'] == 'v1_flat')
    tiered_policy = next(x for x in v2.POLICIES if x['id'] == 'tiered_all')

    v1 = v2.weighted_mtm_portfolio(rows, fold['test_start'], fold['test_end'], family['capacity'], v1_policy)
    global_tiered = v2.weighted_mtm_portfolio(rows, fold['test_start'], fold['test_end'], family['capacity'], tiered_policy)
    same_day = same_day_rank_portfolio(rows, fold['test_start'], fold['test_end'], family['capacity'])

    return {
        'fold': fold['id'],
        'train_start': str(fold['train_start']),
        'train_end': str(fold['train_end']),
        'test_start': str(fold['test_start']),
        'test_end': str(fold['test_end']),
        'thresholds': {
            sid: None if thresholds[sid][v2.QUALITY_INTENSITY] is None else round(float(thresholds[sid][v2.QUALITY_INTENSITY]), 6)
            for sid in family['strategies']
        },
        'variants': {
            'v1_flat': {'test': wf.metric(v1)},
            'global_tiered': {'test': wf.metric(global_tiered), 'allocation': v2.allocation_meta(global_tiered)},
            'same_day_rank': {'test': wf.metric(same_day), 'allocation': meta(same_day)},
        },
    }


def summarize(folds: list[dict], variant: str) -> dict:
    tests = [f['variants'][variant]['test'] for f in folds]
    returns = [x['return_pct'] for x in tests]
    compound = 1.0
    for value in returns:
        compound *= 1.0 + value / 100.0
    baseline = [f['variants']['v1_flat']['test']['return_pct'] for f in folds]
    global_tiered = [f['variants']['global_tiered']['test']['return_pct'] for f in folds]
    out = {
        'stitched_test_return_pct': round((compound - 1.0) * 100.0, 2),
        'median_test_return_pct': round(median(returns), 2) if returns else 0.0,
        'positive_test_folds': sum(1 for x in returns if x > 0),
        'worst_test_return_pct': round(min(returns), 2) if returns else 0.0,
        'worst_test_mdd_pct': round(min((x['mdd_pct'] for x in tests), default=0.0), 2),
        'total_test_trades': sum(x['trades'] for x in tests),
    }
    if variant != 'v1_flat':
        out['folds_beating_v1'] = sum(1 for x, y in zip(returns, baseline) if x > y + 0.01)
        out['mean_delta_vs_v1_pct'] = round(mean(x - y for x, y in zip(returns, baseline)), 2)
    if variant == 'same_day_rank':
        out['folds_beating_global_tiered'] = sum(1 for x, y in zip(returns, global_tiered) if x > y + 0.01)
        out['mean_delta_vs_global_tiered_pct'] = round(mean(x - y for x, y in zip(returns, global_tiered)), 2)
    return out


def main() -> None:
    pool = json.loads(POOL.read_text(encoding='utf-8'))
    if not pool.get('ready') or int(pool.get('version') or 0) < 4:
        raise SystemExit('Replay pool V4 is required')

    candidates = list(pool.get('trades') or [])
    for candidate in candidates:
        candidate['_quality'] = selection.quality_score(candidate)

    family = next((f for f in selection.FAMILIES if f['id'] == v2.FAMILY_ID), None)
    if not family:
        raise SystemExit('Missing V2 family')
    folds = wf.folds_for(opt.parse_day(pool['available_start']), opt.parse_day(pool['available_end']))

    cache = {}
    def executed(candidate):
        key = (candidate.get('symbol'), candidate.get('strategy_id'), candidate.get('signal_date'))
        if key not in cache:
            cache[key] = mtm.execute_candidate_mtm(candidate, pool, None, None)
        return cache[key]

    fold_rows = [family_fold(family, candidates, fold, executed) for fold in folds]
    summary = {variant: summarize(fold_rows, variant) for variant in ('v1_flat', 'global_tiered', 'same_day_rank')}

    payload = {
        'version': 1,
        'ready': True,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'pool_generated_at': pool.get('generated_at'),
        'promotion_status': 'posthoc_development_only_not_fresh_holdout',
        'family': {'id': family['id'], 'name': family['name'], 'strategies': family['strategies'], 'capacity': family['capacity']},
        'hypothesis': {
            'source': 'V2 showed same-day rank1 beat rank4+ in 5/6 rolling TEST folds while absolute high-conviction filtering was weak',
            'rule': 'effective same-day rank1 = 1.0% risk budget; rank2-3 = 0.75%; rank4+ = 0.5%',
            'grid_search': False,
            'candidate_exclusion': False,
            'max_risk_budget_pct': 1.0,
        },
        'method': {
            'quality_filter': 'fixed top 50% within strategy using each fold TRAIN only',
            'ranking': 'fixed hybrid_50 using each fold TRAIN distributions only',
            'rank_assignment': 'same-day rank after removing symbols already held or duplicate that day; before cash/capacity allocation',
            'equity': 'daily_close_mark_to_market',
            'v1_untouched': True,
            'warning': 'rule was designed after inspecting V2 historical diagnostics; these TEST returns are robustness/development evidence, not a fresh holdout',
        },
        'summary': summary,
        'folds': fold_rows,
        'notes': [
            'Frozen Challenger V1 is not changed by this experiment.',
            'No candidate is removed because of same-day rank; lower ranks only receive less capital.',
            'No candidate receives more than the existing 1% account-risk budget.',
            'The 1 / 2-3 / 4+ buckets and 1.0 / 0.75 / 0.5 weights are tested once as a structural hypothesis, not searched as a parameter grid.',
            'Current-universe survivorship bias remains.',
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    print('\nSame-day Rank V2.1')
    for key, value in summary.items():
        print(key, 'ret', value['stitched_test_return_pct'], 'mdd', value['worst_test_mdd_pct'], 'positive', value['positive_test_folds'], 'trades', value['total_test_trades'], 'beats_v1', value.get('folds_beating_v1'), 'beats_global', value.get('folds_beating_global_tiered'), 'delta_global', value.get('mean_delta_vs_global_tiered_pct'))
    for fold in fold_rows:
        print(fold['fold'], {k: v['test']['return_pct'] for k, v in fold['variants'].items()})


if __name__ == '__main__':
    main()
