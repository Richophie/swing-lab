from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_engine import (
    _historical_market_state,
    exit_fill_for_bar,
    market_buy_fill,
    market_sell_fill,
    net_trade_return,
)
from config import (
    BACKTEST_COMMISSION_PCT,
    BACKTEST_HALF_SPREAD_BPS,
    BACKTEST_SLIPPAGE_BPS,
    S_THRESHOLD,
)
from execution_quality import plan_execution_quality
from market_data import indicators, load_price_history, wilder_rsi
from net_rr_research import pooled_stats
from portfolio_backtest import simulate_portfolio
from rsi2_broad_regime_research import MIN_HISTORY_ROWS, research_universe
from rsi2_selector_research import _historical_flow_frame
from scanner import _flow_quality
from strategy_rules import ENTRY_GAP_ATR, ENTRY_GAP_PCT, canonical_signal_frame

OUT=Path('artifacts/structural_stop_research.json')
STRATEGIES=('confirmed_pullback','rsi2_trend_reversion','momentum_pullback')
STRATEGY_NAMES={
    'confirmed_pullback':'확인형 눌림반등',
    'rsi2_trend_reversion':'RSI2 추세내 과매도',
    'momentum_pullback':'모멘텀 눌림 지속',
}
VARIANTS={
    'force_1_50':{'mode':'force','min_atr':1.50},
    'force_1_25':{'mode':'force','min_atr':1.25},
    'structural_raw':{'mode':'raw','min_atr':None},
    'structural_reject_lt_1_25':{'mode':'reject','min_atr':1.25},
    'structural_reject_lt_1_50':{'mode':'reject','min_atr':1.50},
}
TARGET_SYMBOLS=60


def _quality(points:pd.Series,active:pd.Series)->pd.Series:
    q=55+40*np.clip(points.astype(float)/10.0,0,1)
    q=pd.Series(q,index=points.index).round(1)
    q.loc[~active.fillna(False)]=np.minimum(q.loc[~active.fillna(False)],69.0)
    return q


def historical_features(d:pd.DataFrame,state:pd.Series,frame:pd.DataFrame)->dict:
    ind=indicators(d);c=d['Close'].astype(float);o=d['Open'].astype(float);h=d['High'].astype(float);l=d['Low'].astype(float);v=d['Volume'].astype(float)
    s20=ind['sma20'];s50=ind['sma50'];s120=ind['sma120'];s200=ind['sma200'];rsi=ind['rsi'];bb=ind['bb_pos'];atr=ind['atr14'];mh=ind['macd_hist'];vol20=ind['vol20'].replace(0,np.nan)
    d120=c/s120-1;atrp=atr/c;rsi2=wilder_rsi(c,2);ret20=c/c.shift(20)-1;ret5=c/c.shift(5)-1
    price_reversal=(c>c.shift(1))|(c>o);rsi_delta3=rsi-rsi.shift(3);macd_up=mh>mh.shift(1);slope120=s120/s120.shift(20)-1;trend_floor=(c>=s200*.97)&(slope120>=-.01);trend_ok=(c>s200)&(s50>=s120)
    revvol=(v/vol20).where(price_reversal,0.0).fillna(0.0)
    confirm=(rsi_delta3>=0).fillna(False).astype(int)+macd_up.fillna(False).astype(int)+price_reversal.fillna(False).astype(int)+trend_floor.fillna(False).astype(int)

    pp=(
        np.select([(rsi>=30)&(rsi<=42),rsi<=45],[2,1],default=0)
        +np.select([d120.abs()<=.02,d120.abs()<=.035],[2,1],default=0)
        +np.minimum(confirm,4)
        +(bb<=.30).fillna(False).astype(int)
        +(atrp<=.035).fillna(False).astype(int)
    )
    pp=pd.Series(pp,index=d.index)-np.where(revvol<1.0,2,0)
    confirmed_score=_quality(pp,frame['confirmed_pullback'])

    rp=(
        np.select([rsi2<2,rsi2<3],[3,2],default=0)
        +np.select([rsi<42,rsi<=50],[2,1],default=0)
        +np.select([bb<=.25,bb<=.45],[2,1],default=0)
        +(d120.abs()<=.06).fillna(False).astype(int)
        +trend_ok.fillna(False).astype(int)
        +(atrp<=.04).fillna(False).astype(int)
    )
    rsi2_score=_quality(pd.Series(rp,index=d.index),frame['rsi2_trend_reversion'])

    mp=(
        2*trend_ok.fillna(False).astype(int)
        +np.select([(ret20>=.08)&(ret20<=.16),(ret20>=.05)&(ret20<=.20)],[2,1],default=0)
        +np.select([(ret5>=-.04)&(ret5<=-.01),(ret5>=-.05)&(ret5<=-.005)],[2,1],default=0)
        +2*macd_up.fillna(False).astype(int)
        +((rsi>=45)&(rsi<=58)).fillna(False).astype(int)
        +(d120<=.12).fillna(False).astype(int)
    )
    momentum_score=_quality(pd.Series(mp,index=d.index),frame['momentum_pullback'])

    # Historical first-20DMA overlay, equivalent in spirit to scanner._first_20d_pullback_overlay.
    ma5=c.rolling(5).mean();ma20=c.rolling(20).mean();ma50=c.rolling(50).mean();ma200=c.rolling(200).mean();high52=h.rolling(252).max()
    aligned=(ma5>ma20)&(ma20>ma50)&(ma50>ma200)
    recent_high=(h>=high52*.997).rolling(30,min_periods=1).max().fillna(0).astype(bool)
    stayed=((l.shift(1)>ma20.shift(1)).rolling(20,min_periods=20).sum()==20)
    touched=(l<=ma20*1.003)&(c>=ma20*.985)
    overlay=(aligned&recent_high&stayed&touched).fillna(False)

    return {
        'scores':{
            'confirmed_pullback':confirmed_score,
            'rsi2_trend_reversion':rsi2_score,
            'momentum_pullback':momentum_score,
        },
        'flows':_historical_flow_frame(d,ind),
        'overlay':overlay,
    }


def plan_from_row(row:pd.Series,strategy_id:str,variant:str)->dict:
    close=float(row['close']);atr=max(float(row['atr']),close*.005);recent_low=float(row['recent_low']);recent_high=float(row['recent_high']);s20=float(row['s20']);s120=float(row['s120'])
    if strategy_id=='confirmed_pullback':
        anchor=s120;buy_low=anchor-.18*atr;buy_high=anchor+.22*atr;raw_stop=min(recent_low,anchor-.95*atr);target=max(recent_high,anchor+1.8*atr);days=(2,8)
    elif strategy_id=='rsi2_trend_reversion':
        anchor=close;buy_low=anchor-.12*atr;buy_high=anchor+.12*atr;raw_stop=min(recent_low,anchor-1.15*atr);target=max(anchor+1.3*atr,s20 if s20>anchor else anchor+1.3*atr);days=(1,5)
    elif strategy_id=='momentum_pullback':
        anchor=s20 if np.isfinite(s20) else close;buy_low=anchor-.20*atr;buy_high=anchor+.18*atr;raw_stop=min(recent_low,anchor-1.05*atr);target=max(recent_high,anchor+2.0*atr);days=(3,10)
    else:raise ValueError(strategy_id)
    entry=(buy_low+buy_high)/2.0
    if target<=entry:target=entry+1.5*atr
    raw_mult=(entry-raw_stop)/atr
    cfg=VARIANTS[variant];rejected=False
    if cfg['mode']=='force':stop=min(raw_stop,entry-float(cfg['min_atr'])*atr)
    elif cfg['mode']=='raw':stop=raw_stop
    else:
        rejected=raw_mult<float(cfg['min_atr']);stop=raw_stop
    return {
        'buy_low':buy_low,'buy_high':buy_high,'entry':entry,'target':target,'stop':stop,'raw_stop':raw_stop,'atr':atr,'days':days,
        'raw_stop_atr_multiple':raw_mult,'stop_atr_multiple':(entry-stop)/atr,'structural_rejected':rejected,
    }


def selection_pass(strategy_score:float,flow:dict,plan:dict,market_state:str,overlay:bool,close:float,strategy_id:str)->dict:
    if plan.get('structural_rejected'):return {'pass':False,'reason':'structural_min_reject'}
    try:q=plan_execution_quality(plan);rr=float(q['gross_risk_reward']);net_rr=float(q['net_risk_reward'])
    except Exception:return {'pass':False,'reason':'rr_error'}
    fq=_flow_quality(flow);entry_gap=max(ENTRY_GAP_ATR*float(plan['atr']),ENTRY_GAP_PCT*float(close));entry_ok=not(close<float(plan['buy_low'])-entry_gap or close>float(plan['buy_high'])+entry_gap)
    elite=float(strategy_score)*.68+float(fq)*.22+min(100,rr/3*100)*.10
    if overlay and strategy_id in {'confirmed_pullback','momentum_pullback'}:elite+=6
    if market_state=='중립':elite-=2
    if market_state=='조심':elite-=8
    if not entry_ok:elite-=18
    elite=max(0,min(99,elite))
    ok=rr>=1.20 and fq>=42 and market_state!='조심' and entry_ok and elite>=72
    return {'pass':bool(ok),'gross_rr':rr,'net_rr':net_rr,'flow_score':fq,'elite_score':elite,'entry_ok':entry_ok}


def simulate_symbol_variant(d:pd.DataFrame,strategy_id:str,variant:str,symbol:str,features:dict,frame:pd.DataFrame)->tuple[list[dict],dict]:
    commission=BACKTEST_COMMISSION_PCT/100.0;score_s=features['scores'][strategy_id];flows=features['flows'];overlay_s=features['overlay'];state=frame['market_state'];trades=[];diag=defaultdict(int);raw_mults=[];i=205;n=len(d)
    while i<n-2:
        if not bool(frame[strategy_id].iloc[i]) or float(score_s.iloc[i])<S_THRESHOLD:
            i+=1;continue
        diag['strict_s_candidates']+=1
        plan=plan_from_row(frame.iloc[i],strategy_id,variant);raw_mults.append(float(plan['raw_stop_atr_multiple']))
        flow_row=flows.iloc[i];flow={k:(None if pd.isna(v) else float(v)) for k,v in flow_row.items()}
        sel=selection_pass(float(score_s.iloc[i]),flow,plan,str(state.iloc[i]),bool(overlay_s.iloc[i]),float(frame['close'].iloc[i]),strategy_id)
        if not sel.get('pass'):
            diag['selection_reject']+=1
            if sel.get('reason')=='structural_min_reject':diag['structural_min_reject']+=1
            i+=1;continue
        diag['elite_candidates']+=1
        entry_i=i+1;raw_entry=float(d['Open'].iloc[entry_i]);gap=max(ENTRY_GAP_ATR*plan['atr'],ENTRY_GAP_PCT*float(frame['close'].iloc[i]))
        if raw_entry<plan['buy_low']-gap or raw_entry>plan['buy_high']+gap:
            diag['next_open_gap_reject']+=1;i+=1;continue
        entry_fill=market_buy_fill(raw_entry,BACKTEST_SLIPPAGE_BPS,BACKTEST_HALF_SPREAD_BPS);target=float(plan['target']);stop=float(plan['stop'])
        if not stop<entry_fill<target:
            diag['invalid_fill_reject']+=1;i+=1;continue
        exit_i=min(entry_i+int(plan['days'][1]),n-1);raw_exit=float(d['Close'].iloc[exit_i]);exit_fill=market_sell_fill(raw_exit,BACKTEST_SLIPPAGE_BPS,BACKTEST_HALF_SPREAD_BPS);reason='기간종료'
        for j in range(entry_i,exit_i+1):
            bar=d.iloc[j];outcome=exit_fill_for_bar(bar['Open'],bar['High'],bar['Low'],target,stop,BACKTEST_SLIPPAGE_BPS,BACKTEST_HALF_SPREAD_BPS)
            if outcome is not None:exit_fill,reason,raw_exit=outcome;exit_i=j;break
        ret=net_trade_return(entry_fill,exit_fill,commission);risk=entry_fill-stop;reward=target-entry_fill
        split_i=max(205,int(n*.70));recent_i=max(205,n-504)
        trades.append({
            'symbol':symbol,'strategy_id':strategy_id,'variant':variant,'signal_i':i,'signal_date':d.index[i].strftime('%Y-%m-%d'),'entry_date':d.index[entry_i].strftime('%Y-%m-%d'),'exit_date':d.index[exit_i].strftime('%Y-%m-%d'),
            'ret':float(ret),'reason':reason,'risk_pct':risk/entry_fill if entry_fill>0 else 0.0,'risk_reward':reward/risk if risk>0 else 0.0,
            'raw_stop_atr_multiple':float(plan['raw_stop_atr_multiple']),'final_stop_atr_multiple':float(plan['stop_atr_multiple']),'gross_risk_reward_signal':float(sel['gross_rr']),'elite_score':float(sel['elite_score']),'market_state':str(state.iloc[i]),
            'is_is':i<split_i,'is_oos':i>=split_i,'is_recent':i>=recent_i,
        });i=exit_i+1
    diag['avg_raw_stop_atr_multiple']=round(float(np.mean(raw_mults)),4) if raw_mults else None;diag['raw_lt_1_25_pct']=round(sum(x<1.25 for x in raw_mults)/len(raw_mults)*100,2) if raw_mults else 0;diag['raw_lt_1_50_pct']=round(sum(x<1.5 for x in raw_mults)/len(raw_mults)*100,2) if raw_mults else 0
    return trades,dict(diag)


def bucket(trades:list[dict],name:str)->list[dict]:
    if name=='all':return trades
    if name=='is_first_70pct':return [t for t in trades if t['is_is']]
    if name=='oos_last_30pct':return [t for t in trades if t['is_oos']]
    if name=='recent_2y':return [t for t in trades if t['is_recent']]
    raise ValueError(name)


def run_research()->dict:
    requested,source=research_universe();requested=requested[:TARGET_SYMBOLS];eligible=[];errors=[];variant_trades={v:[] for v in VARIANTS};diagnostics={v:defaultdict(lambda:defaultdict(float)) for v in VARIANTS}
    per_symbol=[]
    for symbol in requested:
        try:
            d=load_price_history(symbol,'10y').dropna()
            if len(d)<MIN_HISTORY_ROWS:errors.append({'symbol':symbol,'error':f'history rows {len(d)} < {MIN_HISTORY_ROWS}'});continue
            state=_historical_market_state(d.index);frame=canonical_signal_frame(d,state);feat=historical_features(d,state,frame);eligible.append(symbol)
        except Exception as exc:errors.append({'symbol':symbol,'error':str(exc)});continue
        row={'symbol':symbol,'variants':{}}
        for variant in VARIANTS:
            row['variants'][variant]={}
            for sid in STRATEGIES:
                try:
                    trades,diag=simulate_symbol_variant(d,sid,variant,symbol,feat,frame);variant_trades[variant].extend(trades);row['variants'][variant][sid]={'trades':len(trades),'diagnostics':diag}
                except Exception as exc:row['variants'][variant][sid]={'error':str(exc)}
        per_symbol.append(row)
    summary={}
    for variant,trades in variant_trades.items():
        summary[variant]={}
        for b in ('all','is_first_70pct','oos_last_30pct','recent_2y'):
            bt=bucket(trades,b);stats=pooled_stats(bt);portfolio=simulate_portfolio(bt);stats['portfolio']={k:portfolio.get(k) for k in ('return_pct','realized_pnl_krw','max_drawdown_pct','stress_drawdown_pct','accepted_trades','win_rate_pct','avg_position_krw','max_concurrent_positions','rejected_capacity','rejected_cash')};stats['by_strategy']={sid:pooled_stats([t for t in bt if t['strategy_id']==sid]) for sid in STRATEGIES};summary[variant][b]=stats
        all_raw=[t['raw_stop_atr_multiple'] for t in trades];summary[variant]['trade_stop_distribution']={'trades':len(trades),'avg_raw_stop_atr_multiple':round(float(np.mean(all_raw)),4) if all_raw else None,'raw_lt_1_25_pct':round(sum(x<1.25 for x in all_raw)/len(all_raw)*100,2) if all_raw else 0,'raw_lt_1_50_pct':round(sum(x<1.5 for x in all_raw)/len(all_raw)*100,2) if all_raw else 0}
    payload={
        'study':'Forced minimum ATR stop versus structural stop policies','status':'RESEARCH_ONLY','selection_source':source,'requested_symbol_count':len(requested),'eligible_symbol_count':len(eligible),'eligible_symbols':eligible,'errors':errors,
        'strategies':STRATEGIES,'strategy_names':STRATEGY_NAMES,'variants':VARIANTS,'variant_summary':summary,'symbol_results':per_symbol,
        'live_like_scope':'canonical strict + strategy S score + historical flow + precise gross RR >=1.20 + market + entry viability + elite score + first-20DMA overlay + next-open execution',
        'portfolio_scope':'3M KRW, max 3 positions, 1% planned risk, 40% max position via existing portfolio simulator',
        'decision_rule':'Do not prefer a tighter stop merely because RR rises. Candidate must improve OOS/recent portfolio return and/or stress drawdown with adequate trade count and strategy-level consistency.',
    }
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'eligible_symbol_count':len(eligible),'variant_summary':summary,'errors_count':len(errors)},ensure_ascii=False,indent=2));return payload


if __name__=='__main__':run_research()
