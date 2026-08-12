import numpy as np
import pandas as pd

from app_v6 import indicators
from core_v2 import score_v2
from core_v3 import _wilder_rsi


def _f(v, default=np.nan):
    try:
        return default if pd.isna(v) else float(v)
    except Exception:
        return default


def _clip(x, lo=0.0, hi=100.0):
    return round(max(lo, min(hi, float(x))), 1)


def _series(df):
    ind = indicators(df)
    if len(ind) < 205:
        raise ValueError('최소 205개 일봉이 필요합니다')
    x, p1, p5, p20 = ind.iloc[-1], ind.iloc[-2], ind.iloc[-6], ind.iloc[-21]
    close = _f(x['close']); s200 = _f(x['sma200']); s120 = _f(x['sma120']); s50 = _f(x['sma50'])
    rsi = _f(x['rsi']); bb = _f(x['bb_pos']); atr = _f(x['atr14']); mh = _f(x['macd_hist']); mh1 = _f(p1['macd_hist'])
    vol = _f(x['volume']); vol20 = _f(x['vol20']); vr = vol / vol20 if vol20 and not pd.isna(vol20) else 1.0
    c = df['Close'].astype(float); h = df['High'].astype(float); l = df['Low'].astype(float)
    ret20 = close / _f(p20['close'], close) - 1; ret5 = close / _f(p5['close'], close) - 1
    high20 = float(h.tail(21).iloc[:-1].max()); low20 = float(l.tail(21).iloc[:-1].min())
    tr = (h-l).tail(10).mean()/close
    tr_prev = (h-l).iloc[-30:-10].mean()/float(c.iloc[-20]) if len(df) >= 30 else tr
    rsi2 = _f(_wilder_rsi(c, 2).iloc[-1], 100.0)
    return locals()


def _quality(points, max_points, active):
    q = 55 + 40 * max(0.0, min(1.0, points / max_points))
    if not active:
        q = min(q, 69)
    return _clip(q, 0, 95)


def playbooks(df, market_state=None):
    z = _series(df); close=z['close']; s200=z['s200']; s120=z['s120']; s50=z['s50']; rsi=z['rsi']; bb=z['bb']; mh=z['mh']; mh1=z['mh1']; vr=z['vr']; ret20=z['ret20']; ret5=z['ret5']; high20=z['high20']; tr=z['tr']; tr_prev=z['tr_prev']; rsi2=z['rsi2']
    trend_ok = close > s200 and s50 >= s120
    market_ok = market_state != '조심'
    d120 = close/s120-1 if s120 and not pd.isna(s120) else 99
    d200 = close/s200-1 if s200 and not pd.isna(s200) else 99

    base = score_v2(df, market_state)
    p_active = bool(base['eligible'])
    p_points = (2 if 30 <= rsi <= 45 else 1 if rsi < 50 else 0) + (2 if abs(base['d120']) <= 2 else 1 if abs(base['d120']) <= 4 else 0) + min(4, int(base['confirm_count'])) + (1 if market_ok else 0)
    pullback = {'id':'confirmed_pullback','name':'확인형 눌림반등','score':_quality(p_points,9,p_active),'active':p_active,
                'why':f"RSI {rsi:.1f} · 120일선 {base['d120']:+.2f}% · 반전확인 {base['confirm_count']}/4",
                'evidence':'지지선까지 눌린 뒤 실제 반전이 확인되는 자리'}

    cooling = rsi <= 55 and bb <= .65 and d120 <= .20 and d200 <= .35
    c_active = bool(trend_ok and market_ok and rsi2 < 5 and cooling)
    c_points = (3 if rsi2 < 3 else 2 if rsi2 < 5 else 0) + (2 if rsi < 45 else 1 if rsi <=55 else 0) + (2 if bb <= .35 else 1 if bb <= .65 else 0) + (1 if abs(d120) <= .10 else 0) + (1 if trend_ok else 0) + (1 if market_ok else 0)
    connors = {'id':'rsi2_trend_reversion','name':'RSI2 추세내 과매도','score':_quality(c_points,10,c_active),'active':c_active,
               'why':f"RSI2 {rsi2:.1f} · RSI14 {rsi:.1f} · 120일선 {d120*100:+.1f}% · 상승추세 {'✓' if trend_ok else '×'}",
               'evidence':'큰 상승추세 안에서 단기 과매도가 생긴 평균회귀 자리'}

    m_active = bool(trend_ok and market_ok and ret20 > .04 and -.06 <= ret5 <= .01 and mh > mh1 and rsi < 65)
    m_points = (2 if trend_ok else 0) + (2 if ret20 > .08 else 1 if ret20 > .04 else 0) + (2 if -.05 <= ret5 <= -.01 else 1 if -.06 <= ret5 <= .01 else 0) + (2 if mh > mh1 else 0) + (1 if 40 <= rsi < 60 else 0) + (1 if market_ok else 0)
    momentum = {'id':'momentum_pullback','name':'모멘텀 눌림 지속','score':_quality(m_points,10,m_active),'active':m_active,
                'why':f"20일 {ret20*100:+.1f}% · 5일 {ret5*100:+.1f}% · RSI {rsi:.1f} · MACD 개선 {'✓' if mh>mh1 else '×'}",
                'evidence':'강한 상승 흐름이 짧게 쉬었다가 다시 힘을 받는 자리'}

    contraction = tr_prev > 0 and tr/tr_prev < .72
    breakout = close > high20
    v_active = bool(trend_ok and market_ok and contraction and breakout and vr >= 1.0 and rsi < 72)
    v_points = (2 if trend_ok else 0) + (2 if contraction else 0) + (3 if breakout else 0) + (2 if vr >= 1.5 else 1 if vr >= 1.0 else 0) + (1 if market_ok else 0)
    vcp = {'id':'volatility_breakout','name':'변동성 수축 돌파','score':_quality(v_points,10,v_active),'active':v_active,
           'why':f"변동성 {tr/tr_prev:.2f}배 · 20일 고점 돌파 {'✓' if breakout else '×'} · 거래량 {vr:.2f}배",
           'evidence':'변동성이 줄어든 뒤 거래량과 함께 고점을 돌파하는 자리'}

    arr=[pullback,connors,momentum,vcp]
    arr.sort(key=lambda q:(q['active'],q['score']),reverse=True)
    best=arr[0]; agreement=sum(q['active'] for q in arr)
    return {'best_strategy':best,'strategies':arr,'agreement':agreement,'ensemble_score':best['score'],'confidence':'높음' if best['active'] and best['score']>=85 else '보통' if best['active'] else '낮음','recommend':bool(best['active'] and best['score']>=72),'reason':f"{best['name']} 신호 · {best['evidence']}" if best['active'] else '현재 완성된 매수 신호가 없습니다.'}


def trade_plan_for(df, strategy_id):
    z=_series(df); close=z['close']; atr=max(z['atr'], close*.005); h=df['High'].astype(float); l=df['Low'].astype(float)
    recent_low=float(l.tail(10).min()); recent_high=float(h.tail(20).max())
    if strategy_id == 'confirmed_pullback':
        buy_low=max(close-0.25*atr, close*.992); buy_high=close+0.15*atr
        stop=min(recent_low, close-0.9*atr); target=max(recent_high, close+1.7*atr); days=(2,8); basis='지지선 반전폭/최근 고점'
    elif strategy_id == 'rsi2_trend_reversion':
        buy_low=close-0.10*atr; buy_high=close+0.10*atr
        stop=close-1.15*atr; target=close+1.25*atr; days=(1,5); basis='단기 평균회귀 ATR'
    elif strategy_id == 'momentum_pullback':
        buy_low=close-0.20*atr; buy_high=close+0.15*atr
        stop=min(recent_low, close-1.05*atr); target=max(recent_high, close+2.0*atr); days=(3,10); basis='추세 재개/직전 고점'
    elif strategy_id == 'volatility_breakout':
        breakout=float(h.tail(21).iloc[:-1].max()); buy_low=max(close,breakout); buy_high=buy_low+0.25*atr
        stop=breakout-0.85*atr; target=buy_low+2.2*atr; days=(2,10); basis='돌파선 재이탈/ATR 확장'
    else:
        raise ValueError('알 수 없는 전략')
    entry=(buy_low+buy_high)/2
    if stop >= entry: stop=entry-atr
    if target <= entry: target=entry+1.5*atr
    risk=entry-stop; reward=target-entry; rr=reward/risk if risk>0 else 0
    target_pct=(target/entry-1)*100; stop_pct=(entry-stop)/entry*100
    return {
        'buy_low':round(buy_low,2),'buy_high':round(buy_high,2),
        'entry_low':round(buy_low,2),'entry_high':round(buy_high,2),
        'target':round(target,2),'stop':round(stop,2),
        'target_pct':round(target_pct,2),'stop_pct':round(stop_pct,2),
        'rr':round(rr,2),'risk_reward':round(rr,2),
        'days_min':days[0],'days_max':days[1],
        'target_days':{'days_low':days[0],'days_high':days[1],'method':'전략별 예상 보유기간'},
        'basis':basis,'target_reason':basis,'stop_reason':basis,
        'strategy_id':strategy_id
    }
