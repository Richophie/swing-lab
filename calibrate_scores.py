from datetime import datetime, timezone
from pathlib import Path
import json
import numpy as np
import pandas as pd
import yfinance as yf

from scanner_v6 import load_universe, prefilter
from app_v6 import indicators

OUT = Path(__file__).parent / 'static' / 'score_calibration.json'
BINS = [(0,49.99),(50,59.99),(60,69.99),(70,79.99),(80,89.99),(90,100)]


def raw_score_from_row(r):
    close=float(r['close']); rsi=float(r['rsi']); bb=float(r['bb_pos']); s120=float(r['sma120']); mh=float(r['macd_hist']); s50=float(r['sma50']); atr=float(r['atr14']); vol=float(r['volume']); vol20=float(r['vol20']) if not pd.isna(r['vol20']) else np.nan
    d120=close/s120-1; atrp=atr/close; vr=vol/vol20 if vol20 and not pd.isna(vol20) else np.nan
    rsiS=100 if 30<=rsi<=42 else 70 if 25<=rsi<30 else 75 if rsi<=50 else 45 if rsi<=60 else 20
    bbS=100 if bb<=.12 else 85 if bb<=.30 else 60 if bb<=.50 else 35 if bb<=.75 else 15
    sS=100 if abs(d120)<=.025 else 78 if -.06<d120<.05 else 42 if .05<=d120<.12 else 20
    macdS=82 if mh>0 else 30; trendS=85 if s50>=s120 else 45; riskS=85 if atrp<=.025 else 70 if atrp<=.04 else 45 if atrp<=.06 else 20
    volS=85 if not pd.isna(vr) and 1.1<=vr<=2.5 else 65 if not pd.isna(vr) and vr>.75 else 40
    score=rsiS*.18+bbS*.17+sS*.22+macdS*.16+trendS*.12+volS*.07+riskS*.08-(12 if rsi<22 and close<s120*.93 else 0)
    return max(0,min(100,float(score)))


def collect(symbols, horizon=5):
    rows=[]
    for start in range(0,len(symbols),40):
        chunk=symbols[start:start+40]
        try:
            bulk=yf.download(' '.join(chunk),period='5y',interval='1d',auto_adjust=False,group_by='ticker',threads=True,progress=False)
        except Exception:
            continue
        for s in chunk:
            try:
                d=bulk.copy() if len(chunk)==1 else bulk[s].copy(); d=d.dropna(subset=['Open','High','Low','Close'])
                if len(d)<260: continue
                ind=indicators(d)
                f=pd.DataFrame(index=d.index)
                for c in ['close','rsi','bb_pos','sma120','macd_hist','sma50','atr14','volume','vol20']:
                    f[c]=ind[c]
                f['fwd']=d['Close'].shift(-horizon)/d['Close']-1
                f=f.dropna()
                for _,r in f.iloc[200:-horizon].iterrows():
                    score=raw_score_from_row(r); ret=float(r['fwd'])*100
                    rows.append((score,ret))
            except Exception:
                continue
    return rows


def main():
    universe=load_universe(); symbols=prefilter(universe,max_candidates=180)[:180]
    samples=collect(symbols)
    buckets=[]; prev=0
    for lo,hi in BINS:
        vals=[ret for score,ret in samples if lo<=score<=hi]
        n=len(vals)
        win=round(sum(v>0 for v in vals)/n*100,1) if n else None
        avg=round(float(np.mean(vals)),3) if n else None
        if n:
            empirical=50 + (win-50)*0.85 + avg*3.0
            empirical=max(25,min(95,empirical))
        else:
            empirical=(lo+hi)/2
        calibrated=max(prev,min(95,empirical)); prev=calibrated
        buckets.append({'min':lo,'max':hi,'calibrated':round(calibrated,1),'win_rate':win,'avg_return':avg,'samples':n})
    payload={'version':datetime.now(timezone.utc).isoformat(timespec='seconds'),'method':'5y liquid-US equities, 5-trading-day forward outcome, monotonic bucket calibration','symbols':len(symbols),'samples_total':len(samples),'buckets':buckets}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print('saved',OUT,'samples',len(samples))

if __name__=='__main__': main()
