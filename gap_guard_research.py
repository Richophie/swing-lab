from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_engine import (
    _historical_market_state,
    exit_fill_for_bar,
    market_buy_fill,
    market_sell_fill,
    net_trade_return,
)
from config import (
    BACKTEST_COMMISSION_PCT,
    BACKTEST_HALF_SPREAD_BPS,
    BACKTEST_SLIPPAGE_BPS,
    S_THRESHOLD,
)
from execution_quality import plan_execution_quality
from market_data import load_price_history
from net_rr_research import pooled_stats
from portfolio_backtest import simulate_portfolio
from rsi2_broad_regime_research import MIN_HISTORY_ROWS, research_universe
from structural_stop_research import (
    STRATEGIES,
    STRATEGY_NAMES,
    historical_features,
    plan_from_row,
    selection_pass,
)
from strategy_rules import canonical_signal_frame

OUT = Path('artifacts/gap_guard_research.json')
TARGET_SYMBOLS = 60

VARIANTS = {
    'current': {'down': 'current', 'up': 'current'},
    'zone_only': {'down': 0.0, 'up': 0.0},
    'atr_0_25': {'down': 0.25, 'up': 0.25},
    'atr_0_50': {'down': 0.50, 'up': 0.50},
    'atr_0_75': {'down': 0.75, 'up': 0.75},
    'down_0_25_up_current': {'down': 0.25, 'up': 'current'},
    'down_current_up_0_25': {'down': 'current', 'up': 0.25},
}


def guard_sides(plan: dict, signal_close: float, variant: str) -> tuple[float, float]:
    cfg = VARIANTS[variant]
    atr = float(plan['atr'])
    current = max(0.75 * atr, 0.01 * float(signal_close))

    def side(value):
        if value == 'current':
            return current
        return max(0.0, float(value)) * atr

    return side(cfg['down']), side(cfg['up'])


def open_relation(raw_open: float, buy_low: float, buy_high: float, atr: float) -> tuple[str, float]:
    o = float(raw_open); low = float(buy_low); high = float(buy_high); a = max(float(atr), 1e-12)
    if o < low:
        return 'below_buy_zone', (low - o) / a
    if o > high:
        return 'above_buy_zone', (o - high) / a
    return 'inside_buy_zone', 0.0


def _signal_candidates(d: pd.DataFrame, symbol: str) -> tuple[pd.DataFrame, dict[str, dict[int, dict]]]:
    """Build live-like signal-day candidates with current force-1.5ATR STOP.

    The existing signal-day entry_viable policy remains inside selection_pass. This
    study changes only the *next-open* acceptance guard so the variable is isolated.
    """
    state = _historical_market_state(d.index)
    frame = canonical_signal_frame(d, state)
    features = historical_features(d, state, frame)
    candidates = {sid: {} for sid in STRATEGIES}

    for sid in STRATEGIES:
        scores = features['scores'][sid]
        flows = features['flows']
        overlay = features['overlay']
        for i in range(205, len(d) - 2):
            if not bool(frame[sid].iloc[i]) or float(scores.iloc[i]) < S_THRESHOLD:
                continue
            plan = plan_from_row(frame.iloc[i], sid, 'force_1_50')
            flow_row = flows.iloc[i]
            flow = {k: (None if pd.isna(v) else float(v)) for k, v in flow_row.items()}
            selected = selection_pass(
                float(scores.iloc[i]), flow, plan, str(state.iloc[i]),
                bool(overlay.iloc[i]), float(frame['close'].iloc[i]), sid,
            )
            if not selected.get('pass'):
                continue
            try:
                q = plan_execution_quality(plan)
            except Exception:
                continue
            candidates[sid][i] = {
                'symbol': symbol,
                'strategy_id': sid,
                'plan': plan,
                'strategy_score': float(scores.iloc[i]),
                'elite_score': float(selected['elite_score']),
                'flow_score': float(selected['flow_score']),
                'market_state': str(state.iloc[i]),
                'gross_risk_reward': float(q['gross_risk_reward']),
                'net_risk_reward': float(q['net_risk_reward']),
                'cost_rr_drag': float(q['cost_rr_drag']),
            }
    return frame, candidates


def simulate_variant(
    d: pd.DataFrame,
    frame: pd.DataFrame,
    candidates: dict[int, dict],
    variant: str,
    *,
    symbol: str,
    strategy_id: str,
) -> tuple[list[dict], dict]:
    commission = BACKTEST_COMMISSION_PCT / 100.0
    trades = []
    diag = defaultdict(int)
    distances = []
    i = 205
    n = len(d)
    split_i = max(205, int(n * .70))
    recent_i = max(205, n - 504)

    while i < n - 2:
        info = candidates.get(i)
        if info is None:
            i += 1
            continue
        diag['signal_day_selected'] += 1
        plan = info['plan']
        entry_i = i + 1
        raw_open = float(d['Open'].iloc[entry_i])
        signal_close = float(frame['close'].iloc[i])
        relation, distance_atr = open_relation(raw_open, plan['buy_low'], plan['buy_high'], plan['atr'])
        diag[f'relation_{relation}'] += 1
        if relation != 'inside_buy_zone':
            distances.append(float(distance_atr))

        down_guard, up_guard = guard_sides(plan, signal_close, variant)
        if raw_open < float(plan['buy_low']) - down_guard:
            diag['rejected_below_guard'] += 1
            i += 1
            continue
        if raw_open > float(plan['buy_high']) + up_guard:
            diag['rejected_above_guard'] += 1
            i += 1
            continue

        entry_fill = market_buy_fill(raw_open, BACKTEST_SLIPPAGE_BPS, BACKTEST_HALF_SPREAD_BPS)
        target = float(plan['target']); stop = float(plan['stop'])
        if not stop < entry_fill < target:
            diag['invalid_fill_reject'] += 1
            i += 1
            continue

        exit_i = min(entry_i + int(plan['days'][1]), n - 1)
        raw_exit = float(d['Close'].iloc[exit_i])
        exit_fill = market_sell_fill(raw_exit, BACKTEST_SLIPPAGE_BPS, BACKTEST_HALF_SPREAD_BPS)
        reason = '기간종료'
        for j in range(entry_i, exit_i + 1):
            bar = d.iloc[j]
            outcome = exit_fill_for_bar(
                bar['Open'], bar['High'], bar['Low'], target, stop,
                BACKTEST_SLIPPAGE_BPS, BACKTEST_HALF_SPREAD_BPS,
            )
            if outcome is not None:
                exit_fill, reason, raw_exit = outcome
                exit_i = j
                break

        ret = net_trade_return(entry_fill, exit_fill, commission)
        actual_risk = entry_fill - stop
        actual_reward = target - entry_fill
        diag['accepted'] += 1
        diag[f'accepted_{relation}'] += 1
        trades.append({
            'symbol': symbol,
            'strategy_id': strategy_id,
            'variant': variant,
            'signal_i': i,
            'signal_date': d.index[i].strftime('%Y-%m-%d'),
            'entry_date': d.index[entry_i].strftime('%Y-%m-%d'),
            'exit_date': d.index[exit_i].strftime('%Y-%m-%d'),
            'ret': float(ret),
            'reason': reason,
            'risk_pct': actual_risk / entry_fill if entry_fill > 0 else 0.0,
            'risk_reward': actual_reward / actual_risk if actual_risk > 0 else 0.0,
            'gross_risk_reward': float(info['gross_risk_reward']),
            'net_risk_reward': float(info['net_risk_reward']),
            'cost_rr_drag': float(info['cost_rr_drag']),
            'elite_score': float(info['elite_score']),
            'flow_score': float(info['flow_score']),
            'market_state': info['market_state'],
            'open_relation': relation,
            'outside_zone_atr': round(float(distance_atr), 6),
            'down_guard_atr': round(down_guard / float(plan['atr']), 6),
            'up_guard_atr': round(up_guard / float(plan['atr']), 6),
            'is_is': i < split_i,
            'is_oos': i >= split_i,
            'is_recent': i >= recent_i,
        })
        i = exit_i + 1

    diag['avg_outside_zone_atr_seen'] = round(float(np.mean(distances)), 4) if distances else None
    return trades, dict(diag)


def bucket(trades: list[dict], name: str) -> list[dict]:
    if name == 'all': return trades
    if name == 'is_first_70pct': return [t for t in trades if t['is_is']]
    if name == 'oos_last_30pct': return [t for t in trades if t['is_oos']]
    if name == 'recent_2y': return [t for t in trades if t['is_recent']]
    raise ValueError(name)


def relation_stats(trades: list[dict]) -> dict:
    return {
        relation: pooled_stats([t for t in trades if t.get('open_relation') == relation])
        for relation in ('inside_buy_zone', 'below_buy_zone', 'above_buy_zone')
    }


def run_research() -> dict:
    requested, source = research_universe()
    requested = requested[:TARGET_SYMBOLS]
    eligible = []
    errors = []
    variant_trades = {name: [] for name in VARIANTS}
    diagnostics = {name: defaultdict(int) for name in VARIANTS}
    per_symbol = []

    for symbol in requested:
        try:
            d = load_price_history(symbol, '10y').dropna()
            if len(d) < MIN_HISTORY_ROWS:
                errors.append({'symbol': symbol, 'error': f'history rows {len(d)} < {MIN_HISTORY_ROWS}'})
                continue
            frame, candidates_by_strategy = _signal_candidates(d, symbol)
            eligible.append(symbol)
        except Exception as exc:
            errors.append({'symbol': symbol, 'error': str(exc)})
            continue

        row = {'symbol': symbol, 'variants': {}}
        for variant in VARIANTS:
            row['variants'][variant] = {}
            for sid in STRATEGIES:
                try:
                    trades, diag = simulate_variant(
                        d, frame, candidates_by_strategy[sid], variant,
                        symbol=symbol, strategy_id=sid,
                    )
                    variant_trades[variant].extend(trades)
                    row['variants'][variant][sid] = {'trades': len(trades), 'diagnostics': diag}
                    for key, value in diag.items():
                        if isinstance(value, int): diagnostics[variant][key] += value
                except Exception as exc:
                    row['variants'][variant][sid] = {'error': str(exc)}
        per_symbol.append(row)

    summary = {}
    for variant, trades in variant_trades.items():
        summary[variant] = {}
        for b in ('all', 'is_first_70pct', 'oos_last_30pct', 'recent_2y'):
            bt = bucket(trades, b)
            stats = pooled_stats(bt)
            portfolio = simulate_portfolio(bt)
            stats['portfolio'] = {k: portfolio.get(k) for k in (
                'return_pct','realized_pnl_krw','max_drawdown_pct','stress_drawdown_pct',
                'accepted_trades','win_rate_pct','avg_position_krw','max_concurrent_positions',
                'rejected_capacity','rejected_cash',
            )}
            stats['by_strategy'] = {
                sid: pooled_stats([t for t in bt if t['strategy_id'] == sid]) for sid in STRATEGIES
            }
            stats['by_next_open_relation'] = relation_stats(bt)
            summary[variant][b] = stats
        summary[variant]['diagnostics'] = dict(diagnostics[variant])

    # Current-policy relation table is especially useful for deciding whether a
    # second-stage asymmetric per-strategy study is justified.
    current_relation_by_strategy = {}
    for sid in STRATEGIES:
        current_relation_by_strategy[sid] = {}
        sid_trades = [t for t in variant_trades['current'] if t['strategy_id'] == sid]
        for b in ('all','oos_last_30pct','recent_2y'):
            current_relation_by_strategy[sid][b] = relation_stats(bucket(sid_trades, b))

    payload = {
        'study': 'Next-open gap guard width and directionality',
        'status': 'RESEARCH_ONLY',
        'selection_source': source,
        'requested_symbol_count': len(requested),
        'eligible_symbol_count': len(eligible),
        'eligible_symbols': eligible,
        'errors': errors,
        'strategies': STRATEGIES,
        'strategy_names': STRATEGY_NAMES,
        'variants': VARIANTS,
        'variant_summary': summary,
        'current_relation_by_strategy': current_relation_by_strategy,
        'symbol_results': per_symbol,
        'isolation_note': 'Signal-day entry_viable remains on current production logic. Only next-session open acceptance is varied.',
        'current_policy': 'down/up guard = max(0.75 ATR, 1% signal close)',
        'decision_rule': 'First determine whether width or direction matters consistently in OOS/recent and finite-account results. Do not invent strategy-specific asymmetry until this broad first-stage study supports it.',
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'eligible_symbol_count': len(eligible),
        'variant_summary': summary,
        'current_relation_by_strategy': current_relation_by_strategy,
        'errors_count': len(errors),
    }, ensure_ascii=False, indent=2))
    return payload


if __name__ == '__main__':
    run_research()
