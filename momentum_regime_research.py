from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

import numpy as np
import pandas as pd

import gap_guard_research as gap
from market_data import load_price_history
from net_rr_research import pooled_stats
from portfolio_backtest import simulate_portfolio
from rsi2_broad_regime_research import MIN_HISTORY_ROWS, research_universe

OUT=Path('artifacts/momentum_regime_research.json')
TARGET_SYMBOLS=80
STRATEGY_ID='momentum_pullback'


def spy_regime_features(index:pd.Index)->pd.DataFrame:
    spy=load_price_history('SPY','10y').copy();c=spy['Close'].astype(float)
    ret=c.pct_change();rv20=ret.rolling(20).std()*np.sqrt(252)
    # Trailing 252d percentile uses only information available through each date.
    vol_pct=rv20.rolling(252,min_periods=100).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1],raw=False)
    high20=c.rolling(20).max();dd20=c/high20-1;ret5=c/c.shift(5)-1;ret20=c/c.shift(20)-1
    out=pd.DataFrame({'spy_ret5':ret5,'spy_ret20':ret20,'spy_dd20':dd20,'spy_rv20':rv20,'spy_vol_pct_252':vol_pct},index=spy.index)
    return out.reindex(index).ffill()


def classify_trade(trade:dict,features:pd.DataFrame)->dict:
    date=pd.Timestamp(trade['signal_date'])
    if date not in features.index:
        return {}
    r=features.loc[date]
    vol=float(r['spy_vol_pct_252']) if pd.notna(r['spy_vol_pct_252']) else None
    dd=float(r['spy_dd20']) if pd.notna(r['spy_dd20']) else None
    r5=float(r['spy_ret5']) if pd.notna(r['spy_ret5']) else None
    r20=float(r['spy_ret20']) if pd.notna(r['spy_ret20']) else None
    if vol is None:vol_bucket='vol_unknown'
    elif vol>=.80:vol_bucket='vol_high_80p'
    elif vol<=.20:vol_bucket='vol_low_20p'
    else:vol_bucket='vol_mid'
    if dd is None:dd_bucket='dd_unknown'
    elif dd<=-.05:dd_bucket='dd_deep_5pct'
    elif dd<=-.02:dd_bucket='dd_mid_2_5pct'
    else:dd_bucket='dd_shallow_lt2pct'
    if r5 is None:r5_bucket='ret5_unknown'
    elif r5>=.03:r5_bucket='ret5_rebound_ge3pct'
    elif r5<=-.03:r5_bucket='ret5_drop_le-3pct'
    elif r5>=0:r5_bucket='ret5_up_0_3pct'
    else:r5_bucket='ret5_down_0_3pct'
    rebound=bool(dd is not None and dd<=-.05 and r5 is not None and r5>=.03)
    return {'vol_bucket':vol_bucket,'dd_bucket':dd_bucket,'ret5_bucket':r5_bucket,'deep_drawdown_rebound':rebound,'spy_vol_pct_252':vol,'spy_dd20':dd,'spy_ret5':r5,'spy_ret20':r20}


def bucket(trades,name):
    if name=='all':return trades
    if name=='is_first_70pct':return [t for t in trades if t['is_is']]
    if name=='oos_last_30pct':return [t for t in trades if t['is_oos']]
    if name=='recent_2y':return [t for t in trades if t['is_recent']]
    raise ValueError(name)


def grouped_stats(trades,key):
    groups=defaultdict(list)
    for t in trades:groups[str(t.get(key,'unknown'))].append(t)
    return {k:pooled_stats(v) for k,v in sorted(groups.items())}


def candidate_portfolio(trades, predicate):
    chosen=[t for t in trades if predicate(t)]
    p=simulate_portfolio(chosen)
    return {'trade_stats':pooled_stats(chosen),'portfolio':{k:p.get(k) for k in ('return_pct','realized_pnl_krw','max_drawdown_pct','stress_drawdown_pct','accepted_trades','win_rate_pct','rejected_capacity','rejected_cash')}}


def run_research():
    requested,source=research_universe();requested=requested[:TARGET_SYMBOLS];all_trades=[];eligible=[];errors=[]
    for symbol in requested:
        try:
            d=load_price_history(symbol,'10y').dropna()
            if len(d)<MIN_HISTORY_ROWS:errors.append({'symbol':symbol,'error':f'history rows {len(d)} < {MIN_HISTORY_ROWS}'});continue
            frame,candidates=gap._signal_candidates(d,symbol)
            trades,_=gap.simulate_variant(d,frame,candidates[STRATEGY_ID],'current',symbol=symbol,strategy_id=STRATEGY_ID)
            all_trades.extend(trades);eligible.append(symbol)
        except Exception as exc:errors.append({'symbol':symbol,'error':str(exc)})
    if all_trades:
        dates=pd.DatetimeIndex(sorted({pd.Timestamp(t['signal_date']) for t in all_trades}));features=spy_regime_features(dates)
        for t in all_trades:t.update(classify_trade(t,features))
    summary={}
    for b in ('all','is_first_70pct','oos_last_30pct','recent_2y'):
        bt=bucket(all_trades,b);p=simulate_portfolio(bt)
        summary[b]={
            'baseline':{'trade_stats':pooled_stats(bt),'portfolio':{k:p.get(k) for k in ('return_pct','realized_pnl_krw','max_drawdown_pct','stress_drawdown_pct','accepted_trades','win_rate_pct','rejected_capacity','rejected_cash')}},
            'by_market_state':grouped_stats(bt,'market_state'),
            'by_volatility':grouped_stats(bt,'vol_bucket'),
            'by_drawdown':grouped_stats(bt,'dd_bucket'),
            'by_spy_5d':grouped_stats(bt,'ret5_bucket'),
            'deep_drawdown_rebound':{
                'true':pooled_stats([t for t in bt if t.get('deep_drawdown_rebound')]),
                'false':pooled_stats([t for t in bt if not t.get('deep_drawdown_rebound')]),
            },
            # Small set of diagnostic candidate filters, not production proposals yet.
            'candidate_exclusions':{
                'exclude_high_vol_80p':candidate_portfolio(bt,lambda t:t.get('vol_bucket')!='vol_high_80p'),
                'exclude_deep_dd_5pct':candidate_portfolio(bt,lambda t:t.get('dd_bucket')!='dd_deep_5pct'),
                'exclude_deep_rebound':candidate_portfolio(bt,lambda t:not t.get('deep_drawdown_rebound')),
                'market_good_only':candidate_portfolio(bt,lambda t:t.get('market_state')=='좋음'),
            },
        }
    payload={
        'study':'Live-like momentum pullback regime diagnosis','status':'RESEARCH_ONLY_DIAGNOSTIC','selection_source':source,'requested_symbol_count':len(requested),'eligible_symbol_count':len(eligible),'eligible_symbols':eligible,'errors':errors,
        'strategy_id':STRATEGY_ID,'trade_count':len(all_trades),'summary':summary,
        'feature_definitions':{
            'volatility':'SPY 20d realized vol annualized, ranked versus trailing 252d only',
            'drawdown':'SPY close versus trailing 20d high',
            'deep_drawdown_rebound':'SPY 20d drawdown <= -5% and 5d return >= +3%',
        },
        'decision_rule':'This is diagnosis. Only if one simple exclusion improves both broad OOS and recent finite-account results with adequate coverage should it become a fixed candidate for separate confirmation validation.',
    }
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'eligible_symbol_count':len(eligible),'trade_count':len(all_trades),'summary':summary,'errors_count':len(errors)},ensure_ascii=False,indent=2));return payload


if __name__=='__main__':run_research()
