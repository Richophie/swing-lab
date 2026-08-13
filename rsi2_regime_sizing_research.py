from __future__ import annotations

from collections import defaultdict
from statistics import mean
import json
from pathlib import Path

from backtest_engine import market_buy_fill
from config import (
    BACKTEST_HALF_SPREAD_BPS,
    BACKTEST_INITIAL_CAPITAL_KRW,
    BACKTEST_MAX_POSITION_PCT,
    BACKTEST_MAX_POSITIONS,
    BACKTEST_RISK_PER_TRADE_PCT,
    BACKTEST_SLIPPAGE_BPS,
)
from market_data import load_price_history
from portfolio_backtest import _position_notional
from rsi2_broad_regime_research import MIN_HISTORY_ROWS, research_universe
from rsi2_selector_research import build_live_like_candidates, simulate_variant

OUT=Path('artifacts/rsi2_regime_sizing_research.json')
VARIANTS={
    'neutral_100':{'neutral_multiplier':1.00,'good_first':False},
    'neutral_75':{'neutral_multiplier':0.75,'good_first':False},
    'neutral_50':{'neutral_multiplier':0.50,'good_first':False},
    'neutral_25':{'neutral_multiplier':0.25,'good_first':False},
    'neutral_0_good_only':{'neutral_multiplier':0.00,'good_first':False},
    'neutral_50_good_priority':{'neutral_multiplier':0.50,'good_first':True},
}


def _enrich_trade(trade:dict,d,candidates:dict,split_i:int,recent_i:int)->dict:
    t=dict(trade);i=int(t['signal_i']);info=candidates[i];plan=info['plan'];entry_i=i+1
    raw_entry=float(d['Open'].iloc[entry_i])
    entry_fill=market_buy_fill(raw_entry,BACKTEST_SLIPPAGE_BPS,BACKTEST_HALF_SPREAD_BPS)
    stop=float(plan['stop']);target=float(plan['target']);risk=max(entry_fill-stop,0.0);reward=max(target-entry_fill,0.0)
    t.update({
        'risk_pct':risk/entry_fill if entry_fill>0 else 0.0,
        'risk_reward':reward/risk if risk>0 else 0.0,
        'entry_fill':entry_fill,'target':target,'stop':stop,
        'is_oos':i>=split_i,'is_recent':i>=recent_i,'is_is':i<split_i,
    })
    return t


def build_trade_pool(symbols:list[str])->tuple[list[dict],list[dict],list[str]]:
    trades=[];errors=[];eligible=[]
    for symbol in symbols:
        try:
            d=load_price_history(symbol,'10y').dropna()
            if len(d)<MIN_HISTORY_ROWS:
                errors.append({'symbol':symbol,'error':f'history rows {len(d)} < {MIN_HISTORY_ROWS}'})
                continue
            frame,candidates=build_live_like_candidates(d)
            raw=simulate_variant(d,frame,candidates,'baseline_live_like',symbol=symbol)
            split_i=max(205,int(len(d)*.70));recent_i=max(205,len(d)-504)
            trades.extend(_enrich_trade(t,d,candidates,split_i,recent_i) for t in raw)
            eligible.append(symbol)
        except Exception as exc:
            errors.append({'symbol':symbol,'error':str(exc)})
    trades.sort(key=lambda t:(str(t.get('entry_date')), -float(t.get('risk_reward') or 0), str(t.get('symbol') or '')))
    return trades,errors,eligible


def _stress_equity(cash:float,positions:dict)->float:
    value=float(cash)
    for p in positions.values():
        n=float(p['notional']);risk=max(0.0,float(p['trade'].get('risk_pct') or 0.0));value+=n*max(0.0,1.0-risk)
    return value


def simulate_regime_portfolio(trades:list[dict],neutral_multiplier:float,good_first:bool=False)->dict:
    entries=defaultdict(list);exits=defaultdict(list)
    for seq,trade in enumerate(trades):
        t=dict(trade);t['_seq']=seq
        if t.get('entry_date') and t.get('exit_date'):
            entries[str(t['entry_date'])].append(t);exits[str(t['exit_date'])].append(t)
    dates=sorted(set(entries)|set(exits));cash=float(BACKTEST_INITIAL_CAPITAL_KRW);positions={};accepted=[]
    rejected_capacity=rejected_cash=rejected_regime=0;peak=cash;max_dd=0.0;stress_peak=cash;stress_dd=0.0;max_concurrent=0
    pnl_by_state=defaultdict(float);notional_by_state=defaultdict(list);accepted_by_state=defaultdict(int)

    for day in dates:
        def priority(t):
            good_rank=0 if str(t.get('market_state'))=='좋음' else 1
            return ((good_rank if good_first else 0),-float(t.get('risk_reward') or 0),str(t.get('symbol') or ''),int(t['_seq']))
        for trade in sorted(entries.get(day,[]),key=priority):
            state=str(trade.get('market_state') or '중립')
            mult=1.0 if state=='좋음' else float(neutral_multiplier) if state=='중립' else 0.0
            if mult<=0:
                rejected_regime+=1;continue
            if len(positions)>=BACKTEST_MAX_POSITIONS:
                rejected_capacity+=1;continue
            equity=cash+sum(float(p['notional']) for p in positions.values())
            notional=_position_notional(equity,cash,float(trade.get('risk_pct') or 0),BACKTEST_RISK_PER_TRADE_PCT*mult,BACKTEST_MAX_POSITION_PCT)
            if notional<1:
                rejected_cash+=1;continue
            key=int(trade['_seq']);positions[key]={'trade':trade,'notional':notional};cash-=notional;max_concurrent=max(max_concurrent,len(positions))
            accepted_by_state[state]+=1;notional_by_state[state].append(notional)
            accepted.append({'seq':key,'symbol':trade.get('symbol'),'market_state':state,'entry_date':trade.get('entry_date'),'exit_date':trade.get('exit_date'),'notional_krw':notional,'ret':float(trade.get('ret') or 0),'risk_pct':float(trade.get('risk_pct') or 0),'risk_reward':float(trade.get('risk_reward') or 0)})
        for trade in sorted(exits.get(day,[]),key=lambda t:int(t['_seq'])):
            key=int(trade['_seq']);p=positions.pop(key,None)
            if p is None:continue
            notional=float(p['notional']);pnl=notional*float(trade.get('ret') or 0);cash+=notional+pnl;pnl_by_state[str(trade.get('market_state') or 'unknown')]+=pnl
        equity=cash+sum(float(p['notional']) for p in positions.values());peak=max(peak,equity);max_dd=min(max_dd,equity/peak-1 if peak>0 else 0)
        stress=_stress_equity(cash,positions);stress_peak=max(stress_peak,stress);stress_dd=min(stress_dd,stress/stress_peak-1 if stress_peak>0 else 0)

    if positions:
        for p in positions.values():
            notional=float(p['notional']);trade=p['trade'];pnl=notional*float(trade.get('ret') or 0);cash+=notional+pnl;pnl_by_state[str(trade.get('market_state') or 'unknown')]+=pnl
    ending=cash;returns=[x['ret'] for x in accepted]
    return {
        'initial_capital_krw':round(BACKTEST_INITIAL_CAPITAL_KRW),
        'ending_capital_krw':round(ending),
        'realized_pnl_krw':round(ending-BACKTEST_INITIAL_CAPITAL_KRW),
        'return_pct':round((ending/BACKTEST_INITIAL_CAPITAL_KRW-1)*100,3),
        'max_drawdown_pct':round(max_dd*100,3),'stress_drawdown_pct':round(stress_dd*100,3),
        'accepted_trades':len(accepted),'win_rate_pct':round(sum(r>0 for r in returns)/len(returns)*100,2) if returns else 0.0,
        'max_concurrent_positions':max_concurrent,'rejected_capacity':rejected_capacity,'rejected_cash':rejected_cash,'rejected_regime':rejected_regime,
        'accepted_by_market_state':dict(accepted_by_state),'pnl_by_market_state_krw':{k:round(v) for k,v in pnl_by_state.items()},
        'avg_notional_by_market_state_krw':{k:round(mean(v)) for k,v in notional_by_state.items() if v},
        'settings':{'neutral_risk_multiplier':neutral_multiplier,'good_first_priority':good_first,'max_positions':BACKTEST_MAX_POSITIONS,'base_risk_per_trade_pct':BACKTEST_RISK_PER_TRADE_PCT,'max_position_pct':BACKTEST_MAX_POSITION_PCT},
    }


def _bucket(trades:list[dict],name:str)->list[dict]:
    if name=='all':return trades
    if name=='is_first_70pct':return [t for t in trades if t.get('is_is')]
    if name=='oos_last_30pct':return [t for t in trades if t.get('is_oos')]
    if name=='recent_2y':return [t for t in trades if t.get('is_recent')]
    raise ValueError(name)


def run_research()->dict:
    requested,source=research_universe();trades,errors,eligible=build_trade_pool(requested)
    summary={}
    for variant,settings in VARIANTS.items():
        summary[variant]={bucket:simulate_regime_portfolio(_bucket(trades,bucket),**settings) for bucket in ('all','is_first_70pct','oos_last_30pct','recent_2y')}
    payload={
        'study':'RSI2 market-regime position sizing in finite 3M KRW / max-3-position account',
        'status':'RESEARCH_ONLY','selection_source':source,'requested_symbols':requested,'eligible_symbols':eligible,'errors':errors,
        'candidate_trade_count':len(trades),'variants':VARIANTS,'variant_summary':summary,
        'account_model':{'initial_capital_krw':BACKTEST_INITIAL_CAPITAL_KRW,'max_positions':BACKTEST_MAX_POSITIONS,'base_risk_per_trade_pct':BACKTEST_RISK_PER_TRADE_PCT,'max_position_pct':BACKTEST_MAX_POSITION_PCT,'entries_before_same_day_exits':True},
        'interpretation_rule':'Prefer a multiplier only if OOS and recent account return/stress drawdown improve together without a pathological loss of trade count or reliance on good-first lookalike selection. This is still a current-name universe study.',
    }
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'eligible_symbol_count':len(eligible),'candidate_trade_count':len(trades),'variant_summary':summary,'errors_count':len(errors)},ensure_ascii=False,indent=2));return payload


if __name__=='__main__':run_research()
