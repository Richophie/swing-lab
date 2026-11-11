"""Wide-universe entry-feature pool for the pullback strategies.

The replay pool covers 80 symbols, which leaves the pullback strategies with a
few hundred signals. This builder replays the canonical strict signals over the
same ~500-symbol universe the live scanner uses, and stores for every signal:

- features known at the signal-day close (never anything later), and
- the outcome under the current production plan (next-open entry, canonical
  stop/target/hold, costs included).

Raw strict signals are kept without the elite selection so the research can ask
which setups win, instead of inheriting a selection that forward data showed to
be weakly predictive.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from backtest_engine import _historical_market_state
from config import (
    BACKTEST_COMMISSION_PCT, BACKTEST_HALF_SPREAD_BPS, BACKTEST_SLIPPAGE_BPS, SCAN_CANDIDATE_LIMIT,
)
from exit_policy_research import POLICIES, execute
from market_data import indicators, load_price_history, load_us_universe, prefilter_symbols, wilder_rsi
from regime_rank_research import INDEX_SYMBOLS, index_features
from scanner import _extract_frame
from strategy_rules import canonical_signal_frame, trade_levels_from_row

OUT = Path('static/entry_feature_pool.json')
STRATEGIES = ('confirmed_pullback', 'momentum_pullback', 'rsi2_trend_reversion')
MIN_HISTORY_ROWS = 400
PATH_BARS = 12
CHUNK = 50

FEATURES = {
    'rsi': 'RSI(14)',
    'rsi2': 'RSI(2)',
    'bb_pos': '볼린저 밴드 안 위치',
    'dist_sma20': '20일선과의 거리',
    'dist_sma50': '50일선과의 거리',
    'dist_sma120': '120일선과의 거리',
    'dist_sma200': '200일선과의 거리',
    'slope_sma120': '120일선 기울기(20일)',
    'atr_pct': '하루 평균 움직임',
    'ret5': '최근 5일 수익률',
    'ret20': '최근 20일 수익률',
    'ret60': '최근 60일 수익률',
    'drawdown_60d': '60일 고점 대비 낙폭',
    'drawdown_252d': '1년 고점 대비 낙폭',
    'rel_volume': '당일 거래량 / 20일 평균',
    'volume_5d_vs_20d': '최근 5일 거래량 / 20일 평균',
    'close_in_range': '당일 종가의 고저 범위 안 위치',
    'body_atr': '당일 몸통 / ATR',
    'gap_pct': '당일 시가 갭',
    'up_days_5': '최근 5일 중 상승 마감 일수',
    'down_streak': '연속 하락 마감 일수',
    'dollar_volume_log': '거래대금(로그)',
    'plan_reward_risk': '계획 손익비',
    'plan_stop_pct': '계획 손절 폭',
    'plan_target_pct': '계획 목표 폭',
    'spy_ret5': 'SPY 최근 5일 수익률',
    'spy_ret20': 'SPY 최근 20일 수익률',
}


def feature_frame(d: pd.DataFrame) -> pd.DataFrame:
    """Per-day features. Every column uses data up to and including that day's close."""
    ind = indicators(d)
    c, o = d['Close'].astype(float), d['Open'].astype(float)
    h, l, v = d['High'].astype(float), d['Low'].astype(float), d['Volume'].astype(float)
    atr = ind['atr14']
    vol20 = ind['vol20'].replace(0, np.nan)
    down = (c < c.shift(1)).astype(int)
    streak = down.groupby((down == 0).cumsum()).cumsum()
    span = (h - l).replace(0, np.nan)
    out = pd.DataFrame({
        'rsi': ind['rsi'],
        'rsi2': wilder_rsi(c, 2),
        'bb_pos': ind['bb_pos'],
        'dist_sma20': c / ind['sma20'] - 1,
        'dist_sma50': c / ind['sma50'] - 1,
        'dist_sma120': c / ind['sma120'] - 1,
        'dist_sma200': c / ind['sma200'] - 1,
        'slope_sma120': ind['sma120'] / ind['sma120'].shift(20) - 1,
        'atr_pct': atr / c,
        'ret5': c / c.shift(5) - 1,
        'ret20': c / c.shift(20) - 1,
        'ret60': c / c.shift(60) - 1,
        'drawdown_60d': c / h.rolling(60).max() - 1,
        'drawdown_252d': c / h.rolling(252).max() - 1,
        'rel_volume': v / vol20,
        'volume_5d_vs_20d': v.rolling(5).mean() / vol20,
        'close_in_range': (c - l) / span,
        'body_atr': (c - o) / atr,
        'gap_pct': o / c.shift(1) - 1,
        'up_days_5': (c > c.shift(1)).astype(int).rolling(5).sum(),
        'down_streak': streak,
        'dollar_volume_log': np.log10((c * v).rolling(20).mean().replace(0, np.nan)),
    }, index=d.index)
    return out


def signal_rows(symbol: str, d: pd.DataFrame, state: pd.Series, index_rows: dict, commission: float, friction: float) -> list[dict]:
    frame = canonical_signal_frame(d, state)
    features = feature_frame(d)
    rows = []
    for sid in STRATEGIES:
        for i in np.flatnonzero(frame[sid].to_numpy()):
            if i + 1 >= len(d):
                continue
            row = frame.iloc[i]
            if not all(math.isfinite(float(row[k])) for k in ('close', 'atr', 'recent_low', 'recent_high', 's20', 's120')):
                continue
            plan = trade_levels_from_row(row, sid)
            signal_date = d.index[i].strftime('%Y-%m-%d')
            path = [
                [d.index[j].strftime('%Y-%m-%d'), float(d['Open'].iloc[j]), float(d['High'].iloc[j]), float(d['Low'].iloc[j]), float(d['Close'].iloc[j])]
                for j in range(i + 1, min(len(d), i + 1 + PATH_BARS))
            ]
            candidate = {
                'symbol': symbol, 'strategy_id': sid, 'signal_date': signal_date, 'signal_close': float(row['close']),
                'buy_low': plan['buy_low'], 'buy_high': plan['buy_high'], 'atr': plan['atr'],
                'stop': plan['stop'], 'target': plan['target'], 'max_hold': int(plan['days'][1]), 'path': path,
            }
            # A signal whose hold window is not complete yet has no final outcome.
            if len(path) < candidate['max_hold']:
                continue
            trade = execute(candidate, POLICIES['baseline'], commission, friction)
            if trade is None:
                continue
            entry = plan['entry']
            values = {k: features[k].iloc[i] for k in features.columns}
            values['plan_reward_risk'] = (plan['target'] - entry) / (entry - plan['stop']) if entry > plan['stop'] else np.nan
            values['plan_stop_pct'] = (entry - plan['stop']) / entry
            values['plan_target_pct'] = (plan['target'] - entry) / entry
            index_row = index_rows.get(signal_date) or {}
            values['spy_ret5'] = index_row.get('SPY_ret5', np.nan)
            values['spy_ret20'] = index_row.get('SPY_ret20', np.nan)
            rows.append({
                'symbol': symbol, 'strategy_id': sid, 'signal_date': signal_date,
                'market_state': str(row['market_state']),
                'return_pct': round(trade['return_pct'], 4), 'reason': trade['reason'], 'held_bars': trade['held_bars'],
                'features': {k: (round(float(x), 5) if x is not None and math.isfinite(float(x)) else None) for k, x in values.items()},
            })
    return rows


def download(symbols: list[str]) -> dict[str, pd.DataFrame]:
    frames = {}
    for start in range(0, len(symbols), CHUNK):
        chunk = symbols[start:start + CHUNK]
        try:
            bulk = yf.download(' '.join(chunk), period='10y', interval='1d', auto_adjust=False, group_by='ticker', threads=True, progress=False, timeout=60)
        except Exception:
            continue
        for symbol in chunk:
            try:
                frame = _extract_frame(bulk, symbol, len(chunk))
            except Exception:
                continue
            if frame is not None and len(frame) >= MIN_HISTORY_ROWS:
                frames[symbol] = frame.dropna(subset=['Open', 'High', 'Low', 'Close', 'Volume'])
    return frames


def build(symbols: list[str] | None = None) -> dict:
    symbols = symbols or prefilter_symbols(load_us_universe(), SCAN_CANDIDATE_LIMIT)
    commission = BACKTEST_COMMISSION_PCT / 100.0
    friction = (BACKTEST_SLIPPAGE_BPS + BACKTEST_HALF_SPREAD_BPS) / 10000.0
    index_frames = {s: load_price_history(s, 'max') for s in INDEX_SYMBOLS}
    index_rows = index_features(index_frames).to_dict('index')
    state_all = _historical_market_state(index_frames['SPY'].index)
    frames = download(symbols)
    rows = []
    for symbol, d in sorted(frames.items()):
        try:
            rows.extend(signal_rows(symbol, d, state_all.reindex(d.index).ffill().fillna('조심'), index_rows, commission, friction))
        except Exception:
            continue
    rows.sort(key=lambda r: (r['signal_date'], r['symbol'], r['strategy_id']))
    return {
        'version': 1,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'requested_symbol_count': len(symbols),
        'eligible_symbol_count': len(frames),
        'strategies': list(STRATEGIES),
        'feature_labels': FEATURES,
        'selection': 'raw_strict_signals_without_elite_selection',
        'execution': 'next_open_entry_with_gap_guard_canonical_stop_target_hold',
        'costs': {'commission_pct_per_side': BACKTEST_COMMISSION_PCT, 'slippage_bps': BACKTEST_SLIPPAGE_BPS, 'half_spread_bps': BACKTEST_HALF_SPREAD_BPS},
        'available_start': rows[0]['signal_date'] if rows else None,
        'available_end': rows[-1]['signal_date'] if rows else None,
        'signal_count': len(rows),
        'signals': rows,
        'limitations': [
            '현재 유동성 상위 종목을 과거로 되감은 풀이라 생존편향이 있습니다.',
            '엄선을 거치지 않은 원신호입니다. 실제 추천보다 범위가 넓습니다.',
            '특징은 신호일 종가까지의 데이터만 사용합니다.',
        ],
    }


def main():
    payload = build()
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    counts = {sid: sum(1 for r in payload['signals'] if r['strategy_id'] == sid) for sid in STRATEGIES}
    print(json.dumps({'symbols': payload['eligible_symbol_count'], 'signals': payload['signal_count'], **counts}, ensure_ascii=False))


if __name__ == '__main__':
    main()
