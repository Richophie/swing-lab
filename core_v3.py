import numpy as np
import pandas as pd

from app_v6 import indicators
from core_v2 import score_v2


def _f(v, default=np.nan):
    try:
        return default if pd.isna(v) else float(v)
    except Exception:
        return default


def _clip(x): return round(max(0.0,min(100.0,float(x))),1)


def _series(df):
    ind=indicators(df)
    if len(ind)<205: raise ValueError('최소 205개 일봉이 필요합니다')
    x=ind.iloc[-1]; p1=ind.iloc[-2]; p5=ind.iloc[-6]; p20=ind.iloc[-21]
    close=_f(x['close']); s200=_f(x['sma200']); s120=_f(x['sma120']); s50=_f(x['sma50']); rsi=_f(x['rsi']); bb=_f(x['bb_pos']); atr=_f(x['atr14']); mh=_f(x['macd_hist']); mh1=_f(p1['macd_hist'])
    vol=_f(x['volume']); vol20=_f(x['vol20']); vr=vol/vol20 if vol20 and not pd.isna(vol20) else 1.0
    c=df['Close'].astype(float); h=df['High'].astype(float); l=df['Low'].astype(float)
    ret20=close/_f(p20['close'],close)-1; ret5=close/_f(p5['close'],close)-1
    high20=float(h.tail(21).iloc[:-1].max()); low20=float(l.tail(20).min())
    tr=(h-l).tail(10).mean()/close
    tr_prev=(h-l).iloc[-30:-10].mean()/float(c.iloc[-20]) if len(df)>=30 else tr
    return locals()


def playbooks(df, market_state=None):
    z=_series(df); x=z['x']; close=z['close']; s200=z['s200']; s120=z['s120']; s50=z['s50']; rsi=z['rsi']; bb=z['bb']; atr=z['atr']; mh=z['mh']; mh1=z['mh1']; vr=z['vr']; ret20=z['ret20']; ret5=z['ret5']; high20=z['high20']; tr=z['tr']; tr_prev=z['tr_prev']
    trend_ok=close>s200 and s50>=s120
    market_ok=market_state!='조심'

    # 1) User/core thesis: pullback to support, but only after reversal confirmation.
    base=score_v2(df,market_state)
    pullback={'id':'confirmed_pullback','name':'확인형 눌림반등','score':base['score'],'active':bool(base['eligible']),
              'why':f"RSI {rsi:.1f}, 120일선 거리 {base['d120']:.2f}%, 반전확인 {base['confirm_count']}/4",
              'evidence':'사용자 코어 + 반전확인/장기추세/시장필터'}

    # 2) Connors-style RSI(2) trend mean reversion. RSI2 calculated separately.
    delta=z['c'].diff(); up=delta.clip(lower=0).rolling(2).mean(); dn=(-delta.clip(upper=0)).rolling(2).mean(); rs=up/dn.replace(0,np.nan); rsi2=float((100-100/(1+rs)).iloc[-1]) if not pd.isna(rs.iloc[-1]) else 100.0
    cscore=45 + (25 if trend_ok else -20) + (25 if rsi2<10 else 12 if rsi2<20 else -10) + (8 if market_ok else -12) + (5 if vr>=.7 else 0)
    connors={'id':'rsi2_trend_reversion','name':'RSI2 추세내 과매도','score':_clip(cscore),'active':bool(trend_ok and market_ok and rsi2<10),
             'why':f"200일선 위 {'✓' if close>s200 else '×'} · RSI2 {rsi2:.1f} · 50/120 추세 {'✓' if s50>=s120 else '×'}",
             'evidence':'Connors RSI(2) 계열: 장기 상승추세 안의 단기 과매도'}

    # 3) Momentum continuation after a controlled pullback: medium-term strength + short-term cooling.
    mscore=45 + (20 if trend_ok else -15) + (18 if ret20>0.04 else 8 if ret20>0 else -10) + (12 if -0.06<=ret5<=0.01 else 0) + (8 if mh>mh1 else 0) + (5 if market_ok else -10)
    momentum={'id':'momentum_pullback','name':'모멘텀 눌림 지속','score':_clip(mscore),'active':bool(trend_ok and market_ok and ret20>0.04 and -0.06<=ret5<=0.01 and mh>mh1),
              'why':f"20일 {ret20*100:+.1f}% · 5일 {ret5*100:+.1f}% · MACD 개선 {'✓' if mh>mh1 else '×'}",
              'evidence':'중기 모멘텀 + 단기 조정 후 추세 재개'}

    # 4) Volatility contraction / breakout: contraction + prior trend + breakout confirmation.
    contraction=tr_prev>0 and tr/tr_prev<0.72
    breakout=close>high20
    vscore=40 + (20 if trend_ok else -15) + (18 if contraction else 0) + (17 if breakout else 0) + (8 if vr>=1.2 else 0) + (5 if market_ok else -10)
    vcp={'id':'volatility_breakout','name':'변동성 수축 돌파','score':_clip(vscore),'active':bool(trend_ok and market_ok and contraction and breakout and vr>=1.0),
         'why':f"변동성 수축 {tr/tr_prev:.2f}배 · 20일 고점 돌파 {'✓' if breakout else '×'} · 거래량 {vr:.2f}배",
         'evidence':'추세 + 변동성 수축 + 가격 돌파 확인'}

    arr=[pullback,connors,momentum,vcp]
    arr.sort(key=lambda q:(1 if q['active'] else 0,q['score']),reverse=True)
    active=[q for q in arr if q['active']]
    best=arr[0]
    agreement=sum(q['active'] for q in arr)
    # Agreement is supporting evidence, not additive double-counting. Cap bonus deliberately small.
    ensemble=_clip(best['score'] + min(6,max(0,agreement-1)*2))
    confidence='높음' if agreement>=2 and ensemble>=78 else '보통' if best['active'] else '낮음'
    return {'best_strategy':best,'strategies':arr,'agreement':agreement,'ensemble_score':ensemble,'confidence':confidence,
            'recommend':bool(best['active'] and ensemble>=72),
            'reason':f"오늘 가장 강한 독립 전략은 ‘{best['name']}’입니다. {best['why']}" if best['active'] else '현재 4개 독립 전략 중 완성된 진입 신호가 없습니다.',
            'design_note':'전략 점수를 한데 섞지 않고 독립적으로 판정한 뒤, 오늘 시장/종목에 맞는 최상위 전략을 선택합니다.'}
