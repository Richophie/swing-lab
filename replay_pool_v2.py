from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from config import BACKTEST_COMMISSION_PCT, BACKTEST_HALF_SPREAD_BPS, BACKTEST_SLIPPAGE_BPS
from gap_guard_research import _signal_candidates
from market_data import indicators, load_price_history
from rsi2_broad_regime_research import MIN_HISTORY_ROWS, research_universe
from structural_stop_research import STRATEGIES, STRATEGY_NAMES

OUT = Path('static/replay_backtest_pool_v2.json')
TARGET_SYMBOLS = 80
PATH_BARS = 22
SMA_ID = 'sma200_20_squeeze'
SMA_NAME = 'SMA200·20 스퀴즈'


def _num(v, default=None):
    try:
        x = float(v)
        return x if np.isfinite(x) else default
    except Exception:
        return default


def _path(d: pd.DataFrame, ind: dict, entry_i: int, bars: int) -> list[list]:
    out = []
    s20, s200 = ind['sma20'], ind['sma200']
    for j in range(entry_i, min(len(d), entry_i + bars)):
        bar = d.iloc[j]
        out.append([
            d.index[j].strftime('%Y-%m-%d'),
            round(float(bar['Open']), 6), round(float(bar['High']), 6),
            round(float(bar['Low']), 6), round(float(bar['Close']), 6),
            None if pd.isna(s20.iloc[j]) else round(float(s20.iloc[j]), 6),
            None if pd.isna(s200.iloc[j]) else round(float(s200.iloc[j]), 6),
        ])
    return out


def _sma_candidates(d: pd.DataFrame, ind: dict, symbol: str) -> list[dict]:
    c = d['Close'].astype(float); o = d['Open'].astype(float); l = d['Low'].astype(float); v = d['Volume'].astype(float)
    s20 = ind['sma20'].astype(float); s200 = ind['sma200'].astype(float); atr = ind['atr14'].astype(float)
    vol20 = v.rolling(20).mean().replace(0, np.nan)
    spread = (s20 / s200 - 1).abs()
    side = np.sign(s20 - s200)
    crosses = side.ne(side.shift(1)).rolling(30, min_periods=10).sum()
    strong = (c > o) & ((c - o) >= atr * .70)
    clean = l > pd.concat([s20, s200], axis=1).max(axis=1)
    fresh = c.shift(1) <= pd.concat([s20.shift(1), s200.shift(1)], axis=1).max(axis=1) * 1.015
    liquid = (v / vol20) >= .75
    signal = (c > s200) & (s200 > s200.shift(20)) & (spread <= .035) & (crosses <= 2) & strong & clean & fresh & liquid
    rows = []
    for i in np.flatnonzero(signal.fillna(False).to_numpy()):
        if i < 205 or i + 1 >= len(d):
            continue
        a = _num(atr.iloc[i]); close = _num(c.iloc[i]); ma20 = _num(s20.iloc[i]); ma200 = _num(s200.iloc[i])
        if not all(x is not None for x in (a, close, ma20, ma200)) or a <= 0:
            continue
        entry_i = i + 1
        path = _path(d, ind, entry_i, PATH_BARS)
        if not path:
            continue
        body_atr = max(0.0, (float(c.iloc[i]) - float(o.iloc[i])) / a)
        stop = min(ma20, ma200) - .15 * a
        rows.append({
            'symbol': symbol, 'strategy_id': SMA_ID, 'strategy_name': SMA_NAME,
            'signal_date': d.index[i].strftime('%Y-%m-%d'), 'entry_date': d.index[entry_i].strftime('%Y-%m-%d'),
            'signal_close': round(close, 6), 'buy_low': round(close - .20*a, 6), 'buy_high': round(close + .20*a, 6),
            'atr': round(a, 6), 'target': None, 'stop': round(stop, 6), 'max_hold': 20,
            'elite_score': round(min(95.0, 72.0 + body_atr * 8.0 + max(0.0, .035 - float(spread.iloc[i])) * 200), 4),
            'net_risk_reward': round(1.0 + min(1.0, body_atr / 2.0), 6),
            'market_state': 'strategy_only', 'exit_mode': 'sma20_close', 'path': path,
        })
    return rows


def build():
    requested, source = research_universe(); requested = requested[:TARGET_SYMBOLS]
    candidates, eligible, errors = [], [], []
    names = {**STRATEGY_NAMES, SMA_ID: SMA_NAME}
    for symbol in requested:
        try:
            d = load_price_history(symbol, '10y').dropna()
            if len(d) < MIN_HISTORY_ROWS:
                raise ValueError(f'history rows {len(d)} < {MIN_HISTORY_ROWS}')
            ind = indicators(d)
            frame, by_strategy = _signal_candidates(d, symbol)
            eligible.append(symbol)
        except Exception as exc:
            errors.append({'symbol': symbol, 'error': str(exc)}); continue
        for sid in STRATEGIES:
            for signal_i, info in sorted(by_strategy[sid].items()):
                entry_i = int(signal_i) + 1
                if entry_i >= len(d):
                    continue
                plan = info['plan']; path = _path(d, ind, entry_i, PATH_BARS)
                if not path:
                    continue
                candidates.append({
                    'symbol': symbol, 'strategy_id': sid, 'strategy_name': names.get(sid, sid),
                    'signal_date': d.index[signal_i].strftime('%Y-%m-%d'), 'entry_date': d.index[entry_i].strftime('%Y-%m-%d'),
                    'signal_close': round(float(frame['close'].iloc[signal_i]), 6),
                    'buy_low': round(float(plan['buy_low']), 6), 'buy_high': round(float(plan['buy_high']), 6),
                    'atr': round(float(plan['atr']), 6), 'target': round(float(plan['target']), 6),
                    'stop': round(float(plan['stop']), 6), 'max_hold': int(plan['days'][1]),
                    'elite_score': round(float(info['elite_score']), 4), 'net_risk_reward': round(float(info['net_risk_reward']), 6),
                    'market_state': info['market_state'], 'exit_mode': 'price_plan', 'path': path,
                })
        candidates.extend(_sma_candidates(d, ind, symbol))
    candidates.sort(key=lambda x: (x['entry_date'], -float(x.get('net_risk_reward') or 0), -float(x.get('elite_score') or 0), x['symbol']))
    dates = [x['entry_date'] for x in candidates]
    payload = {
        'version': 2, 'ready': True, 'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'selection_source': source, 'requested_symbol_count': len(requested), 'eligible_symbol_count': len(eligible),
        'available_start': min(dates) if dates else None, 'available_end': max(dates) if dates else None,
        'strategies': [*STRATEGIES, SMA_ID], 'strategy_names': names, 'candidate_count': len(candidates), 'trade_count': len(candidates),
        'path_bars': PATH_BARS,
        'costs': {'commission_pct_per_side': BACKTEST_COMMISSION_PCT, 'slippage_bps': BACKTEST_SLIPPAGE_BPS, 'half_spread_bps': BACKTEST_HALF_SPREAD_BPS},
        'errors': errors, 'trades': candidates,
        'limitations': [
            '현재 유동성 종목을 과거로 되감는 연구용 후보풀이라 survivorship bias가 있습니다.',
            '모든 엄선 신호일을 저장해 짧은 강제익절 뒤 다음 신호를 다시 잡을 수 있게 했습니다.',
            '같은 일봉에서 목표와 손절을 모두 터치하면 보수적으로 손절 우선 처리합니다.',
            'SMA200·20 스퀴즈는 실험전략이며 생산 추천에는 아직 사용하지 않습니다.',
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print('eligible', len(eligible), 'candidates', len(candidates), 'errors', len(errors))


if __name__ == '__main__':
    build()
