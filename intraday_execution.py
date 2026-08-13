from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from stock_names import canonical_symbol

NY = ZoneInfo('America/New_York')


def _normalize_intraday(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    d = df.copy()
    if isinstance(d.columns, pd.MultiIndex):
        if len(d.columns.levels[-1]) == 1:
            d.columns = d.columns.get_level_values(0)
        else:
            d.columns = [c[0] if isinstance(c, tuple) else c for c in d.columns]
    need = ['Open', 'High', 'Low', 'Close']
    if any(c not in d.columns for c in need):
        return pd.DataFrame()
    d = d.dropna(subset=need).copy()
    idx = pd.to_datetime(d.index)
    if getattr(idx, 'tz', None) is None:
        idx = idx.tz_localize('UTC').tz_convert(NY)
    else:
        idx = idx.tz_convert(NY)
    d.index = idx
    return d.sort_index()


def fresh_intraday_history(symbol: str, period: str = '7d') -> pd.DataFrame:
    try:
        d = yf.Ticker(canonical_symbol(symbol)).history(
            period=period,
            interval='1m',
            auto_adjust=False,
            prepost=False,
            timeout=10,
        )
    except TypeError:
        d = yf.Ticker(canonical_symbol(symbol)).history(
            period=period,
            interval='1m',
            auto_adjust=False,
            prepost=False,
        )
    return _normalize_intraday(d)


def bars_for_date(df: pd.DataFrame, session_date: str | date) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    wanted = str(session_date)[:10]
    mask = pd.Index([ts.strftime('%Y-%m-%d') == wanted for ts in df.index])
    return df.loc[mask].copy()


def first_buy_touch(bars: pd.DataFrame, buy_low: float, buy_high: float, *, stop: float | None = None):
    """Return the first price at-or-better than the frozen BUY ceiling.

    BUY high is interpreted as the maximum acceptable entry price, not a narrow
    box that rejects cheaper prices. If the next session opens below BUY low but
    remains above STOP, that cheaper open is a valid fill. If price starts above
    BUY high, wait until it falls to BUY high. A session already at/below STOP is
    considered thesis-broken and must not create a fresh position.
    """
    if bars is None or bars.empty:
        return None
    _, hi = sorted((float(buy_low), float(buy_high)))
    stop_px = None if stop is None else float(stop)
    for ts, row in bars.iterrows():
        o, l = float(row['Open']), float(row['Low'])
        if stop_px is not None and o <= stop_px:
            return {
                'timestamp': ts.isoformat(),
                'raw_price': o,
                'quality': '1m_open_below_stop_skip',
                'invalid': True,
            }
        if o <= hi:
            return {
                'timestamp': ts.isoformat(),
                'raw_price': o,
                'quality': '1m_open_at_or_better_than_buy',
                'invalid': False,
            }
        if l <= hi:
            return {
                'timestamp': ts.isoformat(),
                'raw_price': hi,
                'quality': '1m_first_buy_ceiling_touch',
                'invalid': False,
            }
    return None


def first_exit_touch(
    bars: pd.DataFrame,
    *,
    target: float,
    stop: float,
    after_timestamp: str | None = None,
):
    """Resolve which exit level was touched first from chronological 1-minute bars.

    If both levels occur inside the same one-minute candle the exact tick ordering
    is still unknowable, so that single unresolved candle deliberately falls back
    to STOP and records that degraded resolution quality.
    """
    if bars is None or bars.empty:
        return None
    d = bars
    if after_timestamp:
        try:
            stamp = pd.Timestamp(after_timestamp)
            if stamp.tzinfo is None:
                stamp = stamp.tz_localize(NY)
            else:
                stamp = stamp.tz_convert(NY)
            d = d[d.index >= stamp]
        except Exception:
            pass
    target, stop = float(target), float(stop)
    for ts, row in d.iterrows():
        o, h, l = float(row['Open']), float(row['High']), float(row['Low'])
        if o <= stop:
            return {'side': 'STOP', 'timestamp': ts.isoformat(), 'raw_price': o, 'reason': '갭손절', 'quality': '1m_first_touch'}
        if o >= target:
            return {'side': 'TARGET', 'timestamp': ts.isoformat(), 'raw_price': target, 'reason': '갭목표', 'quality': '1m_first_touch'}
        hit_stop = l <= stop
        hit_target = h >= target
        if hit_stop and hit_target:
            return {
                'side': 'STOP',
                'timestamp': ts.isoformat(),
                'raw_price': stop,
                'reason': '손절',
                'quality': '1m_ambiguous_stop_fallback',
            }
        if hit_stop:
            return {'side': 'STOP', 'timestamp': ts.isoformat(), 'raw_price': stop, 'reason': '손절', 'quality': '1m_first_touch'}
        if hit_target:
            return {'side': 'TARGET', 'timestamp': ts.isoformat(), 'raw_price': target, 'reason': '목표달성', 'quality': '1m_first_touch'}
    return None
