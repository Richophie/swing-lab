from __future__ import annotations

import numpy as np
import pandas as pd

from config import S_THRESHOLD, PUBLIC_STRATEGIES, EXPERIMENTAL_STRATEGIES
from market_data import indicators, wilder_rsi


def _f(v, default=np.nan):
    try:return default if pd.isna(v) else float(v)
    except Exception:return default


def _clip(x, lo=0.0, hi=100.0):return round(max(lo,min(hi,float(x))),1)


def _context(df: pd.DataFrame) -> dict:
    if df is None or len(df)<205:raise ValueError('최소 205개 일봉이 필요합니다')
    ind=indicators(df);x,p1,p3,p5,p20=ind.iloc[-1],ind.iloc[-2],ind.iloc[-4],ind.iloc[-6],ind.iloc[-21]
    close=_f(x['close']);s20=_f(x.get('sma20'),_f(df['Close'].astype(float).rolling(20).mean().iloc[-1]));s50=_f(x['sma50']);s60=_f(df['Close'].astype(float).rolling(60).mean().iloc[-1]);s120=_f(x['sma120']);s200=_f(x['sma200']);rsi=_f(x['rsi']);bb=_f(x['bb_pos']);bb_low=_f(x['bb_low']);atr=_f(x['atr14']);mh=_f(x['macd_hist']);mh1=_f(p1['macd_hist'])
    if any(pd.isna(v) for v in [close,s50,s120,s200,rsi,bb,atr,mh]):raise ValueError('지표 계산에 필요한 데이터가 부족합니다')
    vol=_f(x['volume']);vol20=_f(x['vol20']);vr=vol/vol20 if vol20 and not pd.isna(vol20) else 1.0
    c=df['Close'].astype(float);h=df['High'].astype(float);l=df['Low'].astype(float);o=df['Open'].astype(float);v=df['Volume'].astype(float)
    d120=close/s120-1;d200=close/s200-1;atrp=atr/close;slope120=s120/_f(p20['sma120'],s120)-1;rsi_delta3=rsi-_f(p3['rsi'],rsi);macd_up=mh>mh1;price_reversal=close>float(c.iloc[-2]) or close>float(o.iloc[-1]);trend_floor=close>=s200*.97 and slope120>=-.01
    ret20=close/_f(p20['close'],close)-1;ret5=close/_f(p5['close'],close)-1;high20=float(h.tail(21).iloc[:-1].max());recent_low=float(l.tail(10).min());recent_high=float(h.tail(20).max());tr=float((h-l).tail(10).mean()/close);tr_prev=float((h-l).iloc[-30:-10].mean()/float(c.iloc[-20])) if len(df)>=30 else tr;rsi2=_f(wilder_rsi(c,2).iloc[-1],100.0)
    down=(c<c.shift(1));up=(c>c.shift(1));down_vol=float(v.where(down).tail(10).mean() or 0);up_vol=float(v.where(up).tail(10).mean() or 0);sell_dry=down_vol>0 and up_vol/down_vol;dollar_vol20=float((c*v).tail(20).mean());vol5=float(v.tail(5).mean()/max(v.tail(20).mean(),1));reversal_vol=float(v.iloc[-1]/max(v.tail(20).mean(),1)) if price_reversal else 0
    return locals()


def _pullback_base(z: dict, market_state: str|None) -> dict:
    rsi=z['rsi'];bb=z['bb'];d120=z['d120'];mh=z['mh'];s50=z['s50'];s120=z['s120'];atrp=z['atrp'];vr=z['vr'];rsi_delta3=z['rsi_delta3'];macd_up=z['macd_up'];slope120=z['slope120'];trend_floor=z['trend_floor'];price_reversal=z['price_reversal'];close=z['close'];s200=z['s200']
    rsiS=100 if 30<=rsi<=42 else 70 if 25<=rsi<30 else 75 if rsi<=50 else 45 if rsi<=60 else 20;bbS=100 if bb<=.12 else 85 if bb<=.30 else 60 if bb<=.50 else 35 if bb<=.75 else 15;sS=100 if abs(d120)<=.025 else 78 if -.06<d120<.05 else 42 if .05<=d120<.12 else 20;macdS=82 if mh>0 else 30;trendS=85 if s50>=s120 else 45;riskS=85 if atrp<=.025 else 70 if atrp<=.04 else 45 if atrp<=.06 else 20;volS=85 if 1.1<=vr<=2.5 else 65 if vr>.75 else 40
    score=rsiS*.18+bbS*.17+sS*.22+macdS*.16+trendS*.12+volS*.07+riskS*.08;penalties=[]
    if rsi_delta3<-3:penalties.append(('RSI가 아직 하락 중',7))
    if not macd_up:penalties.append(('MACD 모멘텀 악화',5))
    if slope120<-.01:penalties.append(('120일선 자체가 하락 중',8))
    if close<s200*.97:penalties.append(('200일선 아래 장기추세 약화',10))
    if not price_reversal:penalties.append(('반전 캔들 확인 전',5))
    if rsi<22 and close<s120*.93:penalties.append(('과매도 추락 구간',12))
    for _,p in penalties:score-=p
    if market_state=='중립':score-=2
    if market_state=='조심':score-=8
    confirmations={'rsi_turn':rsi_delta3>=0,'macd_improving':bool(macd_up),'price_reversal':bool(price_reversal),'trend_floor':bool(trend_floor)};count=sum(bool(v) for v in confirmations.values());eligible=score>=72 and count>=3 and trend_floor and market_state!='조심'
    return {'score':_clip(score),'eligible':bool(eligible),'confirm_count':count,'confirmations':confirmations,'penalties':penalties}


def _quality(points: float,max_points: float,active: bool)->float:
    q=55+40*max(0,min(1,points/max_points))
    if not active:q=min(q,69)
    return _clip(q,0,95)


def evaluate_strategies(df: pd.DataFrame, market_state: str|None=None) -> dict:
    z=_context(df);close=z['close'];s50=z['s50'];s120=z['s120'];s200=z['s200'];rsi=z['rsi'];bb=z['bb'];mh=z['mh'];mh1=z['mh1'];vr=z['vr'];ret20=z['ret20'];ret5=z['ret5'];high20=z['high20'];tr=z['tr'];tr_prev=z['tr_prev'];rsi2=z['rsi2'];d120=z['d120'];d200=z['d200'];atrp=z['atrp']
    market_ok=market_state!='조심';trend_ok=close>s200 and s50>=s120
    base=_pullback_base(z,market_state)
    pullback_strict=bool(base['eligible'] and base['confirm_count']==4 and 30<=rsi<=43 and bb<=.40 and abs(d120)<=.035 and atrp<=.045)
    pp=(2 if 30<=rsi<=42 else 1 if rsi<=45 else 0)+(2 if abs(d120)<=.02 else 1 if abs(d120)<=.035 else 0)+min(4,base['confirm_count'])+(1 if bb<=.30 else 0)+(1 if atrp<=.035 else 0)
    pullback={'id':'confirmed_pullback','name':'확인형 눌림반등','score':_quality(pp,10,pullback_strict),'active':pullback_strict,'strict':pullback_strict,'why':f"RSI {rsi:.1f} · 120일선 {d120*100:+.2f}% · 볼린저 {bb*100:.1f}% · 반전확인 {base['confirm_count']}/4",'evidence':'120일선 근처에서 충분히 눌린 뒤 네 가지 반전 확인이 모두 나온 자리'}
    rsi2_strict=bool(trend_ok and market_ok and rsi2<3 and rsi<=50 and bb<=.45 and -.03<=d120<=.12 and d200<=.25 and atrp<=.05)
    cp=(3 if rsi2<2 else 2 if rsi2<3 else 0)+(2 if rsi<42 else 1 if rsi<=50 else 0)+(2 if bb<=.25 else 1 if bb<=.45 else 0)+(1 if abs(d120)<=.06 else 0)+(1 if trend_ok else 0)+(1 if atrp<=.04 else 0)
    rsi2s={'id':'rsi2_trend_reversion','name':'RSI2 추세내 과매도','score':_quality(cp,10,rsi2_strict),'active':rsi2_strict,'strict':rsi2_strict,'why':f"RSI2 {rsi2:.1f} · RSI14 {rsi:.1f} · 120일선 {d120*100:+.1f}% · 볼린저 {bb*100:.1f}%",'evidence':'장기 상승추세는 유지하면서 단기 과매도와 가격 눌림이 동시에 강한 자리'}
    momentum_strict=bool(trend_ok and market_ok and .05<=ret20<=.20 and -.05<=ret5<=-.005 and mh>mh1 and 42<=rsi<=60 and 0<=d120<=.20 and bb<=.80 and atrp<=.06)
    mp=(2 if trend_ok else 0)+(2 if .08<=ret20<=.16 else 1 if .05<=ret20<=.20 else 0)+(2 if -.04<=ret5<=-.01 else 1 if -.05<=ret5<=-.005 else 0)+(2 if mh>mh1 else 0)+(1 if 45<=rsi<=58 else 0)+(1 if d120<=.12 else 0)
    momentum={'id':'momentum_pullback','name':'모멘텀 눌림 지속','score':_quality(mp,10,momentum_strict),'active':momentum_strict,'strict':momentum_strict,'why':f"20일 {ret20*100:+.1f}% · 5일 {ret5*100:+.1f}% · RSI {rsi:.1f} · 120일선 {d120*100:+.1f}%",'evidence':'과열 추격이 아니라 강한 상승 뒤 1~5일 조정을 거치고 모멘텀이 다시 개선되는 자리'}
    contraction=tr_prev>0 and tr/tr_prev<.72;breakout=close>high20;va=bool(trend_ok and market_ok and contraction and breakout and vr>=1.2 and 45<=rsi<68 and atrp<=.07);vp=(2 if trend_ok else 0)+(2 if contraction else 0)+(3 if breakout else 0)+(2 if vr>=1.5 else 1 if vr>=1.2 else 0)+(1 if 50<=rsi<=65 else 0)
    vcp={'id':'volatility_breakout','name':'변동성 수축 돌파','score':_quality(vp,10,va),'active':va,'strict':va,'why':f"변동성 {tr/tr_prev:.2f}배 · 20일 고점 돌파 {'✓' if breakout else '×'} · 거래량 {vr:.2f}배",'evidence':'변동성이 줄어든 뒤 거래량과 함께 고점을 돌파하는 자리'}
    strategies=[pullback,rsi2s,momentum,vcp];strategies.sort(key=lambda q:(q['active'],q['score']),reverse=True);best=strategies[0]
    flow={'relative_volume':round(vr,2),'volume_5d_vs_20d':round(z['vol5'],2),'reversal_volume':round(z['reversal_vol'],2),'up_down_volume_ratio':round(z['sell_dry'],2) if z['sell_dry'] else None,'avg_dollar_volume_20d':round(z['dollar_vol20'],0)}
    return {'best_strategy':best,'strategies':strategies,'agreement':sum(q['active'] for q in strategies),'ensemble_score':best['score'],'recommend':bool(best['active'] and best['score']>=S_THRESHOLD),'metrics':{'rsi':round(rsi,1),'bb_pos':round(bb*100,1),'d120':round(d120*100,2),'atr_pct':round(atrp*100,2),'rsi2':round(rsi2,1),'ret20_pct':round(ret20*100,2),'ret5_pct':round(ret5*100,2)},'flow':flow}


def trade_plan(df: pd.DataFrame,strategy_id: str)->dict:
    z=_context(df);close=z['close'];atr=max(z['atr'],close*.005);recent_low=z['recent_low'];recent_high=z['recent_high'];h=df['High'].astype(float);s20=z['s20'];s120=z['s120']
    ev=evaluate_strategies(df,None);chosen=next((s for s in ev['strategies'] if s['id']==strategy_id),None);active=bool(chosen and chosen['active'])
    if not active:
        reference='120일선 재회복 후 반전 확인' if strategy_id in {'confirmed_pullback','rsi2_trend_reversion'} else '20일선 눌림 후 추세 재개 확인' if strategy_id=='momentum_pullback' else '돌파 조건 재형성 확인'
        return {'entry_low':None,'entry_high':None,'target':None,'stop':None,'target_pct':None,'stop_pct':None,'risk_reward':None,'days_min':None,'days_max':None,'target_days':{'days_low':None,'days_high':None,'method':'현재 매수 신호 없음'},'basis':reference,'target_reason':'현재 매수 신호 없음','stop_reason':'현재 매수 신호 없음','strategy_id':strategy_id,'entry_reference':reference,'entry_status':'현재 매수 신호 없음','signal_active':False,'current_vs_entry_pct':None,'current_price':round(close,2)}
    if strategy_id=='confirmed_pullback':
        anchor=s120;buy_low=anchor-.18*atr;buy_high=anchor+.22*atr;stop=min(recent_low,anchor-.95*atr);target=max(recent_high,anchor+1.8*atr);days=(2,8);basis='120일선 지지/최근 고점';entry_reference='120일선 지지구간'
    elif strategy_id=='rsi2_trend_reversion':
        anchor=close;buy_low=anchor-.12*atr;buy_high=anchor+.12*atr;stop=min(recent_low,anchor-1.15*atr);target=max(anchor+1.3*atr,s20 if s20>anchor else anchor+1.3*atr);days=(1,5);basis='단기 평균회귀/추세 복귀';entry_reference='현재 과매도 구간'
    elif strategy_id=='momentum_pullback':
        anchor=s20 if np.isfinite(s20) else close;buy_low=anchor-.20*atr;buy_high=anchor+.18*atr;stop=min(recent_low,anchor-1.05*atr);target=max(recent_high,anchor+2.0*atr);days=(3,10);basis='20일선 눌림/추세 재개';entry_reference='20일선 눌림구간'
    elif strategy_id=='volatility_breakout':
        breakout=float(h.tail(21).iloc[:-1].max());buy_low=breakout;buy_high=breakout+.25*atr;stop=breakout-.85*atr;target=breakout+2.2*atr;days=(2,10);basis='돌파선 재이탈/ATR 확장';entry_reference='20일 고점 돌파구간'
    else:raise ValueError('알 수 없는 전략')
    entry=(buy_low+buy_high)/2
    if stop>=entry:stop=entry-atr
    if target<=entry:target=entry+1.5*atr
    risk=entry-stop;reward=target-entry;rr=reward/risk if risk>0 else 0
    current_vs_entry=(close/entry-1)*100 if entry else 0
    entry_status='진입 적정' if buy_low<=close<=buy_high else '진입구간 대기'
    return {'entry_low':round(buy_low,2),'entry_high':round(buy_high,2),'target':round(target,2),'stop':round(stop,2),'target_pct':round((target/entry-1)*100,2),'stop_pct':round((entry-stop)/entry*100,2),'risk_reward':round(rr,2),'days_min':days[0],'days_max':days[1],'target_days':{'days_low':days[0],'days_high':days[1],'method':'전략별 예상 보유기간'},'basis':basis,'target_reason':basis,'stop_reason':basis,'strategy_id':strategy_id,'entry_reference':entry_reference,'entry_status':entry_status,'signal_active':True,'current_vs_entry_pct':round(current_vs_entry,2),'current_price':round(close,2)}


def public_s_signals(evaluation: dict)->list[dict]:return [s for s in evaluation['strategies'] if s['id'] in PUBLIC_STRATEGIES and s['active'] and s.get('strict') and float(s['score'])>=S_THRESHOLD]
def experimental_s_signals(evaluation: dict)->list[dict]:return [s for s in evaluation['strategies'] if s['id'] in EXPERIMENTAL_STRATEGIES and s['active'] and float(s['score'])>=S_THRESHOLD]
