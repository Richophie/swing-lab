from __future__ import annotations

import math
import numpy as np
import pandas as pd

from config import (
    BACKTEST_COMMISSION_PCT,
    BACKTEST_HALF_SPREAD_BPS,
    BACKTEST_SLIPPAGE_BPS,
)
from market_data import indicators, load_price_history
from strategy_rules import (
    ENTRY_GAP_ATR,
    ENTRY_GAP_PCT,
    canonical_signal_frame,
    trade_levels_from_row,
)


def _historical_market_state(index: pd.Index) -> pd.Series:
    """Rebuild the live SPY/QQQ market regime for each historical trading day."""
    total = pd.Series(0.0, index=index)
    usable = 0
    for symbol in ('SPY', 'QQQ'):
        try:
            d = load_price_history(symbol, '10y')
            ind = indicators(d)
            score = (
                (ind['close'] > ind['sma120']).astype(int)
                + (ind['close'] > ind['sma200']).astype(int)
                + (ind['rsi'] > 45).astype(int)
            )
            total = total.add(score.reindex(index).ffill().fillna(0), fill_value=0)
            usable += 1
        except Exception:
            continue

    if usable == 0:
        return pd.Series('조심', index=index, dtype='object')

    state = pd.Series('조심', index=index, dtype='object')
    state.loc[total >= 3] = '중립'
    state.loc[total >= 5] = '좋음'
    return state


def _bps_fraction(bps: float) -> float:
    return max(0.0, float(bps)) / 10_000.0


def market_buy_fill(raw_price: float, slippage_bps: float, half_spread_bps: float) -> float:
    """Conservative market-like buy fill: pay half-spread plus slippage."""
    impact = _bps_fraction(slippage_bps) + _bps_fraction(half_spread_bps)
    return float(raw_price) * (1.0 + impact)


def market_sell_fill(raw_price: float, slippage_bps: float, half_spread_bps: float) -> float:
    """Conservative market-like sell fill: cross half-spread plus slippage."""
    impact = _bps_fraction(slippage_bps) + _bps_fraction(half_spread_bps)
    return float(raw_price) * (1.0 - impact)


def net_trade_return(entry_fill: float, exit_fill: float, commission: float) -> float:
    """Return after entry and exit commissions, where commission is a decimal fraction per side."""
    entry_cost = float(entry_fill) * (1.0 + float(commission))
    exit_proceeds = float(exit_fill) * (1.0 - float(commission))
    return exit_proceeds / entry_cost - 1.0


def exit_fill_for_bar(
    open_px: float,
    high_px: float,
    low_px: float,
    target: float,
    stop: float,
    slippage_bps: float = BACKTEST_SLIPPAGE_BPS,
    half_spread_bps: float = BACKTEST_HALF_SPREAD_BPS,
):
    """Return (fill_price, reason, raw_trigger_price) or None for one OHLC bar.

    Rules are intentionally conservative:
    - gap below stop: stop-market fills from the worse opening price plus costs
    - gap above target: target limit is credited only at target, not the better open
    - if target and stop are both touched intraday, stop wins
    """
    open_px = float(open_px)
    high_px = float(high_px)
    low_px = float(low_px)
    target = float(target)
    stop = float(stop)

    if open_px <= stop:
        return market_sell_fill(open_px, slippage_bps, half_spread_bps), '갭손절', open_px
    if open_px >= target:
        return target, '갭목표', target
    if low_px <= stop:
        return market_sell_fill(stop, slippage_bps, half_spread_bps), '손절', stop
    if high_px >= target:
        return target, '목표달성', target
    return None


def signal_frame(d: pd.DataFrame, strategy_id: str) -> pd.DataFrame:
    market_state = _historical_market_state(d.index)
    canonical = canonical_signal_frame(d, market_state)
    if strategy_id not in canonical.columns:
        raise ValueError('알 수 없는 전략')
    return pd.DataFrame(
        {
            'signal': canonical[strategy_id].fillna(False),
            'atr': canonical['atr'],
            'close': canonical['close'],
        },
        index=d.index,
    )


def simulate(
    d: pd.DataFrame,
    strategy_id: str,
    commission: float | None = None,
    start_i: int = 205,
    slippage_bps: float = BACKTEST_SLIPPAGE_BPS,
    half_spread_bps: float = BACKTEST_HALF_SPREAD_BPS,
    market_state: pd.Series | None = None,
    symbol: str | None = None,
):
    commission = BACKTEST_COMMISSION_PCT / 100.0 if commission is None else float(commission)
    market_state = _historical_market_state(d.index) if market_state is None else market_state
    frame = canonical_signal_frame(d, market_state)
    if strategy_id not in frame.columns:
        raise ValueError('알 수 없는 전략')

    trades = []
    i = max(205, int(start_i))
    n = len(d)
    while i < n - 2:
        if not bool(frame[strategy_id].iloc[i]):
            i += 1
            continue

        plan = trade_levels_from_row(frame.iloc[i], strategy_id)
        entry_i = i + 1
        raw_entry = float(d['Open'].iloc[entry_i])

        # Match live entry-viability tolerance before accepting a next-day open fill.
        gap_guard = max(ENTRY_GAP_ATR * plan['atr'], ENTRY_GAP_PCT * float(frame['close'].iloc[i]))
        if raw_entry < plan['buy_low'] - gap_guard or raw_entry > plan['buy_high'] + gap_guard:
            i += 1
            continue

        entry_fill = market_buy_fill(raw_entry, slippage_bps, half_spread_bps)
        target = float(plan['target'])
        stop = float(plan['stop'])
        if not stop < entry_fill < target:
            i += 1
            continue

        max_hold = int(plan['days'][1])
        exit_i = min(entry_i + max_hold, n - 1)
        raw_exit = float(d['Close'].iloc[exit_i])
        exit_fill = market_sell_fill(raw_exit, slippage_bps, half_spread_bps)
        reason = '기간종료'

        for j in range(entry_i, exit_i + 1):
            bar = d.iloc[j]
            outcome = exit_fill_for_bar(
                bar['Open'],
                bar['High'],
                bar['Low'],
                target,
                stop,
                slippage_bps,
                half_spread_bps,
            )
            if outcome is not None:
                exit_fill, reason, raw_exit = outcome
                exit_i = j
                break

        gross_ret = float(exit_fill) / float(entry_fill) - 1.0
        ret = net_trade_return(entry_fill, exit_fill, commission)
        risk = entry_fill - stop
        reward = target - entry_fill
        risk_pct = risk / entry_fill if entry_fill > 0 else 0.0
        risk_reward = reward / risk if risk > 0 else 0.0

        trades.append(
            {
                'symbol': symbol,
                'strategy_id': strategy_id,
                'signal_i': i,
                'signal_date': d.index[i].strftime('%Y-%m-%d'),
                'entry_i': entry_i,
                'entry_date': d.index[entry_i].strftime('%Y-%m-%d'),
                'exit_i': exit_i,
                'exit_date': d.index[exit_i].strftime('%Y-%m-%d'),
                'raw_entry': raw_entry,
                'entry_fill': round(float(entry_fill), 6),
                'target': round(target, 6),
                'stop': round(stop, 6),
                'raw_exit': round(float(raw_exit), 6),
                'exit_fill': round(float(exit_fill), 6),
                'gross_ret': gross_ret,
                'ret': ret,
                'reason': reason,
                'risk_pct': risk_pct,
                'risk_reward': risk_reward,
                'commission_pct_per_side': commission * 100.0,
                'slippage_bps': float(slippage_bps),
                'half_spread_bps': float(half_spread_bps),
            }
        )
        i = exit_i + 1
    return trades


def stats(d: pd.DataFrame, trades: list[dict]):
    if not trades:
        return {
            'return_pct': 0,
            'buy_hold_pct': round((float(d['Close'].iloc[-1]) / float(d['Close'].iloc[0]) - 1) * 100, 2),
            'win_rate': 0,
            'trades': 0,
            'max_drawdown': 0,
            'profit_factor': None,
            'sharpe': None,
            'avg_trade': 0,
            'avg_gross_trade': 0,
            'estimated_cost_drag_per_trade_pct': 0,
            'gap_stop_count': 0,
            'gap_target_count': 0,
        }

    r = np.array([t['ret'] for t in trades], dtype=float)
    gross = np.array([t.get('gross_ret', t['ret']) for t in trades], dtype=float)
    equity = np.cumprod(1 + r)
    peak = np.maximum.accumulate(equity)
    dd = equity / peak - 1
    gains = r[r > 0].sum()
    losses = -r[r < 0].sum()
    return {
        'return_pct': round((equity[-1] - 1) * 100, 2),
        'buy_hold_pct': round((float(d['Close'].iloc[-1]) / float(d['Close'].iloc[0]) - 1) * 100, 2),
        'win_rate': round(float((r > 0).mean() * 100), 1),
        'trades': len(r),
        'max_drawdown': round(float(dd.min() * 100), 2),
        'profit_factor': None if losses <= 0 else round(float(gains / losses), 2),
        'sharpe': None
        if len(r) < 2 or r.std(ddof=1) == 0
        else round(float(r.mean() / r.std(ddof=1) * math.sqrt(len(r))), 2),
        'avg_trade': round(float(r.mean() * 100), 2),
        'avg_gross_trade': round(float(gross.mean() * 100), 2),
        'estimated_cost_drag_per_trade_pct': round(float((gross - r).mean() * 100), 3),
        'gap_stop_count': sum(t.get('reason') == '갭손절' for t in trades),
        'gap_target_count': sum(t.get('reason') == '갭목표' for t in trades),
    }


def run_backtest_on_frame(d: pd.DataFrame, strategy_id: str):
    market_state = _historical_market_state(d.index)
    all_trades = simulate(d, strategy_id, market_state=market_state)
    full = stats(d, all_trades)
    if len(d) <= 220:
        return {'full_10y': full, 'recent_2y': None}

    recent = d.tail(504).copy()
    recent_start = max(205, len(d) - len(recent))
    recent_trades = [t for t in all_trades if int(t['entry_i']) >= recent_start]
    return {
        'full_10y': full,
        'recent_2y': stats(recent, recent_trades),
    }


def run_backtest(symbol: str, strategy_id: str):
    d = load_price_history(symbol, '10y')
    result = run_backtest_on_frame(d, strategy_id)
    return {
        'symbol': symbol,
        'strategy_id': strategy_id,
        'engine': 'Swing Lab Backtest V2',
        'full_10y': result['full_10y'],
        'recent_2y': result['recent_2y'],
        'assumptions': {
            'commission_pct_per_side': BACKTEST_COMMISSION_PCT,
            'slippage_bps': BACKTEST_SLIPPAGE_BPS,
            'half_spread_bps': BACKTEST_HALF_SPREAD_BPS,
            'entry': 'canonical signal; next-day open only when within live entry-gap tolerance; market-like cost applied',
            'target': 'limit-style target; gap above target is conservatively credited at target only',
            'stop': 'stop-market style; gap below stop fills from worse opening price plus spread/slippage',
            'intrabar': 'same-day target+stop touch is counted as stop first',
            'market_regime': 'historical SPY/QQQ regime rebuilt with the live 120d/200d/RSI>45 scoring rule',
        },
    }
