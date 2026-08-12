from __future__ import annotations

from functools import lru_cache
import math
import numpy as np
import pandas as pd
from flask import jsonify

from app_v11 import app
from app_v8 import load_df
from app_v6 import indicators, market_live
from core_v3 import playbooks
from core_v2 import point_in_time_levels


def _market_ok_index(index):
    try:
        spy = load_df('SPY', '10y')
        c = spy['Close'].astype(float)
        ok = (c >= c.rolling(120).mean()) & (c >= c.rolling(200).mean())
        return ok.reindex(index).ffill().fillna(False)
    except Exception:
        return pd.Series(True, index=index)


def _rsi2(close):
    delta = close.diff()
    up = delta.clip(lower=0).rolling(2).mean()
    dn = (-delta.clip(upper=0)).rolling(2).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100)


def _signal_frame(d, strategy_id):
    ind = indicators(d)
    close = d['Close'].astype(float)
    open_ = d['Open'].astype(float)
    high = d['High'].astype(float)
    low = d['Low'].astype(float)
    volume = d['Volume'].astype(float) if 'Volume' in d else pd.Series(0, index=d.index)
    s50, s120, s200 = ind['sma50'], ind['sma120'], ind['sma200']
    rsi, bb, atr, mh = ind['rsi'], ind['bb_pos'], ind['atr14'], ind['macd_hist']
    vol20 = ind['vol20']
    market_ok = _market_ok_index(d.index)
    trend_ok = (close > s200) & (s50 >= s120)

    if strategy_id == 'rsi2_trend_reversion':
        signal = trend_ok & market_ok & (_rsi2(close) < 10)
    elif strategy_id == 'momentum_pullback':
        ret20 = close / close.shift(20) - 1
        ret5 = close / close.shift(5) - 1
        signal = trend_ok & market_ok & (ret20 > .04) & ret5.between(-.06, .01) & (mh > mh.shift(1))
    elif strategy_id == 'volatility_breakout':
        tr10 = (high - low).rolling(10).mean() / close
        tr_prev = (high - low).shift(10).rolling(20).mean() / close.shift(20)
        contraction = (tr_prev > 0) & ((tr10 / tr_prev) < .72)
        breakout = close > high.shift(1).rolling(20).max()
        vr = volume / vol20.replace(0, np.nan)
        signal = trend_ok & market_ok & contraction & breakout & (vr >= 1.0)
    else:
        d120 = close / s120 - 1
        atrp = atr / close
        vr = volume / vol20.replace(0, np.nan)
        rsiS = np.select([(rsi >= 30) & (rsi <= 42), (rsi >= 25) & (rsi < 30), rsi <= 50, rsi <= 60], [100, 70, 75, 45], default=20)
        bbS = np.select([bb <= .12, bb <= .30, bb <= .50, bb <= .75], [100, 85, 60, 35], default=15)
        sS = np.select([d120.abs() <= .025, (d120 > -.06) & (d120 < .05), (d120 >= .05) & (d120 < .12)], [100, 78, 42], default=20)
        macdS = np.where(mh > 0, 82, 30)
        trendS = np.where(s50 >= s120, 85, 45)
        riskS = np.select([atrp <= .025, atrp <= .04, atrp <= .06], [85, 70, 45], default=20)
        volS = np.select([(vr >= 1.1) & (vr <= 2.5), vr > .75], [85, 65], default=40)
        score = rsiS*.18 + bbS*.17 + sS*.22 + macdS*.16 + trendS*.12 + volS*.07 + riskS*.08
        rsi_turn = (rsi - rsi.shift(3)) >= 0
        macd_up = mh > mh.shift(1)
        price_rev = (close > close.shift(1)) | (close > open_)
        slope120 = s120 / s120.shift(20) - 1
        trend_floor = (close >= s200*.97) & (slope120 >= -.01)
        score = score - np.where((rsi-rsi.shift(3)) < -3, 7, 0) - np.where(~macd_up.fillna(False), 5, 0) - np.where(slope120 < -.01, 8, 0) - np.where(close < s200*.97, 10, 0) - np.where(~price_rev.fillna(False), 5, 0)
        confirm = rsi_turn.fillna(False).astype(int) + macd_up.fillna(False).astype(int) + price_rev.fillna(False).astype(int) + trend_floor.fillna(False).astype(int)
        signal = (score >= 72) & (confirm >= 3) & trend_floor & market_ok

    return pd.DataFrame({'signal': signal.fillna(False), 'atr': atr, 'close': close}, index=d.index)


def _simulate(d, strategy_id, max_hold=5, commission=.001):
    f = _signal_frame(d, strategy_id)
    trades = []
    i = 205
    n = len(d)
    while i < n - 2:
        if not bool(f['signal'].iloc[i]):
            i += 1
            continue
        entry_i = i + 1
        entry = float(d['Open'].iloc[entry_i])
        try:
            lv = point_in_time_levels(d.iloc[:i+1])
            target_pct = max(.01, min(.08, float(lv['target_pct'])))
            stop_pct = max(.012, min(.06, float(lv['stop_pct'])))
        except Exception:
            atrp = float(f['atr'].iloc[i]) / float(f['close'].iloc[i]) if pd.notna(f['atr'].iloc[i]) else .025
            target_pct = max(.01, min(.08, atrp*1.65))
            stop_pct = max(.012, min(.06, atrp*1.35))
        target = entry * (1 + target_pct)
        stop = entry * (1 - stop_pct)
        exit_px = float(d['Close'].iloc[min(entry_i+max_hold, n-1)])
        exit_i = min(entry_i+max_hold, n-1)
        reason = '기간종료'
        for j in range(entry_i, min(entry_i+max_hold, n-1)+1):
            hi = float(d['High'].iloc[j]); lo = float(d['Low'].iloc[j])
            if lo <= stop and hi >= target:
                exit_px, exit_i, reason = stop, j, '손절'
                break
            if lo <= stop:
                exit_px, exit_i, reason = stop, j, '손절'
                break
            if hi >= target:
                exit_px, exit_i, reason = target, j, '목표달성'
                break
        ret = exit_px / entry - 1 - commission*2
        trades.append({'entry_i': entry_i, 'exit_i': exit_i, 'ret': ret, 'reason': reason})
        i = exit_i + 1
    return trades


def _stats(d, trades):
    if not trades:
        return {'return_pct':0,'buy_hold_pct':round((float(d['Close'].iloc[-1])/float(d['Close'].iloc[0])-1)*100,2),'win_rate':0,'trades':0,'max_drawdown':0,'profit_factor':None,'sharpe':None,'avg_trade':0,'best_trade':0,'worst_trade':0,'exposure':0}
    r = np.array([t['ret'] for t in trades], dtype=float)
    equity = np.cumprod(1+r)
    peak = np.maximum.accumulate(equity)
    dd = equity/peak - 1
    gains = r[r>0].sum(); losses = -r[r<0].sum()
    bars = sum(t['exit_i']-t['entry_i']+1 for t in trades)
    return {
        'return_pct': round((equity[-1]-1)*100,2),
        'buy_hold_pct': round((float(d['Close'].iloc[-1])/float(d['Close'].iloc[0])-1)*100,2),
        'win_rate': round(float((r>0).mean()*100),1),
        'trades': int(len(r)),
        'max_drawdown': round(float(dd.min()*100),2),
        'profit_factor': None if losses<=0 else round(float(gains/losses),2),
        'sharpe': None if r.std(ddof=1)==0 or len(r)<2 else round(float(r.mean()/r.std(ddof=1)*math.sqrt(len(r))),2),
        'avg_trade': round(float(r.mean()*100),2),
        'best_trade': round(float(r.max()*100),2),
        'worst_trade': round(float(r.min()*100),2),
        'exposure': round(bars/max(1,len(d))*100,1),
    }


@lru_cache(maxsize=256)
def fast_backtest_cached(symbol, strategy_id):
    d = load_df(symbol, '10y')
    full_trades = _simulate(d, strategy_id)
    recent = d.tail(504).copy()
    recent_trades = _simulate(recent, strategy_id) if len(recent) > 220 else []
    return {
        'symbol': symbol,
        'engine': 'Swing Lab Fast Vector Engine',
        'strategy_id': strategy_id,
        'full_10y': _stats(d, full_trades),
        'recent_2y': _stats(recent, recent_trades),
        'assumptions': {'commission_pct':0.1,'max_hold_days':5,'entry_execution':'signal next-day open'},
        'speed_note': '10년 지표를 한 번에 계산하고 실제 신호가 발생한 날짜만 정밀 시뮬레이션합니다.'
    }


@app.route('/api/backtest-fast/<symbol>')
def backtest_fast(symbol):
    try:
        s = symbol.upper().strip()
        d = load_df(s, '10y')
        state = None
        try: state = market_live().get('state')
        except Exception: pass
        ens = playbooks(d, state)
        strategy = ens['best_strategy']['id']
        out = fast_backtest_cached(s, strategy)
        out = dict(out)
        out['strategy_name'] = ens['best_strategy']['name']
        return jsonify(out)
    except Exception as e:
        return jsonify({'error':str(e)}), 400


def index_v12():
    return app.send_static_file('v12.html')

app.view_functions['index'] = index_v12


@app.route('/api/version-v12')
def version_v12():
    return {'version':'12.0','focus':['calm hierarchy','decision-first dashboard','clean technical chart','fast vectorized backtest','progressive disclosure']}
