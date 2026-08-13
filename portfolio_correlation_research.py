from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from statistics import mean

import numpy as np
import pandas as pd

from config import (
    BACKTEST_INITIAL_CAPITAL_KRW,
    BACKTEST_MAX_POSITION_PCT,
    BACKTEST_MAX_POSITIONS,
    BACKTEST_RISK_PER_TRADE_PCT,
)
from gap_guard_research import _signal_candidates, simulate_variant
from market_data import load_price_history
from portfolio_backtest import _equity_at_cost, _position_notional, _stress_equity, simulate_portfolio
from rsi2_broad_regime_research import MIN_HISTORY_ROWS, research_universe
from structural_stop_research import STRATEGIES, STRATEGY_NAMES

OUT = Path('artifacts/portfolio_correlation_research.json')
TARGET_SYMBOLS = 60
LOOKBACK = 60
MIN_OVERLAP = 40
POLICIES = {
    'baseline_rr': {'mode': 'baseline'},
    'low_corr_priority': {'mode': 'priority'},
    'hard_corr_0_75': {'mode': 'hard', 'threshold': 0.75},
    'hard_corr_0_60': {'mode': 'hard', 'threshold': 0.60},
    'half_risk_above_0_75': {'mode': 'half_risk', 'threshold': 0.75},
}


def trailing_corr(returns_by_symbol: dict[str, pd.Series], a: str, b: str, asof: str, lookback: int = LOOKBACK):
    if not a or not b:
        return None
    if a == b:
        return 1.0
    sa = returns_by_symbol.get(a); sb = returns_by_symbol.get(b)
    if sa is None or sb is None:
        return None
    end = pd.Timestamp(asof)
    joined = pd.concat([sa.loc[:end].rename('a'), sb.loc[:end].rename('b')], axis=1, join='inner').dropna().tail(lookback)
    if len(joined) < MIN_OVERLAP:
        return None
    value = joined['a'].corr(joined['b'])
    if value is None or not np.isfinite(value):
        return None
    return float(value)


def max_positive_corr(trade: dict, peers: list[dict], returns_by_symbol: dict[str, pd.Series]):
    vals = []
    for peer in peers:
        value = trailing_corr(returns_by_symbol, str(trade.get('symbol')), str(peer.get('symbol')), str(trade.get('signal_date') or trade.get('entry_date')))
        if value is not None:
            vals.append((float(value), str(peer.get('symbol'))))
    if not vals:
        return None, None
    value, symbol = max(vals, key=lambda x: x[0])
    return value, symbol


def _corr_band(value):
    if value is None:
        return 'no_peer_or_data'
    if value >= .75:
        return 'corr_ge_0_75'
    if value >= .60:
        return 'corr_0_60_0_75'
    if value >= .30:
        return 'corr_0_30_0_60'
    return 'corr_lt_0_30'


def simulate_correlation_portfolio(trades, returns_by_symbol, policy='baseline_rr'):
    cfg = POLICIES[policy]
    initial = float(BACKTEST_INITIAL_CAPITAL_KRW)
    max_positions = int(BACKTEST_MAX_POSITIONS)
    risk_per_trade = float(BACKTEST_RISK_PER_TRADE_PCT)
    max_position_pct = float(BACKTEST_MAX_POSITION_PCT)

    entries = defaultdict(list); exits = defaultdict(list)
    for seq, original in enumerate(trades):
        t = dict(original); t['_seq'] = seq
        if t.get('entry_date') and t.get('exit_date'):
            entries[str(t['entry_date'])].append(t); exits[str(t['exit_date'])].append(t)
    dates = sorted(set(entries) | set(exits))
    cash = initial; positions = {}; accepted = []
    rejected_capacity = rejected_cash = rejected_corr = 0
    peak = stress_peak = initial; max_dd = stress_dd = 0.0; max_concurrent = 0
    corr_bands = defaultdict(lambda: {'trades':0,'wins':0,'return_sum':0.0,'notional_sum':0.0,'pnl_krw':0.0})

    for day in dates:
        remaining = list(entries.get(day, []))
        while remaining:
            if len(positions) >= max_positions:
                rejected_capacity += len(remaining); break
            peers = [p['trade'] for p in positions.values()]
            scored = []
            for t in remaining:
                corr, peer = max_positive_corr(t, peers, returns_by_symbol)
                if cfg['mode'] == 'priority':
                    key = (corr if corr is not None else -1.0, -float(t.get('risk_reward') or 0), str(t.get('symbol') or ''), int(t['_seq']))
                else:
                    key = (-float(t.get('risk_reward') or 0), str(t.get('symbol') or ''), int(t['_seq']))
                scored.append((key, t, corr, peer))
            scored.sort(key=lambda x: x[0])
            _, trade, corr, peer = scored[0]
            remaining = [x for x in remaining if int(x['_seq']) != int(trade['_seq'])]

            if cfg['mode'] == 'hard' and corr is not None and corr >= float(cfg['threshold']):
                rejected_corr += 1
                continue

            equity = _equity_at_cost(cash, positions)
            risk_multiplier = .5 if cfg['mode'] == 'half_risk' and corr is not None and corr >= float(cfg['threshold']) else 1.0
            notional = _position_notional(
                equity, cash, float(trade.get('risk_pct') or 0),
                risk_per_trade * risk_multiplier, max_position_pct,
            )
            if notional < 1.0:
                rejected_cash += 1; continue

            key = int(trade['_seq'])
            positions[key] = {'trade': trade, 'notional_krw': notional, 'max_corr': corr, 'corr_peer': peer}
            cash -= notional
            accepted.append({
                'seq': key, 'symbol': trade.get('symbol'), 'strategy_id': trade.get('strategy_id'),
                'signal_date': trade.get('signal_date'), 'entry_date': trade.get('entry_date'), 'exit_date': trade.get('exit_date'),
                'notional_krw': round(notional, 0), 'risk_pct': float(trade.get('risk_pct') or 0),
                'risk_reward': float(trade.get('risk_reward') or 0), 'ret': float(trade.get('ret') or 0),
                'max_corr_at_entry': None if corr is None else round(float(corr), 4), 'corr_peer': peer,
                'corr_band': _corr_band(corr), 'risk_multiplier': risk_multiplier,
            })
            max_concurrent = max(max_concurrent, len(positions))

        for trade in sorted(exits.get(day, []), key=lambda t: int(t['_seq'])):
            key = int(trade['_seq']); position = positions.pop(key, None)
            if position is None: continue
            notional = float(position['notional_krw']); ret = float(trade.get('ret') or 0); pnl = notional * ret
            cash += notional + pnl
            band = _corr_band(position.get('max_corr')); x = corr_bands[band]
            x['trades'] += 1; x['wins'] += int(ret > 0); x['return_sum'] += ret; x['notional_sum'] += notional; x['pnl_krw'] += pnl

        equity = _equity_at_cost(cash, positions); peak = max(peak, equity)
        if peak > 0: max_dd = min(max_dd, equity / peak - 1.0)
        stress = _stress_equity(cash, positions); stress_peak = max(stress_peak, stress)
        if stress_peak > 0: stress_dd = min(stress_dd, stress / stress_peak - 1.0)

    if positions:
        for position in positions.values():
            notional=float(position['notional_krw']); ret=float(position['trade'].get('ret') or 0); cash += notional*(1+ret)
        positions.clear()
    ending = cash
    band_summary = {}
    for band, x in corr_bands.items():
        n = x['trades']
        band_summary[band] = {
            'trades': n,
            'win_rate_pct': round(x['wins']/n*100,1) if n else 0.0,
            'avg_return_pct': round(x['return_sum']/n*100,3) if n else 0.0,
            'pnl_krw': round(x['pnl_krw'],0),
            'avg_notional_krw': round(x['notional_sum']/n,0) if n else 0,
        }
    corr_values = [x['max_corr_at_entry'] for x in accepted if x.get('max_corr_at_entry') is not None]
    return {
        'policy': policy,
        'initial_capital_krw': initial,
        'ending_capital_krw': round(ending,0),
        'return_pct': round((ending/initial-1)*100,2),
        'realized_pnl_krw': round(ending-initial,0),
        'max_drawdown_pct': round(max_dd*100,2),
        'stress_drawdown_pct': round(stress_dd*100,2),
        'accepted_trades': len(accepted),
        'rejected_capacity': rejected_capacity,
        'rejected_cash': rejected_cash,
        'rejected_correlation': rejected_corr,
        'max_concurrent_positions': max_concurrent,
        'accepted_with_corr_ge_0_75': sum((x.get('max_corr_at_entry') or -9) >= .75 for x in accepted),
        'accepted_with_corr_ge_0_60': sum((x.get('max_corr_at_entry') or -9) >= .60 for x in accepted),
        'median_max_corr_when_peer_exists': round(float(np.median(corr_values)),4) if corr_values else None,
        'corr_band_results': band_summary,
        'accepted': accepted,
    }


def _bucket(trades, name):
    if name == 'all': return trades
    if name == 'is_first_70pct': return [t for t in trades if t.get('is_is')]
    if name == 'oos_last_30pct': return [t for t in trades if t.get('is_oos')]
    if name == 'recent_2y': return [t for t in trades if t.get('is_recent')]
    raise ValueError(name)


def build_trade_pool():
    requested, source = research_universe(); requested = requested[:TARGET_SYMBOLS]
    returns_by_symbol = {}; trades = []; eligible=[]; errors=[]
    for symbol in requested:
        try:
            d = load_price_history(symbol, '10y').dropna()
            if len(d) < MIN_HISTORY_ROWS:
                errors.append({'symbol':symbol,'error':f'history rows {len(d)} < {MIN_HISTORY_ROWS}'}); continue
            returns_by_symbol[symbol] = d['Close'].astype(float).pct_change()
            frame, candidates = _signal_candidates(d, symbol)
            for sid in STRATEGIES:
                ts, _ = simulate_variant(d, frame, candidates[sid], 'current', symbol=symbol, strategy_id=sid)
                trades.extend(ts)
            eligible.append(symbol)
        except Exception as exc:
            errors.append({'symbol':symbol,'error':str(exc)})
    trades.sort(key=lambda t:(str(t.get('entry_date')), -float(t.get('risk_reward') or 0), str(t.get('symbol') or '')))
    return requested, source, eligible, errors, returns_by_symbol, trades


def run_research():
    requested, source, eligible, errors, returns_by_symbol, trades = build_trade_pool()
    summary = {}
    baseline_match = {}
    for bucket in ('all','is_first_70pct','oos_last_30pct','recent_2y'):
        bt = _bucket(trades, bucket)
        summary[bucket] = {name: simulate_correlation_portfolio(bt, returns_by_symbol, name) for name in POLICIES}
        old = simulate_portfolio(bt)
        new = summary[bucket]['baseline_rr']
        baseline_match[bucket] = {
            'existing_return_pct': old['return_pct'], 'research_return_pct': new['return_pct'],
            'existing_accepted': old['accepted_trades'], 'research_accepted': new['accepted_trades'],
            'return_diff_pct_points': round(float(new['return_pct'])-float(old['return_pct']),6),
        }

    payload = {
        'study':'Trailing-60d correlation concentration in finite max-3-position account',
        'status':'RESEARCH_ONLY',
        'selection_source':source,
        'requested_symbol_count':len(requested),'eligible_symbol_count':len(eligible),'eligible_symbols':eligible,'errors':errors,
        'strategies':STRATEGIES,'strategy_names':STRATEGY_NAMES,
        'candidate_trade_count':len(trades),'lookback_days':LOOKBACK,'minimum_overlap_days':MIN_OVERLAP,
        'policies':POLICIES,'summary':summary,'baseline_match':baseline_match,
        'method_note':'Correlation uses only returns available through the signal date. No future prices enter the candidate selection. Entries remain before same-day exits, matching the conservative portfolio convention.',
        'decision_rule':'First diagnose whether high-correlation entries are frequent and harmful. A hard cap is eligible for later confirmation only if it improves OOS/recent account return or materially reduces stress drawdown without excessive idle-capacity cost. Otherwise keep correlation informational/priority-only.',
        'scope_note':'Current-name broad liquid universe; historical constituent survivorship bias remains.',
    }
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    compact = {b:{p:{k:v[k] for k in ('return_pct','stress_drawdown_pct','accepted_trades','rejected_correlation','accepted_with_corr_ge_0_75','median_max_corr_when_peer_exists')} for p,v in policies.items()} for b,policies in summary.items()}
    print(json.dumps({'eligible':len(eligible),'candidate_trade_count':len(trades),'summary':compact,'baseline_match':baseline_match,'errors_count':len(errors)},ensure_ascii=False,indent=2))
    return payload


if __name__=='__main__':
    run_research()
