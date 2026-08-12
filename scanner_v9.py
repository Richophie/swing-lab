from datetime import datetime, timezone
from pathlib import Path
import json
import pandas as pd
import yfinance as yf

from scanner_v6 import load_universe, prefilter
from app_v6 import trade_plan, historical_stats, market_live, history
from core_v2 import score_v2

OUT=Path(__file__).parent/'static'/'latest_scan.json'


def batch_score(symbols, market):
    results=[]; failed=0
    state=market.get('state') if isinstance(market,dict) else None
    for start in range(0,len(symbols),120):
        chunk=symbols[start:start+120]
        try:
            bulk=yf.download(' '.join(chunk),period='14mo',interval='1d',auto_adjust=False,group_by='ticker',threads=True,progress=False)
        except Exception:
            failed+=len(chunk); continue
        for s in chunk:
            try:
                d=bulk.copy() if len(chunk)==1 else bulk[s].copy(); d=d.dropna(subset=['Open','High','Low','Close'])
                if len(d)<205: failed+=1; continue
                sig=score_v2(d,state)
                sig.update({'symbol':s,'sparkline':[round(float(x),2) for x in d['Close'].tail(35).tolist()]})
                results.append(sig)
            except Exception:
                failed+=1
    results.sort(key=lambda x:(1 if x.get('eligible') else 0,x.get('score',0)),reverse=True)
    return results,failed


def main():
    universe=load_universe(); candidates=prefilter(universe); market=market_live(); base,failed=batch_score(candidates,market); final=[]
    # Deep analysis only on the best confirmed setups first.
    ordered=[r for r in base if r.get('eligible')] + [r for r in base if not r.get('eligible')]
    for r in ordered[:30]:
        try:
            d=history(r['symbol'],'10y'); p=trade_plan(d); h=historical_stats(d)
            r['trade_plan']=p; r['history_stats']=h
            # Historical stats are shown as evidence, not used to boost score.
            final.append(r)
        except Exception as e:
            r['detail_error']=str(e); final.append(r)
    final.sort(key=lambda x:(1 if x.get('eligible') else 0,x.get('score',0)),reverse=True)
    payload={'status':'ready','version':'9.0','core_version':'2.0','scanned_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
             'universe_count':len(universe),'candidate_count':len(candidates),'failed_count':failed,'market':market,'results':final,
             'ranking_note':'과거 승률로 오늘 점수를 직접 부풀리지 않고, 현재 기술조건+확인조건으로 순위를 정합니다.'}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print('saved',OUT,len(final))

if __name__=='__main__': main()
