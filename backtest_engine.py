from __future__ import annotations

import math
import numpy as np
import pandas as pd

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


def simulate(d: pd.DataFrame, strategy_id: str, commission: float = .001):
    market_state = _historical_market_state(d.index)
    frame = canonical_signal_frame(d, market_state)
    if strategy_id not in frame.columns:
        raise ValueError('알 수 없는 전략')

    trades = []
    i = 205
    n = len(d)
    while i < n - 2:
        if not bool(frame[strategy_id].iloc[i]):
            i += 1
            continue

        plan = trade_levels_from_row(frame.iloc[i], strategy_id)
        entry_i = i + 1
        entry = float(d['Open'].iloc[entry_i])

        # Match live entry-viability tolerance before accepting a next-day open fill.
        gap_guard = max(ENTRY_GAP_ATR * plan['atr'], ENTRY_GAP_PCT * float(frame['close'].iloc[i]))
        if entry < plan['buy_low'] - gap_guard or entry > plan['buy_high'] + gap_guard:
            i += 1
            continue

        target = float(plan['target'])
        stop = float(plan['stop'])
        if not stop < entry < target:
            i += 1
            continue

        max_hold = int(plan['days'][1])
        exit_i = min(entry_i + max_hold, n - 1)
        exit_px = float(d['Close'].iloc[exit_i])
        reason = '기간종료'

        for j in range(entry_i, exit_i + 1):
            hi = float(d['High'].iloc[j])
            lo = float(d['Low'].iloc[j])
            # Conservative convention: if both are touched on one daily bar, stop wins.
            if lo <= stop:
                exit_px, exit_i, reason = stop, j, '손절'
                break
            if hi >= target:
                exit_px, exit_i, reason = target, j, '목표달성'
                break

        trades.append(
            {
                'entry_i': entry_i,
                'exit_i': exit_i,
                'ret': exit_px / entry - 1 - commission * 2,
                'reason': reason,
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
        }

    r = np.array([t['ret'] for t in trades], dtype=float)
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
    }


def run_backtest_on_frame(d: pd.DataFrame, strategy_id: str):
    recent = d.tail(504).copy()
    return {
        'full_10y': stats(d, simulate(d, strategy_id)),
        'recent_2y': stats(recent, simulate(recent, strategy_id)) if len(recent) > 220 else None,
    }


def run_backtest(symbol: str, strategy_id: str):
    d = load_price_history(symbol, '10y')
    result = run_backtest_on_frame(d, strategy_id)
    return {
        'symbol': symbol,
        'strategy_id': strategy_id,
        'engine': 'Swing Lab Canonical Vector Engine',
        'full_10y': result['full_10y'],
        'recent_2y': result['recent_2y'],
        'assumptions': {
            'commission_pct': 0.1,
            'entry': 'canonical signal; next-day open only when within live entry-gap tolerance',
            'exit': 'same canonical BUY/TARGET/STOP plan used by live scanner',
            'intrabar': 'same-day target+stop touch is counted as stop first',
            'market_regime': 'historical SPY/QQQ regime rebuilt with the live 120d/200d/RSI>45 scoring rule',
        },
    }
