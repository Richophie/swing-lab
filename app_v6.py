from flask import Flask, jsonify, send_from_directory
from functools import lru_cache
from pathlib import Path
import json
import numpy as np
import pandas as pd
import yfinance as yf

app=Flask(__name__,static_folder='static')
CACHE_FILE=Path(__file__).parent/'static'/'latest_scan.json'

def indicators(df):
    c=df['Close'].astype(float); h=df['High'].astype(float); l=df['Low'].astype(float)
    v=df['Volume'].astype(float) if 'Volume' in df else pd.Series(0,index=df.index)
    o=pd.DataFrame(index=df.index); o['close']=c; o['sma50']=c.rolling(50).mean(); o['sma120']=c.rolling(120).mean(); o['sma200']=c.rolling(200).mean()
    d=c.diff(); g=d.clip(lower=0); loss=-d.clip(upper=0); ag=g.ewm(alpha=1/14,adjust=False,min_periods=14).mean(); al=loss.ewm(alpha=1/14,adjust=False,min_periods=14).mean(); o['rsi']=100-100/(1+ag/al.replace(0,np.nan))
    mid=c.rolling(20).mean(); sd=c.rolling(20).std(ddof=0); o['bb_low']=mid-2*sd; o['bb_high']=mid+2*sd; o['bb_pos']=(c-o['bb_low'])/(o['bb_high']-o['bb_low'])
    e12=c.ewm(span=12,adjust=False).mean(); e26=c.ewm(span=26,adjust=False).mean(); m=e12-e26; o['macd_hist']=m-m.ewm(span=9,adjust=False).mean()
    prev=c.shift(1); tr=pd.concat([(h-l).abs(),(h-prev).abs(),(l-prev).abs()],axis=1).max(axis=1); o['atr14']=tr.rolling(14).mean(); o['vol20']=v.rolling(20).mean(); o['volume']=v
    return o

def swing_score(df):
    x=indicators(df).iloc[-1]; close=float(x['close']); rsi=float(x['rsi']); bb=float(x['bb_pos']); s120=float(x['sma120']); mh=float(x['macd_hist']); s50=float(x['sma50']); atr=float(x['atr14']); vr=float(x['volume']/x['vol20']) if x['vol20'] and not pd.isna(x['vol20']) else np.nan
    d120=close/s120-1; atrp=atr/close; rsiS=100 if 30<=rsi<=42 else 70 if 25<=rsi<30 else 75 if rsi<=50 else 45 if rsi<=60 else 20; bbS=100 if bb<=.12 else 85 if bb<=.30 else 60 if bb<=.50 else 35 if bb<=.75 else 15; sS=100 if abs(d120)<=.025 else 78 if -.06<d120<.05 else 42 if .05<=d120<.12 else 20; macdS=82 if mh>0 else 30; trendS=85 if s50>=s120 else 45; riskS=85 if atrp<=.025 else 70 if atrp<=.04 else 45 if atrp<=.06 else 20; volS=85 if not pd.isna(vr) and 1.1<=vr<=2.5 else 65 if not pd.isna(vr) and vr>.75 else 40
    score=max(0,min(100,rsiS*.18+bbS*.17+sS*.22+macdS*.16+trendS*.12+volS*.07+riskS*.08-(12 if rsi<22 and close<s120*.93 else 0))); grade='S' if score>=82 else 'A' if score>=72 else 'B' if score>=58 else 'C'
    return {'score':round(score,1),'grade':grade,'rsi':round(rsi,1),'bb_pos':round(bb*100,1),'d120':round(d120*100,2),'close':round(close,2),'atr_pct':round(atrp*100,2),'sma120':round(s120,2)}

def setup_ok(ind,i):
    r=ind.iloc[i]; return not (pd.isna(r['rsi']) or pd.isna(r['sma120']) or pd.isna(r['bb_pos'])) and 28<=r['rsi']<=45 and r['bb_pos']<=.32 and abs(r['close']/r['sma120']-1)<=.035

def historical_stats(df,horizon=5):
    ind=indicators(df); rets=[]; last=-999
    for i in range(200,len(df)-horizon):
        if not setup_ok(ind,i) or i-last<=5: continue
        last=i; p=float(ind.iloc[i]['close']); rets.append(float(df.iloc[i+horizon]['Close'])/p-1)
    if not rets:return {'trades':0,'win_rate':None,'avg_return':None}
    a=np.array(rets); return {'trades':len(a),'win_rate':round(float((a>0).mean()*100),1),'avg_return':round(float(a.mean()*100),2)}

def estimate_days(df,tp,max_days=12):
    ind=indicators(df); hits=[]; samples=0; last=-999
    for i in range(200,len(df)-max_days):
        if not setup_ok(ind,i) or i-last<=5:continue
        last=i; samples+=1; p=float(ind.iloc[i]['close']); level=p*(1+tp)
        for day,(_,r) in enumerate(df.iloc[i+1:i+1+max_days].iterrows(),1):
            if float(r['High'])>=level:hits.append(day);break
    if hits:
        a=np.array(hits); return {'days_low':max(1,int(np.percentile(a,25))),'days_high':max(1,int(np.percentile(a,75))),'days_mid':int(round(float(np.median(a)))),'hit_rate':round(len(hits)/samples*100,1),'samples':samples,'method':'과거 동일패턴'}
    x=ind.iloc[-1]; atrp=float(x['atr14'])/float(x['close']) if not pd.isna(x['atr14']) else .025; est=max(2,min(max_days,int(round(tp/max(atrp*.62,.004))))); return {'days_low':max(1,est-1),'days_high':min(max_days,est+2),'days_mid':est,'hit_rate':None,'samples':samples,'method':'ATR 이동속도'}

def trade_plan(df):
    ind=indicators(df); x=ind.iloc[-1]; p=float(x['close']); atr=float(x['atr14']) if not pd.isna(x['atr14']) else p*.025; s120=float(x['sma120']) if not pd.isna(x['sma120']) else None; bbl=float(x['bb_low']) if not pd.isna(x['bb_low']) else None; bbh=float(x['bb_high']) if not pd.isna(x['bb_high']) else None; low10=float(df['Low'].tail(10).min()); low20=float(df['Low'].tail(20).min()); high20=float(df['High'].tail(20).max()); high60=float(df['High'].tail(60).max())
    stops=[]
    for val,why in [(s120-atr*.18 if s120 and s120<p else None,'120일선 지지 붕괴'),(bbl-atr*.12 if bbl and bbl<p else None,'볼린저 하단 이탈'),(low10-atr*.18,'최근 10일 저점 이탈'),(low20-atr*.15,'최근 스윙저점 이탈'),(p-atr*1.35,'ATR 변동폭 이탈')]:
        if val and val<p:stops.append((val,why))
    stop,stop_reason=max(stops,key=lambda z:z[0]); stop=max(p*.94,min(p*.988,stop)); risk=p-stop
    targets=[]
    for val,why in [(bbh,'볼린저 상단'),(high20,'최근 20일 고점'),(high60,'최근 60일 고점')]:
        if val and p*1.008<val<=p*1.12:targets.append((val,why))
    targets.append((p+atr*1.65,'ATR 예상 반등폭')); targets.sort(key=lambda z:z[0]); target,why=targets[0]; target=max(p*1.01,min(p*1.08,target)); rr=(target-p)/risk if risk>0 else 0
    if rr<1.25:target=min(p*1.08,p+risk*1.30); why='손익비를 만족하는 현실적 반등폭'; rr=(target-p)/risk
    tp=target/p-1; eta=estimate_days(df,tp)
    return {'entry_low':round(max(p-atr*.22,p*.992),2),'entry_high':round(min(p+atr*.08,p*1.003),2),'target':round(target,2),'target_pct':round(tp*100,2),'target_reason':why,'target_days':eta,'stop':round(stop,2),'stop_pct':round((1-stop/p)*100,2),'stop_reason':stop_reason,'risk_reward':round(rr,2),'rr_quality':'좋음' if rr>=1.5 else '보통' if rr>=1.2 else '나쁨'}

@lru_cache(maxsize=256)
def history(symbol,period='10y'):
    d=yf.Ticker(symbol).history(period=period,auto_adjust=False)
    if d is None or d.empty:raise ValueError('가격 데이터를 찾지 못했습니다')
    return d.dropna(subset=['Open','High','Low','Close']).copy()

def market_live():
    try:
        bulk=yf.download('SPY QQQ',period='1y',interval='1d',auto_adjust=False,group_by='ticker',threads=True,progress=False); total=0; details={}
        for s in ['SPY','QQQ']:
            d=bulk[s].dropna(subset=['Open','High','Low','Close']); x=indicators(d).iloc[-1]; above120=bool(x['close']>x['sma120']); above200=bool(x['close']>x['sma200']); rsi=float(x['rsi']); sc=int(above120)+int(above200)+int(rsi>45); total+=sc; details[s]={'score':sc,'rsi':round(rsi,1),'above120':above120,'above200':above200}
        state='좋음' if total>=5 else '중립' if total>=3 else '조심'; reasons=[]
        for s in ['SPY','QQQ']:
            q=details[s]; reasons.append(f"{s} {'120·200일선 위' if q['above120'] and q['above200'] else '장기선 일부 이탈'} · RSI {q['rsi']}")
        action='눌림목 후보를 적극 관찰하되 추격매수는 자제' if state=='좋음' else '조건이 겹치는 종목만 선별' if state=='중립' else '현금 비중과 손절 기준을 더 보수적으로'
        return {'state':state,'score':total,'details':details,'brief':' / '.join(reasons),'action':action}
    except Exception as e:return {'state':'확인 실패','brief':str(e),'action':'저장된 후보는 보되 시장 확인 후 진입'}

@app.route('/')
def index():return send_from_directory('static','v6.html')
@app.route('/health')
def health():return jsonify({'ok':True,'version':'6.0'})
@app.route('/api/latest')
def latest():
    try:
        if not CACHE_FILE.exists():return jsonify({'status':'pending','results':[],'message':'자동 스캔 결과를 준비 중입니다.'})
        return jsonify(json.loads(CACHE_FILE.read_text(encoding='utf-8')))
    except Exception as e:return jsonify({'status':'error','results':[],'message':str(e)}),200
@app.route('/api/market')
def market():return jsonify(market_live())
@app.route('/api/detail/<symbol>')
def detail(symbol):
    try:
        s=symbol.upper().strip(); d=history(s,'10y'); sig=swing_score(d); hist=historical_stats(d); plan=trade_plan(d); fx=None
        try:
            f=yf.Ticker('KRW=X').history(period='5d'); fx=float(f['Close'].dropna().iloc[-1]) if not f.empty else None
        except:pass
        return jsonify({'symbol':s,'signal':sig,'history_stats':hist,'trade_plan':plan,'usdkrw':fx,'market':market_live()})
    except Exception as e:return jsonify({'error':str(e)}),400

if __name__=='__main__':app.run(host='0.0.0.0',port=8766,debug=False)
