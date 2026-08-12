from __future__ import annotations

import math
import numpy as np
import pandas as pd

from market_data import indicators, wilder_rsi, load_price_history


def _market_ok_index(index):
    try:
        spy=load_price_history('SPY','10y');c=spy['Close'].astype(float);ok=(c>=c.rolling(120).mean())&(c>=c.rolling(200).mean());return ok.reindex(index).ffill().fillna(False)
    except Exception:return pd.Series(True,index=index)


def signal_frame(d,strategy_id):
    ind=indicators(d);close=d['Close'].astype(float);open_=d['Open'].astype(float);high=d['High'].astype(float);low=d['Low'].astype(float);volume=d['Volume'].astype(float) if 'Volume' in d else pd.Series(0,index=d.index)
    s50,s120,s200=ind['sma50'],ind['sma120'],ind['sma200'];rsi,bb,atr,mh=ind['rsi'],ind['bb_pos'],ind['atr14'],ind['macd_hist'];vol20=ind['vol20'];market_ok=_market_ok_index(d.index);trend_ok=(close>s200)&(s50>=s120);d120=close/s120-1;d200=close/s200-1;vr=volume/vol20.replace(0,np.nan);atrp=atr/close
    if strategy_id=='rsi2_trend_reversion':
        rsi2=wilder_rsi(close,2);signal=trend_ok&market_ok&(rsi2<3)&(rsi<=50)&(bb<=.45)&d120.between(-.03,.12)&(d200<=.25)&(atrp<=.05)
    elif strategy_id=='momentum_pullback':
        ret20=close/close.shift(20)-1;ret5=close/close.shift(5)-1;signal=trend_ok&market_ok&ret20.between(.05,.20)&ret5.between(-.05,-.005)&(mh>mh.shift(1))&rsi.between(42,60)&d120.between(0,.20)&(bb<=.80)&(atrp<=.06)
    elif strategy_id=='volatility_breakout':
        tr10=(high-low).rolling(10).mean()/close;tr_prev=(high-low).shift(10).rolling(20).mean()/close.shift(20);signal=trend_ok&market_ok&(tr_prev>0)&((tr10/tr_prev)<.72)&(close>high.shift(1).rolling(20).max())&(vr>=1.2)&rsi.between(45,68,inclusive='left')&(atrp<=.07)
    else:
        rsiS=np.select([(rsi>=30)&(rsi<=42),(rsi>=25)&(rsi<30),rsi<=50,rsi<=60],[100,70,75,45],default=20);bbS=np.select([bb<=.12,bb<=.30,bb<=.50,bb<=.75],[100,85,60,35],default=15);sS=np.select([d120.abs()<=.025,(d120>-.06)&(d120<.05),(d120>=.05)&(d120<.12)],[100,78,42],default=20);macdS=np.where(mh>0,82,30);trendS=np.where(s50>=s120,85,45);riskS=np.select([atrp<=.025,atrp<=.04,atrp<=.06],[85,70,45],default=20);volS=np.select([(vr>=1.1)&(vr<=2.5),vr>.75],[85,65],default=40);score=rsiS*.18+bbS*.17+sS*.22+macdS*.16+trendS*.12+volS*.07+riskS*.08
        rsi_turn=(rsi-rsi.shift(3))>=0;macd_up=mh>mh.shift(1);price_rev=(close>close.shift(1))|(close>open_);slope120=s120/s120.shift(20)-1;trend_floor=(close>=s200*.97)&(slope120>=-.01);score=score-np.where((rsi-rsi.shift(3))<-3,7,0)-np.where(~macd_up.fillna(False),5,0)-np.where(slope120<-.01,8,0)-np.where(close<s200*.97,10,0)-np.where(~price_rev.fillna(False),5,0);confirm=rsi_turn.fillna(False).astype(int)+macd_up.fillna(False).astype(int)+price_rev.fillna(False).astype(int)+trend_floor.fillna(False).astype(int)
        signal=(score>=72)&(confirm==4)&trend_floor&market_ok&rsi.between(30,43)&(bb<=.40)&(d120.abs()<=.035)&(atrp<=.045)
    return pd.DataFrame({'signal':signal.fillna(False),'atr':atr,'close':close},index=d.index)


def _exit_rules(strategy_id,entry,atr,prior_high,prior_low):
    atr=max(float(atr) if pd.notna(atr) else entry*.025,entry*.005)
    if strategy_id=='confirmed_pullback':return max(prior_high,entry+1.7*atr),min(prior_low,entry-.9*atr),8
    if strategy_id=='rsi2_trend_reversion':return entry+1.25*atr,entry-1.15*atr,5
    if strategy_id=='momentum_pullback':return max(prior_high,entry+2.0*atr),min(prior_low,entry-1.05*atr),10
    return entry+2.2*atr,prior_high-.85*atr,10


def simulate(d,strategy_id,commission=.001):
    frame=signal_frame(d,strategy_id);trades=[];i=205;n=len(d)
    while i<n-2:
        if not bool(frame['signal'].iloc[i]):i+=1;continue
        entry_i=i+1;entry=float(d['Open'].iloc[entry_i]);atr=frame['atr'].iloc[i];prior_high=float(d['High'].iloc[max(0,i-20):i+1].max());prior_low=float(d['Low'].iloc[max(0,i-10):i+1].min());target,stop,max_hold=_exit_rules(strategy_id,entry,atr,prior_high,prior_low)
        if stop>=entry:stop=entry-max(float(atr),entry*.01)
        if target<=entry:target=entry+max(float(atr)*1.5,entry*.01)
        exit_i=min(entry_i+max_hold,n-1);exit_px=float(d['Close'].iloc[exit_i]);reason='기간종료'
        for j in range(entry_i,exit_i+1):
            hi=float(d['High'].iloc[j]);lo=float(d['Low'].iloc[j])
            if lo<=stop:exit_px,exit_i,reason=stop,j,'손절';break
            if hi>=target:exit_px,exit_i,reason=target,j,'목표달성';break
        trades.append({'entry_i':entry_i,'exit_i':exit_i,'ret':exit_px/entry-1-commission*2,'reason':reason});i=exit_i+1
    return trades


def stats(d,trades):
    if not trades:return {'return_pct':0,'buy_hold_pct':round((float(d['Close'].iloc[-1])/float(d['Close'].iloc[0])-1)*100,2),'win_rate':0,'trades':0,'max_drawdown':0,'profit_factor':None,'sharpe':None,'avg_trade':0}
    r=np.array([t['ret'] for t in trades],dtype=float);equity=np.cumprod(1+r);peak=np.maximum.accumulate(equity);dd=equity/peak-1;gains=r[r>0].sum();losses=-r[r<0].sum()
    return {'return_pct':round((equity[-1]-1)*100,2),'buy_hold_pct':round((float(d['Close'].iloc[-1])/float(d['Close'].iloc[0])-1)*100,2),'win_rate':round(float((r>0).mean()*100),1),'trades':len(r),'max_drawdown':round(float(dd.min()*100),2),'profit_factor':None if losses<=0 else round(float(gains/losses),2),'sharpe':None if len(r)<2 or r.std(ddof=1)==0 else round(float(r.mean()/r.std(ddof=1)*math.sqrt(len(r))),2),'avg_trade':round(float(r.mean()*100),2)}


def run_backtest_on_frame(d,strategy_id):
    recent=d.tail(504).copy();return {'full_10y':stats(d,simulate(d,strategy_id)),'recent_2y':stats(recent,simulate(recent,strategy_id)) if len(recent)>220 else None}


def run_backtest(symbol,strategy_id):
    d=load_price_history(symbol,'10y');result=run_backtest_on_frame(d,strategy_id);return {'symbol':symbol,'strategy_id':strategy_id,'engine':'Swing Lab Fast Vector Engine','full_10y':result['full_10y'],'recent_2y':result['recent_2y'],'assumptions':{'commission_pct':0.1,'entry':'signal next-day open','exit':'strategy-specific target/stop','rules':'same conservative live filters as Core 4.2'}}
