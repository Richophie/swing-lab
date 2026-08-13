from __future__ import annotations

import numpy as np
import pandas as pd

from market_data import indicators, wilder_rsi

MIN_STOP_ATR = 1.5
ENTRY_GAP_ATR = 0.75
ENTRY_GAP_PCT = 0.01
CONFIRM_REVERSAL_VOL_MIN = 1.0

STRATEGY_IDS = (
    'confirmed_pullback',
    'rsi2_trend_reversion',
    'momentum_pullback',
    'volatility_breakout',
)


def _market_state_series(index, market_state=None) -> pd.Series:
    if isinstance(market_state, pd.Series):
        return market_state.reindex(index).ffill().fillna('조심')
    label = '좋음' if market_state is None else str(market_state)
    return pd.Series(label, index=index, dtype='object')


def canonical_signal_frame(d: pd.DataFrame, market_state=None) -> pd.DataFrame:
    """Canonical strict entry rules shared by live scanning and backtests."""
    ind = indicators(d)
    close = d['Close'].astype(float)
    open_ = d['Open'].astype(float)
    high = d['High'].astype(float)
    low = d['Low'].astype(float)
    volume = d['Volume'].astype(float) if 'Volume' in d else pd.Series(0.0, index=d.index)

    s20 = ind['sma20']
    s50 = ind['sma50']
    s120 = ind['sma120']
    s200 = ind['sma200']
    rsi = ind['rsi']
    bb = ind['bb_pos']
    atr = ind['atr14']
    mh = ind['macd_hist']
    vol20 = ind['vol20']

    state = _market_state_series(d.index, market_state)
    market_ok = state.ne('조심')
    state_penalty = state.map({'중립': 2.0, '조심': 8.0}).fillna(0.0)

    d120 = close / s120 - 1
    d200 = close / s200 - 1
    atrp = atr / close
    slope120 = s120 / s120.shift(20) - 1
    rsi_delta3 = rsi - rsi.shift(3)
    macd_up = mh > mh.shift(1)
    price_reversal = (close > close.shift(1)) | (close > open_)
    trend_floor = (close >= s200 * .97) & (slope120 >= -.01)
    trend_ok = (close > s200) & (s50 >= s120)

    vr = volume / vol20.replace(0, np.nan)
    reversal_vol = (volume / vol20.replace(0, np.nan)).where(price_reversal, 0.0).fillna(0.0)

    rsi_score = np.select(
        [(rsi >= 30) & (rsi <= 42), (rsi >= 25) & (rsi < 30), rsi <= 50, rsi <= 60],
        [100, 70, 75, 45],
        default=20,
    )
    bb_score = np.select([bb <= .12, bb <= .30, bb <= .50, bb <= .75], [100, 85, 60, 35], default=15)
    s120_score = np.select(
        [d120.abs() <= .025, (d120 > -.06) & (d120 < .05), (d120 >= .05) & (d120 < .12)],
        [100, 78, 42],
        default=20,
    )
    macd_score = np.where(mh > 0, 82, 30)
    trend_score = np.where(s50 >= s120, 85, 45)
    risk_score = np.select([atrp <= .025, atrp <= .04, atrp <= .06], [85, 70, 45], default=20)
    volume_score = np.select([(vr >= 1.1) & (vr <= 2.5), vr > .75], [85, 65], default=40)

    pullback_score = (
        rsi_score * .18
        + bb_score * .17
        + s120_score * .22
        + macd_score * .16
        + trend_score * .12
        + volume_score * .07
        + risk_score * .08
    )
    pullback_score = pullback_score - np.where(rsi_delta3 < -3, 7, 0)
    pullback_score = pullback_score - np.where(~macd_up.fillna(False), 5, 0)
    pullback_score = pullback_score - np.where(slope120 < -.01, 8, 0)
    pullback_score = pullback_score - np.where(close < s200 * .97, 10, 0)
    pullback_score = pullback_score - np.where(~price_reversal.fillna(False), 5, 0)
    pullback_score = pullback_score - np.where((rsi < 22) & (close < s120 * .93), 12, 0)
    pullback_score = pullback_score - state_penalty

    confirm_count = (
        (rsi_delta3 >= 0).fillna(False).astype(int)
        + macd_up.fillna(False).astype(int)
        + price_reversal.fillna(False).astype(int)
        + trend_floor.fillna(False).astype(int)
    )
    pullback_base = (pullback_score >= 72) & (confirm_count >= 3) & trend_floor & market_ok
    confirmed_pullback = (
        pullback_base
        & (confirm_count == 4)
        & (reversal_vol >= CONFIRM_REVERSAL_VOL_MIN)
        & rsi.between(30, 43)
        & (bb <= .40)
        & (d120.abs() <= .035)
        & (atrp <= .045)
    )

    rsi2 = wilder_rsi(close, 2)
    rsi2_trend_reversion = (
        trend_ok
        & market_ok
        & (rsi2 < 3)
        & (rsi <= 50)
        & (bb <= .45)
        & d120.between(-.03, .12)
        & (d200 <= .25)
        & (atrp <= .05)
    )

    ret20 = close / close.shift(20) - 1
    ret5 = close / close.shift(5) - 1
    momentum_pullback = (
        trend_ok
        & market_ok
        & ret20.between(.05, .20)
        & ret5.between(-.05, -.005)
        & macd_up
        & rsi.between(42, 60)
        & d120.between(0, .20)
        & (bb <= .80)
        & (atrp <= .06)
    )

    tr10 = (high - low).rolling(10).mean() / close
    tr_prev = (high - low).shift(10).rolling(20).mean() / close.shift(20)
    high20 = high.shift(1).rolling(20).max()
    volatility_breakout = (
        trend_ok
        & market_ok
        & (tr_prev > 0)
        & ((tr10 / tr_prev) < .72)
        & (close > high20)
        & (vr >= 1.2)
        & rsi.between(45, 68, inclusive='left')
        & (atrp <= .07)
    )

    return pd.DataFrame(
        {
            'confirmed_pullback': confirmed_pullback.fillna(False),
            'rsi2_trend_reversion': rsi2_trend_reversion.fillna(False),
            'momentum_pullback': momentum_pullback.fillna(False),
            'volatility_breakout': volatility_breakout.fillna(False),
            'atr': atr,
            'close': close,
            's20': s20,
            's120': s120,
            'recent_low': low.rolling(10).min(),
            'recent_high': high.rolling(20).max(),
            'high20': high20,
            'market_state': state,
        },
        index=d.index,
    )


def strict_signal_flags(d: pd.DataFrame, market_state=None) -> dict[str, bool]:
    frame = canonical_signal_frame(d, market_state)
    if frame.empty:
        return {sid: False for sid in STRATEGY_IDS}
    row = frame.iloc[-1]
    return {sid: bool(row[sid]) for sid in STRATEGY_IDS}


def trade_levels_from_row(row: pd.Series, strategy_id: str) -> dict:
    close = float(row['close'])
    atr = max(float(row['atr']) if pd.notna(row['atr']) else close * .025, close * .005)
    recent_low = float(row['recent_low'])
    recent_high = float(row['recent_high'])
    s20 = float(row['s20'])
    s120 = float(row['s120'])

    if strategy_id == 'confirmed_pullback':
        anchor = s120
        buy_low = anchor - .18 * atr
        buy_high = anchor + .22 * atr
        raw_stop = min(recent_low, anchor - .95 * atr)
        target = max(recent_high, anchor + 1.8 * atr)
        days = (2, 8)
        basis = '120일선 지지/최근 고점'
        entry_reference = '120일선 지지구간'
    elif strategy_id == 'rsi2_trend_reversion':
        anchor = close
        buy_low = anchor - .12 * atr
        buy_high = anchor + .12 * atr
        raw_stop = min(recent_low, anchor - 1.15 * atr)
        target = max(anchor + 1.3 * atr, s20 if s20 > anchor else anchor + 1.3 * atr)
        days = (1, 5)
        basis = '단기 평균회귀/추세 복귀'
        entry_reference = '현재 과매도 구간'
    elif strategy_id == 'momentum_pullback':
        anchor = s20 if np.isfinite(s20) else close
        buy_low = anchor - .20 * atr
        buy_high = anchor + .18 * atr
        raw_stop = min(recent_low, anchor - 1.05 * atr)
        target = max(recent_high, anchor + 2.0 * atr)
        days = (3, 10)
        basis = '20일선 눌림/추세 재개'
        entry_reference = '20일선 눌림구간'
    elif strategy_id == 'volatility_breakout':
        breakout = float(row['high20'])
        buy_low = breakout
        buy_high = breakout + .25 * atr
        raw_stop = breakout - .85 * atr
        target = breakout + 2.2 * atr
        days = (2, 10)
        basis = '돌파선 재이탈/ATR 확장'
        entry_reference = '20일 고점 돌파구간'
    else:
        raise ValueError('알 수 없는 전략')

    entry = (buy_low + buy_high) / 2
    stop = min(raw_stop, entry - MIN_STOP_ATR * atr)
    if target <= entry:
        target = entry + 1.5 * atr

    return {
        'buy_low': buy_low,
        'buy_high': buy_high,
        'entry': entry,
        'target': target,
        'stop': stop,
        'atr': atr,
        'days': days,
        'basis': basis,
        'entry_reference': entry_reference,
    }


def current_trade_levels(d: pd.DataFrame, strategy_id: str) -> dict:
    frame = canonical_signal_frame(d, None)
    if frame.empty:
        raise ValueError('가격 데이터가 없습니다')
    return trade_levels_from_row(frame.iloc[-1], strategy_id)
