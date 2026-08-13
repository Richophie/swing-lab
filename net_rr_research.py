from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

import numpy as np

from audit_matrix import SYMBOLS, STRATEGIES, STRATEGY_NAMES
from backtest_engine import (
    _historical_market_state,
    exit_fill_for_bar,
    market_buy_fill,
    market_sell_fill,
    net_trade_return,
)
from config import BACKTEST_COMMISSION_PCT, BACKTEST_HALF_SPREAD_BPS, BACKTEST_SLIPPAGE_BPS
from execution_quality import plan_execution_quality
from market_data import load_price_history
from strategy_rules import ENTRY_GAP_ATR, ENTRY_GAP_PCT, canonical_signal_frame, trade_levels_from_row

OUT = Path('artifacts/net_rr_sensitivity.json')
VARIANTS = {
    'no_rr_filter': {'metric': None, 'threshold': None},
    'gross_1_20': {'metric': 'gross_risk_reward', 'threshold': 1.20},
    'net_1_10': {'metric': 'net_risk_reward', 'threshold': 1.10},
    'net_1_20': {'metric': 'net_risk_reward', 'threshold': 1.20},
    'net_1_30': {'metric': 'net_risk_reward', 'threshold': 1.30},
    'net_1_40': {'metric': 'net_risk_reward', 'threshold': 1.40},
}


def _passes(quality: dict, variant: dict) -> bool:
    metric = variant.get('metric')
    if not metric:
        return True
    return float(quality.get(metric) or 0.0) >= float(variant['threshold'])


def simulate_rr_variant(d, strategy_id: str, variant: dict, *, symbol: str | None = None) -> list[dict]:
    """Simulate one RR rule from scratch so rejected trades free later signals.

    The RR decision occurs on the signal bar using planned levels only. This avoids
    filtering completed trades after seeing outcomes and preserves realistic signal
    availability when a trade is rejected by the candidate RR rule.
    """
    commission = BACKTEST_COMMISSION_PCT / 100.0
    market_state = _historical_market_state(d.index)
    frame = canonical_signal_frame(d, market_state)
    trades = []
    i = 205
    n = len(d)
    while i < n - 2:
        if not bool(frame[strategy_id].iloc[i]):
            i += 1
            continue

        plan = trade_levels_from_row(frame.iloc[i], strategy_id)
        quality = plan_execution_quality(plan)
        if not _passes(quality, variant):
            i += 1
            continue

        entry_i = i + 1
        raw_entry = float(d['Open'].iloc[entry_i])
        gap_guard = max(ENTRY_GAP_ATR * plan['atr'], ENTRY_GAP_PCT * float(frame['close'].iloc[i]))
        if raw_entry < plan['buy_low'] - gap_guard or raw_entry > plan['buy_high'] + gap_guard:
            i += 1
            continue

        entry_fill = market_buy_fill(raw_entry, BACKTEST_SLIPPAGE_BPS, BACKTEST_HALF_SPREAD_BPS)
        target = float(plan['target'])
        stop = float(plan['stop'])
        if not stop < entry_fill < target:
            i += 1
            continue

        max_hold = int(plan['days'][1])
        exit_i = min(entry_i + max_hold, n - 1)
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
        trades.append({
            'symbol': symbol,
            'strategy_id': strategy_id,
            'signal_i': i,
            'signal_date': d.index[i].strftime('%Y-%m-%d'),
            'entry_date': d.index[entry_i].strftime('%Y-%m-%d'),
            'exit_date': d.index[exit_i].strftime('%Y-%m-%d'),
            'ret': float(ret),
            'reason': reason,
            'gross_risk_reward': quality['gross_risk_reward'],
            'net_risk_reward': quality['net_risk_reward'],
            'cost_rr_drag': quality['cost_rr_drag'],
        })
        i = exit_i + 1
    return trades


def pooled_stats(trades: list[dict]) -> dict:
    if not trades:
        return {
            'trades': 0, 'win_rate_pct': 0.0, 'avg_return_pct': 0.0,
            'median_return_pct': 0.0, 'profit_factor': None,
            'avg_gross_rr': None, 'avg_net_rr': None, 'expectancy_pct': 0.0,
            'target_rate_pct': 0.0, 'stop_rate_pct': 0.0, 'time_exit_rate_pct': 0.0,
        }
    r = np.array([float(t['ret']) for t in trades], dtype=float)
    wins = r[r > 0]
    losses = r[r < 0]
    gains = wins.sum()
    loss_abs = -losses.sum()
    reasons = [str(t.get('reason') or '') for t in trades]
    return {
        'trades': len(trades),
        'win_rate_pct': round(float((r > 0).mean() * 100.0), 2),
        'avg_return_pct': round(float(r.mean() * 100.0), 4),
        'median_return_pct': round(float(np.median(r) * 100.0), 4),
        'profit_factor': None if loss_abs <= 0 else round(float(gains / loss_abs), 4),
        'avg_gross_rr': round(float(np.mean([t['gross_risk_reward'] for t in trades])), 4),
        'avg_net_rr': round(float(np.mean([t['net_risk_reward'] for t in trades])), 4),
        'avg_cost_rr_drag': round(float(np.mean([t['cost_rr_drag'] for t in trades])), 4),
        'expectancy_pct': round(float(r.mean() * 100.0), 4),
        'target_rate_pct': round(sum('목표' in x for x in reasons) / len(trades) * 100.0, 2),
        'stop_rate_pct': round(sum('손절' in x for x in reasons) / len(trades) * 100.0, 2),
        'time_exit_rate_pct': round(sum(x == '기간종료' for x in reasons) / len(trades) * 100.0, 2),
    }


def _split_stats(trades: list[dict], split_i: int, recent_start_i: int) -> dict:
    return {
        'full_10y': pooled_stats(trades),
        'is_first_70pct': pooled_stats([t for t in trades if int(t['signal_i']) < split_i]),
        'oos_last_30pct': pooled_stats([t for t in trades if int(t['signal_i']) >= split_i]),
        'recent_2y': pooled_stats([t for t in trades if int(t['signal_i']) >= recent_start_i]),
    }


def current_scan_sensitivity() -> list[dict]:
    try:
        data = json.loads(Path('static/latest_scan.json').read_text(encoding='utf-8'))
    except Exception:
        return []
    rows = []
    for row in data.get('results') or []:
        plans = row.get('strategy_trade_plans') or {}
        for sig in row.get('strategy_signals') or []:
            sid = sig.get('strategy_id')
            if sid not in STRATEGIES or bool(sig.get('experimental')):
                continue
            plan = plans.get(sid)
            if not plan or plan.get('entry_low') is None or plan.get('target') is None or plan.get('stop') is None:
                continue
            try:quality = plan_execution_quality(plan)
            except Exception:continue
            rows.append({
                'symbol': row.get('symbol'),
                'strategy_id': sid,
                'strategy_name': sig.get('strategy_name'),
                'elite_pass_current': bool(sig.get('elite_pass')),
                'elite_score': sig.get('elite_score'),
                'gross_risk_reward': quality['gross_risk_reward'],
                'net_risk_reward': quality['net_risk_reward'],
                'cost_rr_drag': quality['cost_rr_drag'],
                'passes': {name: _passes(quality, rule) for name,rule in VARIANTS.items()},
            })
    return rows


def run_research() -> dict:
    pooled = {name: [] for name in VARIANTS}
    pooled_by_strategy = {name: defaultdict(list) for name in VARIANTS}
    errors = []
    symbol_summaries = []

    for symbol in SYMBOLS:
        try:
            d = load_price_history(symbol, '10y').dropna()
        except Exception as exc:
            errors.append({'symbol':symbol,'error':str(exc)})
            continue
        split_i = int(len(d) * .70)
        recent_start_i = max(205, len(d) - 504)
        for strategy_id in STRATEGIES:
            row = {'symbol':symbol,'strategy_id':strategy_id,'strategy_name':STRATEGY_NAMES[strategy_id],'variants':{}}
            for name, rule in VARIANTS.items():
                try:
                    trades = simulate_rr_variant(d, strategy_id, rule, symbol=symbol)
                    pooled[name].extend(trades)
                    pooled_by_strategy[name][strategy_id].extend(trades)
                    row['variants'][name] = _split_stats(trades, split_i, recent_start_i)
                except Exception as exc:
                    row['variants'][name] = {'error':str(exc)}
            symbol_summaries.append(row)

    # A pooled split by signal_i is not comparable across symbols of different lengths.
    # Build time-bucket labels within each symbol above, then aggregate OOS/recent directly
    # from per-trade dates using a common approximate 10y sample split date.
    all_dates = sorted({t['signal_date'] for trades in pooled['no_rr_filter'] for t in trades})
    common_oos_date = all_dates[int(len(all_dates)*.70)] if all_dates else None
    recent_cutoff = None
    if all_dates:
        last_year = int(all_dates[-1][:4]);recent_cutoff = f'{last_year-2:04d}-{all_dates[-1][5:]}'

    variant_summary = {}
    baseline_n = max(1, len(pooled['no_rr_filter']))
    for name,trades in pooled.items():
        summary = {
            'all': pooled_stats(trades),
            'oos_common_last_30pct_dates': pooled_stats([t for t in trades if common_oos_date and t['signal_date'] >= common_oos_date]),
            'recent_approx_2y': pooled_stats([t for t in trades if recent_cutoff and t['signal_date'] >= recent_cutoff]),
            'coverage_vs_no_rr_pct': round(len(trades)/baseline_n*100.0,2),
            'by_strategy': {sid: pooled_stats(pooled_by_strategy[name][sid]) for sid in STRATEGIES},
        }
        variant_summary[name] = summary

    payload = {
        'study':'Pre-trade cost-aware risk/reward sensitivity',
        'status':'RESEARCH_ONLY_DO_NOT_PROMOTE_FROM_THIS_FILE_ALONE',
        'symbols':SYMBOLS,
        'strategies':STRATEGIES,
        'variants':VARIANTS,
        'execution_assumptions':{
            'commission_pct_per_side':BACKTEST_COMMISSION_PCT,
            'slippage_bps':BACKTEST_SLIPPAGE_BPS,
            'half_spread_bps':BACKTEST_HALF_SPREAD_BPS,
            'target':'limit-style target at raw target minus sell commission',
            'stop':'stop-market at stop less spread/slippage and sell commission',
            'entry':'planned BUY midpoint plus spread/slippage and buy commission',
        },
        'common_oos_date':common_oos_date,
        'recent_cutoff_approx':recent_cutoff,
        'variant_summary':variant_summary,
        'current_scan':current_scan_sensitivity(),
        'symbol_summaries':symbol_summaries,
        'errors':errors,
        'scope_note':'Fixed current-name 20-stock sample. Useful for sensitivity and direction, not a historical-universe profitability proof. Promotion still requires broader pooled/walk-forward validation.',
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'variant_summary':variant_summary,'current_scan':payload['current_scan'],'errors':errors},ensure_ascii=False,indent=2))
    return payload


if __name__=='__main__':run_research()
