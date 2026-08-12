from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import pandas as pd
import yfinance as yf

from config import APP_VERSION, CORE_VERSION, S_THRESHOLD, SCAN_CANDIDATE_LIMIT
from market_data import load_us_universe, prefilter_symbols, market_snapshot, indicators, load_price_history
from strategy_engine import evaluate_strategies, trade_plan, public_s_signals, experimental_s_signals
from stock_names import korean_name

OUT=Path(__file__).parent/'static'/'latest_scan.json'


def _extract_frame(bulk,symbol,count):
    try:
        d=bulk.copy() if count==1 else bulk[symbol].copy()
        return d.dropna(subset=['Open','High','Low','Close']).copy()
    except Exception:
        return pd.DataFrame()


def _dedupe_share_classes(rows):
    groups=[({'GOOG','GOOGL'},'GOOGL')]
    out=list(rows)
    for group,preferred in groups:
        present=[r for r in out if r['symbol'] in group]
        if len(present)>1:
            keep=next((r for r in present if r['symbol']==preferred),max(present,key=lambda r:r['score']))
            out=[r for r in out if r['symbol'] not in group or r is keep]
    return out


def scan_candidates(symbols,market,security_names):
    rows=[];failed=[];state=market.get('state')
    for start in range(0,len(symbols),100):
        chunk=symbols[start:start+100]
        try:
            bulk=yf.download(' '.join(chunk),period='14mo',interval='1d',auto_adjust=False,group_by='ticker',threads=True,progress=False,timeout=25)
        except Exception as exc:
            failed.extend({'symbol':s,'reason':str(exc)} for s in chunk);continue
        for symbol in chunk:
            try:
                d=_extract_frame(bulk,symbol,len(chunk))
                if len(d)<205: raise ValueError('일봉 205개 미만')
                ev=evaluate_strategies(d,state); pub=public_s_signals(ev); exp=experimental_s_signals(ev)
                if not pub and not exp: continue
                ind=indicators(d); tail=ind.tail(35); close_tail=d['Close'].tail(35)
                all_s=pub+exp; all_s.sort(key=lambda x:x['score'],reverse=True); best=all_s[0]
                row={'symbol':symbol,'name_ko':korean_name(symbol,security_names.get(symbol)),'security_name':security_names.get(symbol),'score':best['score'],'grade':'S','eligible':True,'strategy_id':best['id'],'strategy_name':best['name'],'strategy_reason':best['evidence'],'strategy_signals':[{'strategy_id':s['id'],'strategy_name':s['name'],'strategy_score':s['score'],'why':s['why'],'evidence':s['evidence'],'experimental':s['id']=='volatility_breakout'} for s in all_s],'rsi':ev['metrics']['rsi'],'d120':ev['metrics']['d120'],'bb_pos':ev['metrics']['bb_pos'],'atr_pct':ev['metrics']['atr_pct'],'sparkline':[round(float(x),2) for x in close_tail.tolist()],'bb_high_spark':[None if pd.isna(x) else round(float(x),2) for x in tail['bb_high'].tolist()],'bb_low_spark':[None if pd.isna(x) else round(float(x),2) for x in tail['bb_low'].tolist()]}
                rows.append(row)
            except Exception as exc:
                failed.append({'symbol':symbol,'reason':str(exc)})
    return rows,failed


def enrich_plans(rows):
    out=[]
    for row in rows:
        try:
            d=load_price_history(row['symbol'],'10y'); plans={}
            for sig in row['strategy_signals']:
                plans[sig['strategy_id']]=trade_plan(d,sig['strategy_id'])
            row['strategy_trade_plans']=plans;row['trade_plan']=plans[row['strategy_id']];out.append(row)
        except Exception as exc:
            row['detail_error']=str(exc);out.append(row)
    return out


def main():
    universe=load_us_universe(); names={x['symbol']:x['security_name'] for x in universe}; symbols=prefilter_symbols(universe,SCAN_CANDIDATE_LIMIT);market=market_snapshot()
    rows,failed=scan_candidates(symbols,market,names);rows=_dedupe_share_classes(rows);rows=enrich_plans(rows);rows.sort(key=lambda r:r['score'],reverse=True)
    public_count=sum(any(not s.get('experimental') for s in r['strategy_signals']) for r in rows);experimental_count=sum(any(s.get('experimental') for s in r['strategy_signals']) for r in rows)
    payload={'status':'ready','version':APP_VERSION,'core_version':CORE_VERSION,'scanned_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'universe_count':len(universe),'candidate_count':len(symbols),'failed_count':len(failed),'failed':failed[:100],'market':market,'results':rows,'public_s_count':public_count,'experimental_s_count':experimental_count,'display_filter':'public S only; breakout retained as experimental data','s_threshold':S_THRESHOLD}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');print('saved',OUT,len(rows),'rows')

if __name__=='__main__':main()
