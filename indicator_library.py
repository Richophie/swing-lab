"""Classic technical indicators as signal-day features for the strategy evolution search.

Every column uses data up to and including that day's close, and is scaled (by ATR,
price or a 0-100 range) so one threshold means the same thing for a $20 and a $500 stock.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from market_data import wilder_rsi

LABELS = {
    'macd_hist_atr': 'MACD 히스토그램 / ATR',
    'macd_hist_change': 'MACD 히스토그램 3일 변화 / ATR',
    'macd_line_atr': 'MACD 선 / ATR',
    'stoch_k': '스토캐스틱 %K(14,3)',
    'stoch_k_minus_d': '스토캐스틱 %K - %D',
    'cci20': 'CCI(20)',
    'mfi14': 'MFI(14)',
    'adx14': 'ADX(14)',
    'di_spread': '+DI - -DI',
    'obv_slope20': 'OBV 20일 변화 / 20일 거래량',
    'cmf20': '차이킨 머니 플로우(20)',
    'up_volume_ratio10': '최근 10일 상승일 거래량 비중',
    'bb_width': '볼린저 밴드 폭',
    'bb_width_rank120': '볼린저 밴드 폭의 120일 내 순위',
    'keltner_pos': '20일 지수평균과의 거리 / ATR',
    'donchian_pos20': '20일 고저 범위 안 위치',
    'donchian_pos55': '55일 고저 범위 안 위치',
    'dist_low_252d': '1년 저점 대비 상승폭',
    'days_since_high20': '20일 고점 이후 지난 일수',
    'days_since_low20': '20일 저점 이후 지난 일수',
    'ret1': '당일 수익률',
    'ret3': '최근 3일 수익률',
    'ret10': '최근 10일 수익률',
    'ret120': '최근 120일 수익률',
    'rsi5': 'RSI(5)',
    'rsi_change3': 'RSI(14) 3일 변화',
    'dist_ema10': '10일 지수평균과의 거리',
    'ema10_vs_ema50': '10일 지수평균 / 50일 지수평균',
    'sma50_vs_sma200': '50일선 / 200일선',
    'ichimoku_cloud_dist': '일목 구름 상단과의 거리',
    'tenkan_vs_kijun': '일목 전환선 - 기준선',
    'volatility_ratio': '최근 5일 변동폭 / 20일 변동폭',
    'range_atr': '당일 고저 폭 / ATR',
    'range_vs_min7': '당일 고저 폭 / 최근 7일 최소 폭',
    'lower_wick_atr': '아래꼬리 / ATR',
    'upper_wick_atr': '위꼬리 / ATR',
    'intraday_ret5': '최근 5일 장중(시가→종가) 수익 합',
    'overnight_ret5': '최근 5일 밤사이(종가→시가) 수익 합',
    'realized_vol20': '20일 실현 변동성',
    'efficiency10': '10일 추세 효율(직선 이동 / 총 이동)',
    # cross-sectional and market-wide, added on the panel
    'rs_spy20': 'SPY 대비 20일 초과수익',
    'rs_spy60': 'SPY 대비 60일 초과수익',
    'rank_ret5': '지수 내 5일 수익률 순위',
    'rank_ret20': '지수 내 20일 수익률 순위',
    'rank_ret60': '지수 내 60일 수익률 순위',
    'rank_rsi2': '지수 내 RSI(2) 순위',
    'breadth_sma50': '50일선 위 종목 비율',
    'breadth_sma200': '200일선 위 종목 비율',
    'breadth_oversold': 'RSI(2) 10 미만 종목 비율',
    'breadth_change5': '50일선 위 종목 비율의 5일 변화',
    'spy_dist_sma200': 'SPY의 200일선과의 거리',
    'spy_dist_sma20': 'SPY의 20일선과의 거리',
    'spy_rsi2': 'SPY RSI(2)',
    'spy_ret1': 'SPY 당일 수익률',
    'spy_ret60': 'SPY 최근 60일 수익률',
    'vix': 'VIX',
    'vix_vs_sma20': 'VIX / 20일 평균',
    'vix_ret5': 'VIX 5일 변화',
}


def _bars_since_extreme(series: pd.Series, window: int, highest: bool) -> pd.Series:
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    if len(values) >= window:
        view = np.lib.stride_tricks.sliding_window_view(values, window)
        ok = np.isfinite(view).all(axis=1)
        safe = np.where(np.isfinite(view), view, 0.0)
        where = safe.argmax(axis=1) if highest else safe.argmin(axis=1)
        out[window - 1:] = np.where(ok, window - 1 - where, np.nan)
    return pd.Series(out, index=series.index)


def extra_features(d: pd.DataFrame) -> pd.DataFrame:
    c, o = d['Close'].astype(float), d['Open'].astype(float)
    h, l, v = d['High'].astype(float), d['Low'].astype(float), d['Volume'].astype(float)
    prev = c.shift(1)
    tr = pd.concat([(h - l).abs(), (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().replace(0, np.nan)
    span = (h - l).replace(0, np.nan)
    ema = lambda s, n: s.ewm(span=n, adjust=False, min_periods=n).mean()
    wilder = lambda s, n: s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()

    macd = ema(c, 12) - ema(c, 26)
    hist = macd - macd.ewm(span=9, adjust=False, min_periods=9).mean()

    low14, high14 = l.rolling(14).min(), h.rolling(14).max()
    stoch_k = ((c - low14) / (high14 - low14).replace(0, np.nan) * 100).rolling(3).mean()

    typical = (h + l + c) / 3
    mean_dev = (typical - typical.rolling(20).mean()).abs().rolling(20).mean().replace(0, np.nan)
    flow = typical * v
    up_flow = flow.where(typical > typical.shift(1), 0.0).rolling(14).sum()
    down_flow = flow.where(typical < typical.shift(1), 0.0).rolling(14).sum()

    up_move, down_move = h.diff(), -l.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    tr_w = wilder(tr, 14).replace(0, np.nan)
    plus_di, minus_di = 100 * wilder(plus_dm, 14) / tr_w, 100 * wilder(minus_dm, 14) / tr_w
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)

    vol20_sum = v.rolling(20).sum().replace(0, np.nan)
    obv = (np.sign(c.diff()).fillna(0) * v).cumsum()
    money_flow_volume = ((c - l) - (h - c)) / span * v
    up_day = c > prev

    sma20, std20 = c.rolling(20).mean(), c.rolling(20).std(ddof=0)
    bb_width = 4 * std20 / sma20
    low20, high20, low55, high55 = l.rolling(20).min(), h.rolling(20).max(), l.rolling(55).min(), h.rolling(55).max()

    tenkan = (h.rolling(9).max() + l.rolling(9).min()) / 2
    kijun = (h.rolling(26).max() + l.rolling(26).min()) / 2
    # The cloud drawn under today's bar was computed 26 bars ago.
    span_a, span_b = ((tenkan + kijun) / 2).shift(26), ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
    cloud_top = pd.concat([span_a, span_b], axis=1).max(axis=1, skipna=False)

    rsi14 = wilder_rsi(c, 14)
    daily = c.pct_change()
    path = c.diff().abs().rolling(10).sum().replace(0, np.nan)
    return pd.DataFrame({
        'macd_hist_atr': hist / atr,
        'macd_hist_change': (hist - hist.shift(3)) / atr,
        'macd_line_atr': macd / atr,
        'stoch_k': stoch_k,
        'stoch_k_minus_d': stoch_k - stoch_k.rolling(3).mean(),
        'cci20': (typical - typical.rolling(20).mean()) / (0.015 * mean_dev),
        'mfi14': 100 * up_flow / (up_flow + down_flow).replace(0, np.nan),
        'adx14': wilder(dx, 14),
        'di_spread': plus_di - minus_di,
        'obv_slope20': (obv - obv.shift(20)) / vol20_sum,
        'cmf20': money_flow_volume.rolling(20).sum() / vol20_sum,
        'up_volume_ratio10': v.where(up_day, 0.0).rolling(10).sum() / v.rolling(10).sum().replace(0, np.nan),
        'bb_width': bb_width,
        'bb_width_rank120': bb_width.rolling(120).rank(pct=True),
        'keltner_pos': (c - ema(c, 20)) / atr,
        'donchian_pos20': (c - low20) / (high20 - low20).replace(0, np.nan),
        'donchian_pos55': (c - low55) / (high55 - low55).replace(0, np.nan),
        'dist_low_252d': c / l.rolling(252).min() - 1,
        'days_since_high20': _bars_since_extreme(h, 20, True),
        'days_since_low20': _bars_since_extreme(l, 20, False),
        'ret1': daily,
        'ret3': c / c.shift(3) - 1,
        'ret10': c / c.shift(10) - 1,
        'ret120': c / c.shift(120) - 1,
        'rsi5': wilder_rsi(c, 5).where(c.shift(5).notna()),
        'rsi_change3': rsi14 - rsi14.shift(3),
        'dist_ema10': c / ema(c, 10) - 1,
        'ema10_vs_ema50': ema(c, 10) / ema(c, 50) - 1,
        'sma50_vs_sma200': c.rolling(50).mean() / c.rolling(200).mean() - 1,
        'ichimoku_cloud_dist': c / cloud_top - 1,
        'tenkan_vs_kijun': (tenkan - kijun) / c,
        'volatility_ratio': tr.rolling(5).mean() / tr.rolling(20).mean().replace(0, np.nan),
        'range_atr': (h - l) / atr,
        'range_vs_min7': (h - l) / (h - l).rolling(7).min().replace(0, np.nan),
        'lower_wick_atr': (pd.concat([o, c], axis=1).min(axis=1) - l) / atr,
        'upper_wick_atr': (h - pd.concat([o, c], axis=1).max(axis=1)) / atr,
        'intraday_ret5': (c / o - 1).rolling(5).sum(),
        'overnight_ret5': (o / prev - 1).rolling(5).sum(),
        'realized_vol20': daily.rolling(20).std(ddof=0),
        'efficiency10': (c - c.shift(10)).abs() / path,
    }, index=d.index)


def market_features(spy: pd.DataFrame, vix: pd.DataFrame | None) -> pd.DataFrame:
    close = spy['Close'].astype(float)
    out = pd.DataFrame({
        'spy_ret1': close.pct_change(),
        'spy_ret5': close / close.shift(5) - 1,
        'spy_ret20': close / close.shift(20) - 1,
        'spy_ret60': close / close.shift(60) - 1,
        'spy_dist_sma20': close / close.rolling(20).mean() - 1,
        'spy_dist_sma200': close / close.rolling(200).mean() - 1,
        'spy_rsi2': wilder_rsi(close, 2),
    })
    if vix is not None and len(vix):
        level = vix['Close'].astype(float).reindex(out.index).ffill()
        out['vix'] = level
        out['vix_vs_sma20'] = level / level.rolling(20).mean()
        out['vix_ret5'] = level / level.shift(5) - 1
    return out


def add_panel_features(features: dict, member: np.ndarray) -> None:
    """Features that compare a stock with the rest of the index on the same day. Edits `features` in place."""
    width = member.shape[1]
    counted = member.sum(axis=1).astype(np.float32)
    counted[counted == 0] = np.nan
    wide = lambda column: np.repeat(column.astype(np.float32)[:, None], width, axis=1)

    def rank(name: str) -> np.ndarray:
        values = np.where(member, features[name], np.nan)
        frame = pd.DataFrame(values).rank(axis=1, pct=True)
        return frame.to_numpy(dtype=np.float32)

    for window in (5, 20, 60):
        features[f'rank_ret{window}'] = rank(f'ret{window}')
    features['rank_rsi2'] = rank('rsi2')
    for window in (20, 60):
        if f'spy_ret{window}' in features:
            features[f'rs_spy{window}'] = (features[f'ret{window}'] - features[f'spy_ret{window}']).astype(np.float32)

    def share(condition: np.ndarray) -> np.ndarray:
        return (condition & member).sum(axis=1) / counted

    above50 = share(np.nan_to_num(features['dist_sma50'], nan=-1.0) > 0)
    features['breadth_sma50'] = wide(above50)
    features['breadth_sma200'] = wide(share(np.nan_to_num(features['dist_sma200'], nan=-1.0) > 0))
    features['breadth_oversold'] = wide(share(np.nan_to_num(features['rsi2'], nan=100.0) < 10))
    change = np.full(len(above50), np.nan)
    change[5:] = above50[5:] - above50[:-5]
    features['breadth_change5'] = wide(change)
