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
OUT = Path('static/opportunity_cost_rotation.json')
BASE_RISK_PCT = 0.75
CAPACITY = 10

# Coarse mechanism checks only. No fine grid search.
POLICIES = {
    'natural': {
        'label': '기준 · 약한 포지션도 자연청산까지 유지',
        'rotate': False,
        'min_age_sessions': None,
        'max_current_r': None,
    },
    'negative_after_5': {
        'label': '5세션+ 손실 포지션 1개 → 오늘 1순위 후보',
        'rotate': True,
        'min_age_sessions': 5,
        'max_current_r': 0.0,
    },
    'stale_after_10': {
        'label': '10세션+ 0.25R 이하 정체 포지션 1개 → 오늘 1순위 후보',
        'rotate': True,
        'min_age_sessions': 10,
        'max_current_r': 0.25,
    },
}


def _costs(pool: dict) -> tuple[float, float]:
    costs = pool.get('costs') or {}
    commission = opt.num(costs.get('commission_pct_per_side'), 0.10) / 100.0
    friction = (opt.num(costs.get('slippage_bps'), 5.0) + opt.num(costs.get('half_spread_bps'), 2.5)) / 10000.0
    return commission, friction


def enriched_execute(candidate: dict, pool: dict) -> dict | None:
    row = mtm.execute_candidate_mtm(candidate, pool, None, None)
    if not row:
        return None
    commission, friction = _costs(pool)
    paid = opt.num(row.get('mtm_entry_paid'))
    if paid <= 0:
        return row
    end_day = str(row.get('end_date') or '')
    opens = {}
    for bar in candidate.get('path') or ():
        day = str(bar[0])
        if end_day and day > end_day:
            break
        raw_open = opt.num(bar[1])
        if raw_open <= 0:
            continue
        received = raw_open * (1.0 - friction) * (1.0 - commission)
        opens[day] = max(0.0, received / paid)
    out = dict(row)
    out['_open_factors'] = opens
    return out


def _equity(cash: float, positions: dict) -> float:
    return cash + sum(p['size'] * opt.num(p.get('mark'), 1.0) for p in positions.values())


def _current_r(pos: dict) -> float:
    risk = max(opt.num(pos['row'].get('risk_fraction')), 0.001)
    return (opt.num(pos.get('mark'), 1.0) - 1.0) / risk


def choose_victim(positions: dict, day: str, policy: dict):
    if not policy.get('rotate'):
        return None
    min_age = int(policy.get('min_age_sessions') or 0)
    max_r = float(policy.get('max_current_r') or 0.0)
    eligible = []
    for seq, pos in positions.items():
        row = pos['row']
        if int(pos.get('age_sessions') or 0) < min_age:
            continue
        # A trade scheduled to finish today is left to its original exit logic.
        if str(row.get('end_date') or '') <= day:
            continue
        if day not in (row.get('_open_factors') or {}):
            continue
        current_r = _current_r(pos)
        if current_r > max_r:
            continue
        eligible.append((current_r, -int(pos.get('age_sessions') or 0), seq, pos))
    if not eligible:
        return None
    eligible.sort(key=lambda x: (x[0], x[1], x[2]))
    return eligible[0][2], eligible[0][3], eligible[0][0]


def regret_after_rotation(row: dict, sale_day: str, sale_factor: float) -> dict:
    risk = max(opt.num(row.get('risk_fraction')), 0.001)
    later = [opt.num(mark[1], 1.0) for mark in row.get('marks') or () if len(mark) >= 2 and str(mark[0]) > sale_day]
    later.append(1.0 + opt.num(row.get('change')))
    future_max = max(later, default=sale_factor)
    sale_return = sale_factor - 1.0
    natural_return = opt.num(row.get('change'))
    return {
        'missed_mfe_from_sale_pct': (future_max / sale_factor - 1.0) * 100.0 if sale_factor > 0 else 0.0,
        'natural_minus_sale_pct_points': (natural_return - sale_return) * 100.0,
        'future_max_r_from_original_entry': (future_max - 1.0) / risk,
        'became_2r_winner_after_sale': (future_max - 1.0) >= 2.0 * risk,
    }


def rotation_portfolio(rows: list[dict], start: date, end: date, policy: dict) -> dict:
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
    positions = {}
    open_symbols = set()
    realized_changes = []
    replacement_changes = []
    replacement_seqs = set()
    holding_sessions = []
    rejects_cash = rejects_capacity = rejects_duplicate = cash_limited = 0
    allocated_total = 0.0
    equity_samples = []
    cash_samples = []
    exposure_samples = []
    open_samples = []
    rotations = []

    def exposure():
        return sum(p['size'] * opt.num(p.get('mark'), 1.0) for p in positions.values())

    def equity():
        return cash + exposure()

    def enter(row: dict) -> tuple[bool, str]:
        nonlocal cash, allocated_total, cash_limited
        if len(positions) >= CAPACITY:
            return False, 'capacity'
        total = equity()
        rf = max(opt.num(row.get('risk_fraction')), 0.001)
        desired = min(total * (BASE_RISK_PCT / 100.0) / rf, total * opt.MAX_SHARE)
        actual = min(cash, desired)
        if actual < 1.0:
            return False, 'cash'
        if actual + 1e-6 < desired:
            cash_limited += 1
        positions[row['_seq']] = {'row': row, 'size': actual, 'mark': 1.0, 'age_sessions': 0}
        symbol = row.get('symbol')
        if symbol:
            open_symbols.add(symbol)
        cash -= actual
        allocated_total += actual
        return True, 'ok'

    for day in days:
        incoming = sorted(starts.get(day, []), key=lambda r: (-opt.num(r.get('priority')), str(r.get('key') or ''), r['_seq']))
        top_request_available = True
        for row in incoming:
            symbol = row.get('symbol')
            if symbol and symbol in open_symbols:
                rejects_duplicate += 1
                continue

            is_top_request = top_request_available
            top_request_available = False
            entered, reason = enter(row)
            if entered:
                continue

            rotated = False
            if is_top_request and policy.get('rotate') and reason in {'cash', 'capacity'}:
                picked = choose_victim(positions, day, policy)
                if picked:
                    victim_seq, victim, victim_r = picked
                    victim_row = victim['row']
                    sale_factor = opt.num((victim_row.get('_open_factors') or {}).get(day))
                    if sale_factor > 0:
                        sale_value = victim['size'] * sale_factor
                        sale_change = sale_factor - 1.0
                        cash += sale_value
                        realized_changes.append(sale_change)
                        holding_sessions.append(int(victim.get('age_sessions') or 0))
                        victim_symbol = victim_row.get('symbol')
                        if victim_symbol:
                            open_symbols.discard(victim_symbol)
                        del positions[victim_seq]
                        regret = regret_after_rotation(victim_row, day, sale_factor)
                        rotations.append({
                            'day': day,
                            'sold_symbol': victim_symbol,
                            'new_symbol': row.get('symbol'),
                            'sold_current_r': round(victim_r, 3),
                            'sold_age_sessions': int(victim.get('age_sessions') or 0),
                            'sale_change_pct': round(sale_change * 100.0, 3),
                            **regret,
                        })
                        entered_after, reason_after = enter(row)
                        if entered_after:
                            replacement_seqs.add(row['_seq'])
                            rotated = True
                        else:
                            # Keep the portfolio self-consistent even if the freed cash was still insufficient.
                            reason = reason_after
            if rotated:
                continue
            if reason == 'capacity':
                rejects_capacity += 1
            elif reason == 'cash':
                rejects_cash += 1

        for row in sorted(ends.get(day, []), key=lambda r: r['_seq']):
            pos = positions.get(row['_seq'])
            if not pos:
                continue
            change = opt.num(row.get('change'))
            cash += pos['size'] * (1.0 + change)
            realized_changes.append(change)
            if row['_seq'] in replacement_seqs:
                replacement_changes.append(change)
            holding_sessions.append(int(pos.get('age_sessions') or 0))
            symbol = pos['row'].get('symbol')
            if symbol:
                open_symbols.discard(symbol)
            del positions[row['_seq']]

        for seq, factor in marks.get(day, ()):
            pos = positions.get(seq)
            if pos:
                pos['mark'] = factor
                pos['age_sessions'] = int(pos.get('age_sessions') or 0) + 1

        total = equity()
        expo = exposure()
        if total > 0:
            equity_samples.append(total)
            cash_samples.append(cash / total)
            exposure_samples.append(expo / total)
        open_samples.append(len(positions))
        peak = max(peak, total)
        if peak > 0:
            mdd = min(mdd, total / peak - 1.0)

    # All selected natural exits are within `end`; this is only a safety fallback.
    for pos in list(positions.values()):
        change = opt.num(pos['row'].get('change'))
        cash += pos['size'] * (1.0 + change)
        realized_changes.append(change)

    years = max((end - start).days / 365.25, 0.25)
    avg_equity = mean(equity_samples) if equity_samples else opt.INITIAL_CAPITAL
    regrets = rotations
    return {
        'ending': cash,
        'return': cash / opt.INITIAL_CAPITAL - 1.0,
        'cagr': (cash / opt.INITIAL_CAPITAL) ** (1.0 / years) - 1.0 if cash > 0 else -1.0,
        'mdd': mdd,
        'trades': len(realized_changes),
        'win_rate': sum(x > 0 for x in realized_changes) / len(realized_changes) if realized_changes else 0.0,
        'avg_trade': mean(realized_changes) if realized_changes else 0.0,
        'trades_per_year': len(realized_changes) / years,
        'max_open': max(open_samples, default=0),
        'underwater_days': 0,
        'rotations': len(rotations),
        'reject_cash': rejects_cash,
        'reject_capacity': rejects_capacity,
        'reject_duplicate': rejects_duplicate,
        'cash_limited_entries': cash_limited,
        'avg_cash_pct': mean(cash_samples) * 100.0 if cash_samples else 100.0,
        'avg_exposure_pct': mean(exposure_samples) * 100.0 if exposure_samples else 0.0,
        'avg_open_positions': mean(open_samples) if open_samples else 0.0,
        'avg_holding_sessions': mean(holding_sessions) if holding_sessions else 0.0,
        'notional_turns_per_year': allocated_total / max(avg_equity, 1.0) / years,
        'replacement_trades': len(replacement_changes),
        'replacement_win_rate': sum(x > 0 for x in replacement_changes) / len(replacement_changes) if replacement_changes else 0.0,
        'replacement_avg_trade': mean(replacement_changes) if replacement_changes else 0.0,
        'regret_big_winners': sum(1 for r in regrets if r['became_2r_winner_after_sale']),
        'mean_missed_mfe_from_sale_pct': mean(r['missed_mfe_from_sale_pct'] for r in regrets) if regrets else 0.0,
        'mean_natural_minus_sale_pct_points': mean(r['natural_minus_sale_pct_points'] for r in regrets) if regrets else 0.0,
        'rotation_events': rotations,
    }


def compact(x: dict) -> dict:
    base = wf.metric(x)
    base.update({
        'rotations': int(x['rotations']),
        'reject_cash': int(x['reject_cash']),
        'reject_capacity': int(x['reject_capacity']),
        'cash_limited_entries': int(x['cash_limited_entries']),
        'avg_cash_pct': round(x['avg_cash_pct'], 1),
        'avg_exposure_pct': round(x['avg_exposure_pct'], 1),
        'avg_open_positions': round(x['avg_open_positions'], 2),
        'avg_holding_sessions': round(x['avg_holding_sessions'], 1),
        'notional_turns_per_year': round(x['notional_turns_per_year'], 2),
        'replacement_trades': int(x['replacement_trades']),
        'replacement_win_rate_pct': round(x['replacement_win_rate'] * 100.0, 2),
        'replacement_avg_trade_pct': round(x['replacement_avg_trade'] * 100.0, 3),
        'regret_big_winners': int(x['regret_big_winners']),
        'mean_missed_mfe_from_sale_pct': round(x['mean_missed_mfe_from_sale_pct'], 2),
        'mean_natural_minus_sale_pct_points': round(x['mean_natural_minus_sale_pct_points'], 2),
    })
    return base


def summarize(folds: list[dict], key: str) -> dict:
    vals = [f['variants'][key] for f in folds]
    returns = [x['return_pct'] for x in vals]
    compound = 1.0
    for value in returns:
        compound *= 1.0 + value / 100.0
    ref = [f['variants']['natural']['return_pct'] for f in folds]
    out = {
        'stitched_test_return_pct': round((compound - 1.0) * 100.0, 2),
        'positive_folds': sum(x > 0 for x in returns),
        'median_test_return_pct': round(median(returns), 2),
        'worst_test_return_pct': round(min(returns), 2),
        'worst_mdd_pct': round(min(x['mdd_pct'] for x in vals), 2),
        'total_trades': sum(x['trades'] for x in vals),
        'total_rotations': sum(x['rotations'] for x in vals),
        'total_cash_rejects': sum(x['reject_cash'] for x in vals),
        'total_capacity_rejects': sum(x['reject_capacity'] for x in vals),
        'mean_avg_cash_pct': round(mean(x['avg_cash_pct'] for x in vals), 1),
        'mean_notional_turns_per_year': round(mean(x['notional_turns_per_year'] for x in vals), 2),
        'mean_avg_holding_sessions': round(mean(x['avg_holding_sessions'] for x in vals), 1),
        'total_regret_big_winners': sum(x['regret_big_winners'] for x in vals),
        'mean_missed_mfe_from_sale_pct': round(mean(x['mean_missed_mfe_from_sale_pct'] for x in vals), 2),
        'mean_natural_minus_sale_pct_points': round(mean(x['mean_natural_minus_sale_pct_points'] for x in vals), 2),
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
    for candidate in candidates:
        candidate['_quality'] = selection.quality_score(candidate)
    family = next(f for f in selection.FAMILIES if f['id'] == v2.FAMILY_ID)
    folds = wf.folds_for(opt.parse_day(pool['available_start']), opt.parse_day(pool['available_end']))
    cache = {}

    def executed(candidate):
        key = (candidate.get('symbol'), candidate.get('strategy_id'), candidate.get('signal_date'))
        if key not in cache:
            cache[key] = enriched_execute(candidate, pool)
        return cache[key]

    fold_rows = []
    for fold in folds:
        _, rows = v2.fixed_pairs(family, candidates, fold, executed)
        variants = {key: compact(rotation_portfolio(rows, fold['test_start'], fold['test_end'], policy)) for key, policy in POLICIES.items()}
        fold_rows.append({
            'fold': fold['id'],
            'test_start': str(fold['test_start']),
            'test_end': str(fold['test_end']),
            'variants': variants,
        })

    summary = {key: summarize(fold_rows, key) for key in POLICIES}
    payload = {
        'version': 1,
        'ready': True,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'promotion_status': 'development_only_opportunity_cost_rotation_not_fresh_holdout',
        'method': {
            'family': family.get('name') or family['id'],
            'quality_gate': 'TRAIN strategy top 50%',
            'priority': 'TRAIN hybrid_50',
            'base_risk_pct': BASE_RISK_PCT,
            'capacity': CAPACITY,
            'new_candidate_trigger': 'only the first non-duplicate candidate of that entry day can evict a position, and only when it would otherwise be rejected for cash or capacity',
            'victim_information': 'previous completed close mark + completed holding sessions only',
            'replacement_execution': 'sell existing position at same-day open liquidation estimate, then buy new candidate at its planned open',
            'winner_protection': 'rotation policies only allow current R at or below their low threshold; strong winners are not evicted',
            'regret_audit': 'track whether the sold position later became a 2R winner and its post-sale MFE',
            'grid_search': False,
            'v1_v2_forward_untouched': True,
            'historical_status': 'development data already inspected; rolling TEST is mechanism evidence, not pristine final holdout',
        },
        'policies': {k: v for k, v in POLICIES.items()},
        'folds': fold_rows,
        'summary': summary,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Opportunity-cost rotation research')
    for key, value in summary.items():
        print(key, 'ret', value['stitched_test_return_pct'], 'mdd', value['worst_mdd_pct'], 'rot', value['total_rotations'], 'cashrej', value['total_cash_rejects'], 'beat', value.get('folds_beating_reference'))


if __name__ == '__main__':
    main()
