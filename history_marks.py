from datetime import datetime,timezone
from pathlib import Path
import json,yfinance as yf

P=Path(__file__).parent/'static'/'trade_history.json'

def ref(x):
    a=x.get('entry_low');b=x.get('entry_high')
    try:return (float(a)+float(b))/2,'BUY 구간 중앙값'
    except Exception:pass
    try:return float((x.get('sparkline') or [])[-1]),'최초 추천 당시 종가'
    except Exception:return None,None

def main():
    try:d=json.loads(P.read_text(encoding='utf-8'))
    except Exception:return
    items=[x for day in d.get('days',[]) for x in day.get('items',[])]
    syms=sorted({str(x.get('symbol','')).upper() for x in items if x.get('symbol')})
    if not syms:return
    try:q=yf.download(' '.join(syms),period='5d',interval='1d',auto_adjust=False,group_by='ticker',threads=True,progress=False,timeout=30)
    except Exception:return
    now=datetime.now(timezone.utc).isoformat(timespec='seconds');cache={};count=len(syms);done=0
    for x in items:
        s=str(x.get('symbol','')).upper();r,basis=ref(x)
        if not s or not r:continue
        if s not in cache:
            try:
                f=q.copy() if count==1 else q[s].copy();f=f.dropna(subset=['Close']);row=f.iloc[-1];cache[s]=(float(row['Close']),str(f.index[-1])[:10])
            except Exception:cache[s]=(None,None)
        price,day=cache[s]
        if price is None:continue
        x.update(current_price=round(price,4),current_return_pct=round((price/r-1)*100,2),current_reference_price=round(r,4),current_reference_basis=basis,current_price_market_date=day,current_marked_at=now);done+=1
    d['current_marks_updated_at']=now;d['current_marks_basis']='entry midpoint; outcome stays frozen';P.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
    print('archive marks',done,'/',len(items))

if __name__=='__main__':main()
