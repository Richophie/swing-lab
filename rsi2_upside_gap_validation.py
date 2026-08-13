from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

import gap_guard_research as gap
from market_data import load_price_history
from net_rr_research import pooled_stats
from portfolio_backtest import simulate_portfolio
from rsi2_broad_regime_research import MIN_HISTORY_ROWS, research_universe

OUT=Path('artifacts/rsi2_upside_gap_validation.json')
TARGET_SYMBOLS=80
POLICIES={
    'baseline_current':{
        'confirmed_pullback':'current',
        'rsi2_trend_reversion':'current',
        'momentum_pullback':'current',
    },
    'rsi2_up_0_50':{
        'confirmed_pullback':'current',
        'rsi2_trend_reversion':'down_current_up_0_50',
        'momentum_pullback':'current',
    },
}
gap.VARIANTS['down_current_up_0_50']={'down':'current','up':0.50}


def bucket(trades,name):
    if name=='all':return trades
    if name=='is_first_70pct':return [t for t in trades if t['is_is']]
    if name=='oos_last_30pct':return [t for t in trades if t['is_oos']]
    if name=='recent_2y':return [t for t in trades if t['is_recent']]
    raise ValueError(name)


def portfolio_compact(trades):
    p=simulate_portfolio(trades)
    return {k:p.get(k) for k in (
        'return_pct','realized_pnl_krw','max_drawdown_pct','stress_drawdown_pct',
        'accepted_trades','win_rate_pct','avg_position_krw','max_concurrent_positions',
        'rejected_capacity','rejected_cash',
    )}


def leave_one_symbol_out(trades):
    symbols=sorted({t.get('symbol') for t in trades if t.get('symbol')})
    rows=[]
    for symbol in symbols:
        p=portfolio_compact([t for t in trades if t.get('symbol')!=symbol])
        rows.append({'removed':symbol,'return_pct':p['return_pct'],'stress_drawdown_pct':p['stress_drawdown_pct'],'accepted_trades':p['accepted_trades']})
    returns=[x['return_pct'] for x in rows if x['return_pct'] is not None]
    stress=[x['stress_drawdown_pct'] for x in rows if x['stress_drawdown_pct'] is not None]
    return {
        'symbols_tested':len(rows),
        'return_pct_min':min(returns) if returns else None,
        'return_pct_max':max(returns) if returns else None,
        'stress_drawdown_pct_min':min(stress) if stress else None,
        'stress_drawdown_pct_max':max(stress) if stress else None,
        'rows':rows,
    }


def symbol_rsi2_robustness(current,candidate,bucket_name):
    by_current=defaultdict(list);by_candidate=defaultdict(list)
    for t in bucket(current,bucket_name):
        if t['strategy_id']=='rsi2_trend_reversion':by_current[t['symbol']].append(t)
    for t in bucket(candidate,bucket_name):
        if t['strategy_id']=='rsi2_trend_reversion':by_candidate[t['symbol']].append(t)
    symbols=sorted(set(by_current)|set(by_candidate));rows=[]
    improved=positive_candidate=0;comparable=0
    for symbol in symbols:
        a=pooled_stats(by_current[symbol]);b=pooled_stats(by_candidate[symbol])
        row={'symbol':symbol,'current':a,'candidate':b}
        if a['trades'] and b['trades']:
            comparable+=1
            if b['avg_return_pct']>a['avg_return_pct']:improved+=1
        if b['trades'] and b['avg_return_pct']>0:positive_candidate+=1
        rows.append(row)
    return {
        'active_symbols':len(symbols),
        'comparable_symbols':comparable,
        'candidate_improved_avg_symbol_pct':round(improved/comparable*100,2) if comparable else 0.0,
        'candidate_positive_avg_symbol_pct':round(positive_candidate/len(symbols)*100,2) if symbols else 0.0,
        'rows':rows,
    }


def run_validation():
    requested,source=research_universe();requested=requested[:TARGET_SYMBOLS]
    policy_trades={p:[] for p in POLICIES};eligible=[];errors=[]
    for symbol in requested:
        try:
            d=load_price_history(symbol,'10y').dropna()
            if len(d)<MIN_HISTORY_ROWS:
                errors.append({'symbol':symbol,'error':f'history rows {len(d)} < {MIN_HISTORY_ROWS}'});continue
            frame,candidates=gap._signal_candidates(d,symbol);eligible.append(symbol)
        except Exception as exc:
            errors.append({'symbol':symbol,'error':str(exc)});continue
        for policy,mapping in POLICIES.items():
            for sid,variant in mapping.items():
                try:
                    trades,_=gap.simulate_variant(d,frame,candidates[sid],variant,symbol=symbol,strategy_id=sid)
                    policy_trades[policy].extend(trades)
                except Exception as exc:
                    errors.append({'symbol':symbol,'policy':policy,'strategy':sid,'error':str(exc)})
    summary={}
    for policy,trades in policy_trades.items():
        summary[policy]={}
        for b in ('all','is_first_70pct','oos_last_30pct','recent_2y'):
            bt=bucket(trades,b);rsi2=[t for t in bt if t['strategy_id']=='rsi2_trend_reversion']
            summary[policy][b]={'all':pooled_stats(bt),'rsi2':pooled_stats(rsi2),'portfolio':portfolio_compact(bt)}
        summary[policy]['oos_leave_one_symbol_out']=leave_one_symbol_out(bucket(trades,'oos_last_30pct'))
        summary[policy]['recent_leave_one_symbol_out']=leave_one_symbol_out(bucket(trades,'recent_2y'))
    robustness={
        'oos_last_30pct':symbol_rsi2_robustness(policy_trades['baseline_current'],policy_trades['rsi2_up_0_50'],'oos_last_30pct'),
        'recent_2y':symbol_rsi2_robustness(policy_trades['baseline_current'],policy_trades['rsi2_up_0_50'],'recent_2y'),
    }
    payload={
        'study':'Confirmation validation of RSI2 upside gap 0.50ATR','status':'RESEARCH_ONLY_CANDIDATE_VALIDATION',
        'selection_source':source,'requested_symbol_count':len(requested),'eligible_symbol_count':len(eligible),'eligible_symbols':eligible,'errors':errors,
        'policies':POLICIES,'variant_summary':summary,'rsi2_symbol_robustness':robustness,
        'decision_rule':'Promote only if candidate preserves/improves OOS and recent whole-account return/risk, leaves adequate RSI2 coverage, and is not dependent on one symbol. This still does not eliminate current-name survivorship bias.',
    }
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'eligible_symbol_count':len(eligible),'variant_summary':summary,'rsi2_symbol_robustness':robustness,'errors_count':len(errors)},ensure_ascii=False,indent=2));return payload


if __name__=='__main__':run_validation()
