from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

from market_data import load_price_history, load_us_universe, prefilter_symbols
from net_rr_research import pooled_stats
from rsi2_selector_research import build_live_like_candidates, simulate_variant

OUT = Path('artifacts/rsi2_broad_regime_research.json')
TARGET_SYMBOLS = 80
MIN_HISTORY_ROWS = 1000
VARIANTS = ('baseline_live_like', 'market_good_only')

# Research fallback only. The primary universe is the objective current screener.
FALLBACK = [
    'AAPL','MSFT','NVDA','AMZN','META','GOOGL','AVGO','TSLA','BRK-B','JPM','V','MA','WMT','LLY','ORCL','NFLX','COST','HD','PG','JNJ',
    'ABBV','BAC','KO','PLTR','CRM','AMD','CSCO','CVX','XOM','IBM','GE','CAT','RTX','LMT','UNH','MRK','PEP','MCD','TMO','ACN',
    'QCOM','TXN','AMAT','MU','INTU','NOW','ADBE','BKNG','UBER','SPGI','GS','MS','AXP','BLK','SCHW','C','WFC','PGR','CB','COP',
    'SLB','EOG','NEE','DUK','SO','PLD','AMT','EQIX','LIN','SHW','DE','HON','UNP','UPS','LOW','NKE','SBUX','DIS','CMCSA','TGT',
]


def research_universe() -> tuple[list[str], str]:
    try:
        universe = load_us_universe()
        symbols = prefilter_symbols(universe, TARGET_SYMBOLS)
        if len(symbols) >= 40:
            return symbols[:TARGET_SYMBOLS], 'objective_current_prefilter'
    except Exception:
        pass
    return FALLBACK[:TARGET_SYMBOLS], 'static_liquid_fallback'


def _bucket(trades: list[dict], split_i: int, recent_i: int) -> dict[str, list[dict]]:
    return {
        'all': trades,
        'is_first_70pct': [t for t in trades if int(t['signal_i']) < split_i],
        'oos_last_30pct': [t for t in trades if int(t['signal_i']) >= split_i],
        'recent_2y': [t for t in trades if int(t['signal_i']) >= recent_i],
    }


def _symbol_robustness(symbol_trades: dict[str, list[dict]]) -> dict:
    active = {s:t for s,t in symbol_trades.items() if t}
    if not active:
        return {
            'active_symbols':0,'positive_avg_symbol_pct':0.0,'top5_trade_share_pct':0.0,
            'leave_one_symbol_out_avg_return_pct_min':None,'leave_one_symbol_out_avg_return_pct_max':None,
            'leave_one_symbol_out_pf_min':None,'leave_one_symbol_out_pf_max':None,
        }
    avg_by_symbol = {s:pooled_stats(t)['avg_return_pct'] for s,t in active.items()}
    total = sum(len(t) for t in active.values())
    top5 = sum(sorted((len(t) for t in active.values()), reverse=True)[:5])
    loo = []
    symbols = list(active)
    for removed in symbols:
        pooled = [trade for s,trades in active.items() if s != removed for trade in trades]
        if pooled:
            loo.append(pooled_stats(pooled))
    pfs = [x['profit_factor'] for x in loo if x.get('profit_factor') is not None]
    avgs = [x['avg_return_pct'] for x in loo]
    return {
        'active_symbols':len(active),
        'positive_avg_symbol_pct':round(sum(v>0 for v in avg_by_symbol.values())/len(avg_by_symbol)*100,2),
        'negative_avg_symbol_pct':round(sum(v<0 for v in avg_by_symbol.values())/len(avg_by_symbol)*100,2),
        'top5_trade_share_pct':round(top5/total*100,2) if total else 0.0,
        'leave_one_symbol_out_avg_return_pct_min':round(min(avgs),4) if avgs else None,
        'leave_one_symbol_out_avg_return_pct_max':round(max(avgs),4) if avgs else None,
        'leave_one_symbol_out_pf_min':round(min(pfs),4) if pfs else None,
        'leave_one_symbol_out_pf_max':round(max(pfs),4) if pfs else None,
        'per_symbol_avg_return_pct':dict(sorted(avg_by_symbol.items())),
    }


def run_research() -> dict:
    requested, source = research_universe()
    pooled = {v:defaultdict(list) for v in VARIANTS}
    by_symbol = {v:{'all':defaultdict(list),'oos_last_30pct':defaultdict(list),'recent_2y':defaultdict(list)} for v in VARIANTS}
    symbol_rows=[];errors=[];eligible_symbols=[]

    for symbol in requested:
        try:
            d=load_price_history(symbol,'10y').dropna()
            if len(d)<MIN_HISTORY_ROWS:
                errors.append({'symbol':symbol,'error':f'history rows {len(d)} < {MIN_HISTORY_ROWS}'})
                continue
            frame,candidates=build_live_like_candidates(d)
        except Exception as exc:
            errors.append({'symbol':symbol,'error':str(exc)})
            continue
        eligible_symbols.append(symbol)
        split_i=max(205,int(len(d)*.70));recent_i=max(205,len(d)-504)
        row={'symbol':symbol,'history_rows':len(d),'live_like_candidates':len(candidates),'variants':{}}
        for variant in VARIANTS:
            try:
                trades=simulate_variant(d,frame,candidates,variant,symbol=symbol)
                grouped=_bucket(trades,split_i,recent_i)
                row['variants'][variant]={name:pooled_stats(items) for name,items in grouped.items()}
                for name,items in grouped.items():
                    pooled[variant][name].extend(items)
                    if name in by_symbol[variant]: by_symbol[variant][name][symbol].extend(items)
            except Exception as exc:
                row['variants'][variant]={'error':str(exc)}
        symbol_rows.append(row)

    baseline_counts={k:max(1,len(v)) for k,v in pooled['baseline_live_like'].items()}
    summary={}
    for variant in VARIANTS:
        summary[variant]={}
        for bucket in ('all','is_first_70pct','oos_last_30pct','recent_2y'):
            trades=pooled[variant][bucket]
            stats=pooled_stats(trades)
            stats['coverage_vs_baseline_pct']=round(len(trades)/baseline_counts[bucket]*100,2)
            if bucket in by_symbol[variant]:
                stats['symbol_robustness']=_symbol_robustness(by_symbol[variant][bucket])
            summary[variant][bucket]=stats

    payload={
        'study':'Broad current-liquid-universe validation of RSI2 market_good_only candidate',
        'status':'RESEARCH_ONLY',
        'selection_source':source,
        'requested_symbol_count':len(requested),
        'eligible_symbol_count':len(eligible_symbols),
        'requested_symbols':requested,
        'eligible_symbols':eligible_symbols,
        'variants':VARIANTS,
        'variant_summary':summary,
        'symbol_results':symbol_rows,
        'errors':errors,
        'decision_rule':'Candidate should improve OOS and recent expectancy/PF with meaningful coverage and without dependence on a handful of symbols. This current-name universe still does not remove survivorship bias.',
        'scope_note':'Broad robustness check, not final historical-universe proof. No live promotion from this artifact alone.',
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({
        'selection_source':source,'eligible_symbol_count':len(eligible_symbols),
        'variant_summary':summary,'errors_count':len(errors),
    },ensure_ascii=False,indent=2))
    return payload


if __name__=='__main__':run_research()
