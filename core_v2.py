import math
import numpy as np
import pandas as pd

from app_v6 import indicators


def _safe(v, default=np.nan):
    try:
        if pd.isna(v):
            return default
        return float(v)
    except Exception:
        return default


def raw_components(df):
    """Point-in-time score using only rows available up to the current bar."""
    if df is None or len(df) < 205:
        raise ValueError('최소 205개 일봉이 필요합니다')
    ind = indicators(df)
    x = ind.iloc[-1]
    prev1 = ind.iloc[-2]
    prev3 = ind.iloc[-4]
    prev20 = ind.iloc[-21]

    close = _safe(x['close']); open_ = float(df['Open'].iloc[-1])
    rsi = _safe(x['rsi']); bb = _safe(x['bb_pos']); s50 = _safe(x['sma50']); s120 = _safe(x['sma120']); s200 = _safe(x['sma200'])
    mh = _safe(x['macd_hist']); mh1 = _safe(prev1['macd_hist']); atr = _safe(x['atr14']); vol = _safe(x['volume']); vol20 = _safe(x['vol20'])
    if any(pd.isna(v) for v in [close,rsi,bb,s50,s120,s200,mh,atr]):
        raise ValueError('지표 계산에 필요한 데이터가 부족합니다')

    d120 = close/s120 - 1
    atrp = atr/close
    vr = vol/vol20 if vol20 and not pd.isna(vol20) else np.nan
    slope120_20 = s120/_safe(prev20['sma120'], s120)-1
    rsi_delta3 = rsi-_safe(prev3['rsi'], rsi)
    macd_improving = mh > mh1
    price_reversal = close > float(df['Close'].iloc[-2]) or close > open_
    above_long_floor = close >= s200*0.97

    rsiS = 100 if 30<=rsi<=42 else 70 if 25<=rsi<30 else 75 if rsi<=50 else 45 if rsi<=60 else 20
    bbS = 100 if bb<=.12 else 85 if bb<=.30 else 60 if bb<=.50 else 35 if bb<=.75 else 15
    sS = 100 if abs(d120)<=.025 else 78 if -.06<d120<.05 else 42 if .05<=d120<.12 else 20
    macdS = 82 if mh>0 else 30
    trendS = 85 if s50>=s120 else 45
    riskS = 85 if atrp<=.025 else 70 if atrp<=.04 else 45 if atrp<=.06 else 20
    volS = 85 if not pd.isna(vr) and 1.1<=vr<=2.5 else 65 if not pd.isna(vr) and vr>.75 else 40

    score = rsiS*.18 + bbS*.17 + sS*.22 + macdS*.16 + trendS*.12 + volS*.07 + riskS*.08

    penalties=[]
    if rsi_delta3 < -3: penalties.append(('RSI가 아직 하락 중', 7))
    if not macd_improving: penalties.append(('MACD 모멘텀 악화', 5))
    if slope120_20 < -0.01: penalties.append(('120일선 자체가 하락 중', 8))
    if not above_long_floor: penalties.append(('200일선 아래 장기추세 약화', 10))
    if not price_reversal: penalties.append(('반전 캔들 확인 전', 5))
    if rsi < 22 and close < s120*.93: penalties.append(('과매도 추락 구간', 12))
    for _,p in penalties: score -= p

    confirmations = {
        'rsi_turn': rsi_delta3 >= 0,
        'macd_improving': bool(macd_improving),
        'price_reversal': bool(price_reversal),
        'trend_floor': bool(above_long_floor and slope120_20 >= -0.01),
    }
    confirm_count = sum(bool(v) for v in confirmations.values())
    eligible = score >= 72 and confirm_count >= 3 and confirmations['trend_floor']

    return {
        'raw_score': round(max(0,min(100,float(score))),1),
        'rsi': round(rsi,1), 'bb_pos': round(bb*100,1), 'd120': round(d120*100,2), 'atr_pct': round(atrp*100,2),
        'slope120_20': round(slope120_20*100,2), 'rsi_delta3': round(rsi_delta3,1),
        'confirmations': confirmations, 'confirm_count': confirm_count, 'eligible': bool(eligible),
        'penalties': [{'reason':r,'points':p} for r,p in penalties],
    }


def score_v2(df, market_state=None):
    out = raw_components(df)
    score = float(out['raw_score'])
    market_penalty = 0
    if market_state == '조심':
        market_penalty = 8
        score -= market_penalty
    elif market_state == '중립':
        market_penalty = 2
        score -= market_penalty
    score = max(0,min(100,score))
    eligible = bool(out['eligible']) and market_state != '조심'
    grade = 'S' if score>=82 and eligible else 'A' if score>=72 and eligible else 'B' if score>=58 else 'C'
    out.update({'score':round(score,1),'grade':grade,'market_penalty':market_penalty,'eligible':eligible})
    return out


def point_in_time_levels(df):
    """Same structural stop/target idea as live trade_plan, but only uses data available at this bar."""
    if len(df) < 205:
        raise ValueError('일봉 부족')
    ind=indicators(df); x=ind.iloc[-1]
    p=float(x['close']); atr=float(x['atr14']) if not pd.isna(x['atr14']) else p*.025
    s120=float(x['sma120']); bbl=float(x['bb_low']); bbh=float(x['bb_high'])
    low10=float(df['Low'].tail(10).min()); low20=float(df['Low'].tail(20).min()); high20=float(df['High'].tail(20).max()); high60=float(df['High'].tail(60).max())
    stops=[]
    for val,why in [(s120-atr*.18 if s120<p else None,'120일선 지지 붕괴'),(bbl-atr*.12 if bbl<p else None,'볼린저 하단 이탈'),(low10-atr*.18,'최근 10일 저점 이탈'),(low20-atr*.15,'최근 스윙저점 이탈'),(p-atr*1.35,'ATR 변동폭 이탈')]:
        if val and val<p: stops.append((val,why))
    if not stops: stops=[(p-atr*1.35,'ATR 변동폭 이탈')]
    stop,stop_reason=max(stops,key=lambda z:z[0]); stop=max(p*.94,min(p*.988,stop)); risk=p-stop
    targets=[]
    for val,why in [(bbh,'볼린저 상단'),(high20,'최근 20일 고점'),(high60,'최근 60일 고점')]:
        if val and p*1.008<val<=p*1.12: targets.append((val,why))
    targets.append((p+atr*1.65,'ATR 예상 반등폭')); targets.sort(key=lambda z:z[0]); target,why=targets[0]
    target=max(p*1.01,min(p*1.08,target)); rr=(target-p)/risk if risk>0 else 0
    if rr<1.25:
        target=min(p*1.08,p+risk*1.30); why='손익비를 만족하는 현실적 반등폭'; rr=(target-p)/risk if risk>0 else 0
    return {'entry':p,'stop':float(stop),'target':float(target),'stop_pct':(p-stop)/p,'target_pct':(target-p)/p,'risk_reward':rr,'stop_reason':stop_reason,'target_reason':why}
