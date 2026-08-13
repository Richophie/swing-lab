from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from gap_guard_research import _signal_candidates, simulate_variant
from market_data import load_price_history
from portfolio_correlation_research import simulate_correlation_portfolio
from rsi2_broad_regime_research import MIN_HISTORY_ROWS, research_universe
from structural_stop_research import STRATEGIES

OUT = Path('artifacts/portfolio_correlation_validation.json')
TARGET_SYMBOLS = 80
POLICIES = ('baseline_rr', 'low_corr_priority')


def build_pool():
    requested, source = research_universe(); requested = requested[:TARGET_SYMBOLS]
    eligible=[];errors=[];returns_by_symbol={};trades=[]
    for symbol in requested:
        try:
            d=load_price_history(symbol,'10y').dropna()
            if len(d)<MIN_HISTORY_ROWS:
                errors.append({'symbol':symbol,'error':f'history rows {len(d)} < {MIN_HISTORY_ROWS}'});continue
            returns_by_symbol[symbol]=d['Close'].astype(float).pct_change()
            frame,candidates=_signal_candidates(d,symbol)
            for sid in STRATEGIES:
                ts,_=simulate_variant(d,frame,candidates[sid],'current',symbol=symbol,strategy_id=sid)
                trades.extend(ts)
            eligible.append(symbol)
        except Exception as exc:
            errors.append({'symbol':symbol,'error':str(exc)})
    trades.sort(key=lambda t:(str(t.get('entry_date')),-float(t.get('risk_reward') or 0),str(t.get('symbol') or '')))
    return requested,source,eligible,errors,returns_by_symbol,trades


def bucket(trades,name):
    if name=='oos_last_30pct':return [t for t in trades if t.get('is_oos')]
    if name=='recent_2y':return [t for t in trades if t.get('is_recent')]
    raise ValueError(name)


def compact(result):
    return {k:result.get(k) for k in (
        'return_pct','realized_pnl_krw','stress_drawdown_pct','max_drawdown_pct','accepted_trades',
        'rejected_capacity','accepted_with_corr_ge_0_75','accepted_with_corr_ge_0_60','median_max_corr_when_peer_exists',
    )}


def leave_one_symbol_out(trades,returns_by_symbol,symbols,bucket_name):
    bt=bucket(trades,bucket_name);rows=[]
    active=sorted({str(t.get('symbol')) for t in bt})
    for removed in active:
        filtered=[t for t in bt if str(t.get('symbol'))!=removed]
        base=simulate_correlation_portfolio(filtered,returns_by_symbol,'baseline_rr')
        cand=simulate_correlation_portfolio(filtered,returns_by_symbol,'low_corr_priority')
        rows.append({
            'removed':removed,'baseline_return_pct':base['return_pct'],'candidate_return_pct':cand['return_pct'],
            'delta_pct_points':round(float(cand['return_pct'])-float(base['return_pct']),4),
            'baseline_stress_dd':base['stress_drawdown_pct'],'candidate_stress_dd':cand['stress_drawdown_pct'],
        })
    deltas=[x['delta_pct_points'] for x in rows]
    return {
        'active_symbols':len(active),'runs':len(rows),
        'candidate_beats_baseline_pct':round(sum(x>0 for x in deltas)/len(deltas)*100,2) if deltas else None,
        'delta_min_pct_points':round(min(deltas),4) if deltas else None,
        'delta_median_pct_points':round(float(np.median(deltas)),4) if deltas else None,
        'delta_max_pct_points':round(max(deltas),4) if deltas else None,
        'rows':rows,
    }


def yearly_slices(trades,returns_by_symbol):
    years=sorted({str(t.get('signal_date',''))[:4] for t in trades if str(t.get('signal_date',''))[:4].isdigit()})
    out={}
    for year in years[-6:]:
        ys=[t for t in trades if str(t.get('signal_date','')).startswith(year)]
        if len(ys)<5:continue
        base=simulate_correlation_portfolio(ys,returns_by_symbol,'baseline_rr')
        cand=simulate_correlation_portfolio(ys,returns_by_symbol,'low_corr_priority')
        out[year]={
            'trades':len(ys),'baseline_return_pct':base['return_pct'],'candidate_return_pct':cand['return_pct'],
            'delta_pct_points':round(float(cand['return_pct'])-float(base['return_pct']),4),
        }
    return out


def main():
    requested,source,eligible,errors,returns_by_symbol,trades=build_pool()
    summary={}
    for b in ('oos_last_30pct','recent_2y'):
        bt=bucket(trades,b)
        summary[b]={p:compact(simulate_correlation_portfolio(bt,returns_by_symbol,p)) for p in POLICIES}
        summary[b]['delta_candidate_minus_baseline']={
            'return_pct_points':round(float(summary[b]['low_corr_priority']['return_pct'])-float(summary[b]['baseline_rr']['return_pct']),4),
            'stress_dd_pct_points':round(float(summary[b]['low_corr_priority']['stress_drawdown_pct'])-float(summary[b]['baseline_rr']['stress_drawdown_pct']),4),
            'accepted_trade_delta':int(summary[b]['low_corr_priority']['accepted_trades'])-int(summary[b]['baseline_rr']['accepted_trades']),
        }
    robustness={b:leave_one_symbol_out(trades,returns_by_symbol,eligible,b) for b in ('oos_last_30pct','recent_2y')}
    payload={
        'study':'Fixed-candidate confirmation of low-correlation priority for slot conflicts',
        'status':'CONFIRMATION_RESEARCH_ONLY','selection_source':source,
        'requested_symbol_count':len(requested),'eligible_symbol_count':len(eligible),'errors':errors,
        'candidate_trade_count':len(trades),'policies':POLICIES,'summary':summary,'leave_one_symbol_out':robustness,
        'recent_year_slices':yearly_slices([t for t in trades if t.get('is_oos')],returns_by_symbol),
        'candidate_definition':'Do not reject high-correlation trades. Only when portfolio slots compete, rank the next candidate by lower trailing-60d max correlation to existing positions before ex-ante RR.',
        'confirmation_rule':'Promotion requires candidate to improve both pooled OOS and recent account return without worse stress drawdown, and the advantage should remain positive across a clear majority of leave-one-symbol-out runs. Otherwise retain current RR priority.',
        'scope_note':'Current-name liquid universe; no future data in correlation calculation; historical constituent survivorship bias remains.',
    }
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({
        'eligible_symbol_count':len(eligible),'candidate_trade_count':len(trades),'summary':summary,
        'loo':{b:{k:v[k] for k in ('active_symbols','candidate_beats_baseline_pct','delta_min_pct_points','delta_median_pct_points','delta_max_pct_points')} for b,v in robustness.items()},
        'recent_year_slices':payload['recent_year_slices'],'errors_count':len(errors),
    },ensure_ascii=False,indent=2))
    return payload


if __name__=='__main__':main()
