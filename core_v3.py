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


def _wilder_rsi(series, period=2):
    delta=series.diff()
    gain=delta.clip(lower=0)
    loss=-delta.clip(upper=0)
    avg_gain=gain.ewm(alpha=1/period,adjust=False,min_periods=period).mean()
    avg_loss=loss.ewm(alpha=1/period,adjust=False,min_periods=period).mean()
    rs=avg_gain/avg_loss.replace(0,np.nan)
    out=100-100/(1+rs)
    out=out.where(avg_loss.ne(0),100)
    out=out.where(avg_gain.ne(0),0)
    return out.clip(0,100)


def playbooks(df, market_state=None):
    z=_series(df); x=z['x']; close=z['close']; s200=z['s200']; s120=z['s120']; s50=z['s50']; rsi=z['rsi']; bb=z['bb']; atr=z['atr']; mh=z['mh']; mh1=z['mh1']; vr=z['vr']; ret20=z['ret20']; ret5=z['ret5']; high20=z['high20']; tr=z['tr']; tr_prev=z['tr_prev']
    trend_ok=close>s200 and s50>=s120
    market_ok=market_state!='조심'

    # 1) User/core thesis: pullback to support, but only after reversal confirmation.
    base=score_v2(df,market_state)
    pullback={'id':'confirmed_pullback','name':'확인형 눌림반등','score':base['score'],'active':bool(base['eligible']),
              'why':f"RSI {rsi:.1f}, 120일선 거리 {base['d120']:.2f}%, 반전확인 {base['confirm_count']}/4",
              'evidence':'사용자 코어 + 반전확인/장기추세/시장필터'}

    # 2) Connors-style RSI(2) mean reversion inside an established uptrend.
    # Use Wilder-style RSI(2), not a 2-bar simple average that collapses to 0/100 too easily.
    rsi2s=_wilder_rsi(z['c'],2); rsi2=_f(rsi2s.iloc[-1],100.0)
    d120=close/s120-1 if s120 and not pd.isna(s120) else 99
    d200=close/s200-1 if s200 and not pd.isna(s200) else 99
    cooling=(rsi<=55 and bb<=0.65 and d120<=0.20 and d200<=0.35)
    extreme= rsi2<5
    cscore=52
    cscore += 12 if trend_ok else -22
    cscore += 16 if rsi2<3 else 12 if rsi2<5 else 6 if rsi2<10 else -10
    cscore += 8 if rsi<45 else 4 if rsi<=55 else -10
    cscore += 5 if bb<=.35 else 2 if bb<=.65 else -6
    cscore += 4 if abs(d120)<=.10 else 1 if d120<=.20 else -8
    cscore += 3 if market_ok else -10
    cscore += 2 if vr>=.7 else 0
    cscore=min(cscore,88)
    connors_active=bool(trend_ok and market_ok and extreme and cooling)
    connors={'id':'rsi2_trend_reversion','name':'RSI2 추세내 과매도','score':_clip(cscore),'active':connors_active,
             'why':f"RSI2 {rsi2:.1f} · RSI14 {rsi:.1f} · 120일선 {d120*100:+.1f}% · 상승추세 {'✓' if trend_ok else '×'}",
             'evidence':'장기 상승추세 안에서 단기 과매도 후 반등을 노리는 RSI(2) 계열'}

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
    best=arr[0]
    agreement=sum(q['active'] for q in arr)
    # Agreement is context only; it cannot turn a mediocre strategy into an S grade.
    ensemble=_clip(best['score'] + min(3,max(0,agreement-1)))
    confidence='높음' if best['active'] and best['score']>=82 else '보통' if best['active'] else '낮음'
    return {'best_strategy':best,'strategies':arr,'agreement':agreement,'ensemble_score':ensemble,'confidence':confidence,
            'recommend':bool(best['active'] and ensemble>=72),
            'reason':f"오늘 가장 강한 독립 전략은 ‘{best['name']}’입니다. {best['why']}" if best['active'] else '현재 4개 독립 전략 중 완성된 진입 신호가 없습니다.',
            'design_note':'전략 점수를 한데 섞지 않고 독립적으로 판정한 뒤, 오늘 시장/종목에 맞는 최상위 전략을 선택합니다.'}
