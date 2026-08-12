from io import StringIO
from pathlib import Path
from datetime import datetime, timezone
import json, re, requests
import pandas as pd
import yfinance as yf
from app_v6 import swing_score, trade_plan, historical_stats, market_live, history
from calibration import apply_calibration, calibrated_grade

OUT=Path(__file__).parent/'static'/'latest_scan.json'

def clean_symbol(sym):return bool(re.match(r'^[A-Z][A-Z0-9.\-]{0,7}$',str(sym or '').strip().upper()))
def name_ok(name):
    n=str(name or '').lower(); bad=[' warrant',' warrants',' units',' unit ',' rights',' right ',' preferred',' preference',' depositary shares',' notes due',' bond',' etf',' etn']
    return not any(x in n for x in bad)

def load_universe():
    urls=[('https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt','nasdaq'),('https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt','other')]; sy=[]
    for url,kind in urls:
        r=requests.get(url,timeout=25,headers={'User-Agent':'Mozilla/5.0'}); r.raise_for_status(); df=pd.read_csv(StringIO(r.text),sep='|')
        for _,row in df.iterrows():
            sym=row.get('Symbol') if kind=='nasdaq' else row.get('ACT Symbol'); name=row.get('Security Name','')
            if str(row.get('ETF','N'))!='N' or str(row.get('Test Issue','N'))!='N':continue
            if kind=='other' and str(row.get('Exchange','')) not in {'A','N','P','Z'}:continue
            if clean_symbol(sym) and name_ok(name):sy.append(str(sym).upper())
    return sorted(set(sy))

def prefilter(universe,max_candidates=700):
    uset=set(universe); rows=[]
    try:
        q=yf.EquityQuery('and',[yf.EquityQuery('eq',['region','us']),yf.EquityQuery('is-in',['exchange','NMS','NGM','NCM','NYQ','ASE']),yf.EquityQuery('gte',['intradayprice',2]),yf.EquityQuery('gte',['avgdailyvol3m',200000]),yf.EquityQuery('gte',['intradaymarketcap',50000000])])
        offset=0
        while offset<5000 and len(rows)<max_candidates:
            resp=yf.screen(q,offset=offset,size=250,sortField='avgdailyvol3m',sortAsc=False); quotes=resp.get('quotes',[]) if isinstance(resp,dict) else []
            if not quotes:break
            for x in quotes:
                s=str(x.get('symbol','')).upper()
                if s in uset:rows.append(s)
            offset+=len(quotes)
            if len(quotes)<250:break
    except Exception as e:print('prefilter fallback',e)
    if len(rows)<100:
        liquid_fallback=['AAPL','MSFT','NVDA','AMZN','META','GOOGL','AVGO','TSLA','JPM','V','WMT','MA','NFLX','COST','HD','PG','JNJ','BAC','CRM','AMD','PLTR','CSCO','CVX','IBM','GE','CAT','KO','PEP','DIS','QCOM','MU','UBER','SOFI','RBLX','COIN','SHOP','PYPL','NKE','F','GM']
        rows.extend([s for s in liquid_fallback if s in uset])
    return list(dict.fromkeys(rows))[:max_candidates]

def batch_score(symbols,market):
    results=[]; failed=0
    for start in range(0,len(symbols),120):
        chunk=symbols[start:start+120]
        try:bulk=yf.download(' '.join(chunk),period='10mo',interval='1d',auto_adjust=False,group_by='ticker',threads=True,progress=False)
        except Exception as e:print('chunk fail',e); failed+=len(chunk); continue
        for s in chunk:
            try:
                d=bulk.copy() if len(chunk)==1 else bulk[s].copy(); d=d.dropna(subset=['Open','High','Low','Close'])
                if len(d)<120:failed+=1;continue
                r=swing_score(d)
                if market.get('state')=='조심':
                    r['score']=round(max(0,r['score']-5),1); r['grade']='S' if r['score']>=82 else 'A' if r['score']>=72 else 'B' if r['score']>=58 else 'C'
                closes=[round(float(x),2) for x in d['Close'].tail(35).tolist()]
                r.update({'symbol':s,'sparkline':closes}); results.append(r)
            except Exception:failed+=1
    results.sort(key=lambda x:x['score'],reverse=True); return results,failed

def main():
    universe=load_universe(); candidates=prefilter(universe); market=market_live(); base,failed=batch_score(candidates,market); final=[]
    for r in base[:24]:
        try:
            d=history(r['symbol'],'10y'); p=trade_plan(d); h=historical_stats(d); raw=float(r['score'])
            if p['rr_quality']=='좋음':raw+=3
            elif p['rr_quality']=='나쁨':raw-=7
            if h['trades']>=8 and h['win_rate'] is not None:raw+=max(-4,min(4,(h['win_rate']-50)/5))
            raw=max(0,min(100,raw)); cal=apply_calibration(raw)
            r['raw_score']=round(raw,1); r['score']=cal['calibrated_score']; r['grade']=calibrated_grade(r['score']); r['calibration']=cal; r['trade_plan']=p; r['history_stats']=h; final.append(r)
        except Exception as e:r['detail_error']=str(e); final.append(r)
    final.sort(key=lambda x:x['score'],reverse=True)
    payload={'status':'ready','version':'8.1','scanned_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'universe_count':len(universe),'candidate_count':len(candidates),'failed_count':failed,'market':market,'results':final}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8'); print('saved',OUT,len(final))

if __name__=='__main__':main()
