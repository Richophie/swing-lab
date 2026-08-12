from flask import Flask, jsonify, request, send_from_directory
from functools import lru_cache
from io import StringIO
from datetime import datetime
import time, re, requests
import numpy as np
import pandas as pd
import yfinance as yf

app = Flask(__name__, static_folder="static")
UNIVERSE_CACHE={"ts":0,"symbols":[],"count":0,"source":"Nasdaq Symbol Directory"}
SCAN_CACHE={"date":None,"payload":None}


def indicators(df):
    c=df["Close"].astype(float); h=df["High"].astype(float); l=df["Low"].astype(float)
    v=df["Volume"].astype(float) if "Volume" in df else pd.Series(0,index=df.index)
    out=pd.DataFrame(index=df.index); out["close"]=c
    out["sma50"]=c.rolling(50).mean(); out["sma120"]=c.rolling(120).mean(); out["sma200"]=c.rolling(200).mean()
    d=c.diff(); g=d.clip(lower=0); loss=-d.clip(upper=0)
    ag=g.ewm(alpha=1/14,adjust=False,min_periods=14).mean(); al=loss.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    out["rsi"]=100-100/(1+ag/al.replace(0,np.nan))
    mid=c.rolling(20).mean(); sd=c.rolling(20).std(ddof=0)
    out["bb_low"]=mid-2*sd; out["bb_high"]=mid+2*sd; out["bb_pos"]=(c-out["bb_low"])/(out["bb_high"]-out["bb_low"])
    e12=c.ewm(span=12,adjust=False).mean(); e26=c.ewm(span=26,adjust=False).mean(); m=e12-e26
    out["macd_hist"]=m-m.ewm(span=9,adjust=False).mean()
    prev=c.shift(1); tr=pd.concat([(h-l).abs(),(h-prev).abs(),(l-prev).abs()],axis=1).max(axis=1)
    out["atr14"]=tr.rolling(14).mean(); out["vol20"]=v.rolling(20).mean(); out["volume"]=v
    return out


def swing_score(df):
    x=indicators(df).iloc[-1]
    close=float(x["close"]); rsi=float(x["rsi"]); bb=float(x["bb_pos"]); s120=float(x["sma120"])
    mh=float(x["macd_hist"]); s50=float(x["sma50"]); atr=float(x["atr14"])
    vr=float(x["volume"]/x["vol20"]) if x["vol20"] and not pd.isna(x["vol20"]) else np.nan
    d120=close/s120-1; atrp=atr/close
    rsiS=100 if 30<=rsi<=42 else 70 if 25<=rsi<30 else 75 if rsi<=50 else 45 if rsi<=60 else 20
    bbS=100 if bb<=.12 else 85 if bb<=.30 else 60 if bb<=.50 else 35 if bb<=.75 else 15
    sS=100 if abs(d120)<=.025 else 78 if -.06<d120<.05 else 42 if .05<=d120<.12 else 20
    macdS=82 if mh>0 else 30; trendS=85 if s50>=s120 else 45
    riskS=85 if atrp<=.025 else 70 if atrp<=.04 else 45 if atrp<=.06 else 20
    volS=85 if not pd.isna(vr) and 1.1<=vr<=2.5 else 65 if not pd.isna(vr) and vr>.75 else 40
    score=rsiS*.18+bbS*.17+sS*.22+macdS*.16+trendS*.12+volS*.07+riskS*.08
    if rsi<22 and close<s120*.93: score-=12
    score=max(0,min(100,score)); grade="S" if score>=82 else "A" if score>=72 else "B" if score>=58 else "C"
    return {"score":round(score,1),"grade":grade,"rsi":round(rsi,1),"bb_pos":round(bb*100,1),"d120":round(d120*100,2),"close":round(close,2),"atr_pct":round(atrp*100,2)}


def setup_ok(ind,i):
    r=ind.iloc[i]
    if pd.isna(r["rsi"]) or pd.isna(r["sma120"]) or pd.isna(r["bb_pos"]): return False
    return 28<=r["rsi"]<=45 and r["bb_pos"]<=.32 and abs(r["close"]/r["sma120"]-1)<=.035


def historical_stats(df,horizon=5):
    ind=indicators(df); rets=[]; last=-999
    for i in range(200,len(df)-horizon):
        if not setup_ok(ind,i) or i-last<=5: continue
        last=i; p=float(ind.iloc[i]["close"]); fut=df.iloc[i+1:i+1+horizon]
        rets.append(float(fut.iloc[-1]["Close"])/p-1)
    if not rets:return {"trades":0,"win_rate":None,"avg_return":None}
    a=np.array(rets); return {"trades":len(a),"win_rate":round(float((a>0).mean()*100),1),"avg_return":round(float(a.mean()*100),2)}


def estimate_target_days(df,target_pct,max_days=12):
    ind=indicators(df); hits=[]; samples=0; last=-999
    for i in range(200,len(df)-max_days):
        if not setup_ok(ind,i) or i-last<=5: continue
        last=i; samples+=1; p=float(ind.iloc[i]["close"]); level=p*(1+target_pct)
        for day,(_,r) in enumerate(df.iloc[i+1:i+1+max_days].iterrows(),1):
            if float(r["High"])>=level: hits.append(day); break
    if hits:
        a=np.array(hits); return {"days_low":max(1,int(np.percentile(a,25))),"days_high":max(1,int(np.percentile(a,75))),"days_mid":int(round(float(np.median(a)))),"hit_rate":round(len(hits)/samples*100,1),"samples":samples,"method":"과거 동일패턴"}
    x=ind.iloc[-1]; atrp=float(x["atr14"])/float(x["close"]) if not pd.isna(x["atr14"]) else .025
    est=max(2,min(max_days,int(round(target_pct/max(atrp*.62,.004)))))
    return {"days_low":max(1,est-1),"days_high":min(max_days,est+2),"days_mid":est,"hit_rate":None,"samples":samples,"method":"ATR 이동속도"}


def trade_plan(df):
    ind=indicators(df); x=ind.iloc[-1]; p=float(x["close"]); atr=float(x["atr14"]) if not pd.isna(x["atr14"]) else p*.025
    s120=float(x["sma120"]) if not pd.isna(x["sma120"]) else None; bbl=float(x["bb_low"]) if not pd.isna(x["bb_low"]) else None; bbh=float(x["bb_high"]) if not pd.isna(x["bb_high"]) else None
    low10=float(df["Low"].tail(10).min()); low20=float(df["Low"].tail(20).min()); high20=float(df["High"].tail(20).max()); high60=float(df["High"].tail(60).max())
    stops=[]
    if s120 and s120<p: stops.append((s120-atr*.18,"120일선 지지 붕괴"))
    if bbl and bbl<p: stops.append((bbl-atr*.12,"볼린저 하단 이탈"))
    if low10<p: stops.append((low10-atr*.18,"최근 10일 저점 이탈"))
    if low20<p: stops.append((low20-atr*.15,"최근 스윙저점 이탈"))
    stops.append((p-atr*1.35,"ATR 변동폭 이탈"))
    stop,stop_reason=max([z for z in stops if z[0]<p],key=lambda z:z[0]); stop=min(stop,p*.988); stop=max(stop,p*.94); risk=p-stop
    targets=[]
    for val,why in [(bbh,"볼린저 상단"),(high20,"최근 20일 고점"),(high60,"최근 60일 고점")]:
        if val and p*1.008<val<=p*1.12: targets.append((val,why))
    targets.append((p+atr*1.65,"ATR 예상 반등폭")); targets=sorted(targets,key=lambda z:z[0])
    target,why=targets[0]; target=max(target,p*1.01); target=min(target,p*1.08)
    if risk>0 and (target-p)/risk<1.25:
        better=[z for z in targets if z[0]>p+risk*1.25 and z[0]<=p*1.08]
        if better: target,why=better[0]
        else: target=min(p*1.08,p+risk*1.30); why="손익비를 만족하는 현실적 반등폭"
    rr=(target-p)/risk if risk>0 else None; tp=target/p-1; sp=1-stop/p
    eta=estimate_target_days(df,tp)
    return {"entry_low":round(max(p-atr*.22,p*.992),2),"entry_high":round(min(p+atr*.08,p*1.003),2),"target":round(target,2),"target_pct":round(tp*100,2),"target_reason":why,"target_days":eta,"stop":round(stop,2),"stop_pct":round(sp*100,2),"stop_reason":stop_reason,"risk_reward":round(rr,2) if rr else None,"rr_quality":"좋음" if rr and rr>=1.5 else "보통" if rr and rr>=1.2 else "나쁨"}


def bb_label(v):
    if v<0:return "하단 이탈 · 급락주의"
    if v<=20:return "하단 아주 가까움"
    if v<=35:return "하단 근처"
    if v<=70:return "중간 구간"
    if v<=100:return "상단 근처 · 추격주의"
    return "상단 돌파 · 과열주의"


def market_state():
    try:
        bulk=yf.download("SPY QQQ",period="1y",interval="1d",auto_adjust=False,group_by="ticker",threads=True,progress=False)
        total=0; details={}
        for s in ["SPY","QQQ"]:
            d=bulk[s].dropna(subset=["Open","High","Low","Close"]); x=indicators(d).iloc[-1]; sc=0
            if x["close"]>x["sma120"]:sc+=1
            if x["close"]>x["sma200"]:sc+=1
            if x["rsi"]>45:sc+=1
            total+=sc; details[s]={"score":sc,"rsi":round(float(x["rsi"]),1)}
        return {"state":"좋음" if total>=5 else "중립" if total>=3 else "조심","score":total,"details":details}
    except Exception as e:return {"state":"확인 실패","error":str(e)}


def clean_symbol(sym):return bool(re.match(r'^[A-Z][A-Z0-9.\-]{0,7}$',str(sym or '').strip().upper()))

def name_ok(name):
    n=str(name or '').lower(); bad=[" warrant"," warrants"," units"," unit "," rights"," right "," preferred"," preference"," depositary shares"," notes due"," bond"," etf"," etn"," acquisition corp"," acquisition company"]
    return not any(x in n for x in bad)


def load_universe(force=False):
    now=time.time()
    if not force and UNIVERSE_CACHE["symbols"] and now-UNIVERSE_CACHE["ts"]<86400:return UNIVERSE_CACHE
    urls=[("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt","nasdaq"),("https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt","other")]; sy=[]
    for url,kind in urls:
        r=requests.get(url,timeout=15,headers={"User-Agent":"Mozilla/5.0"}); r.raise_for_status(); df=pd.read_csv(StringIO(r.text),sep='|')
        for _,row in df.iterrows():
            sym=row.get("Symbol") if kind=="nasdaq" else row.get("ACT Symbol"); name=row.get("Security Name","")
            if str(row.get("ETF","N"))!="N" or str(row.get("Test Issue","N"))!="N":continue
            if kind=="other" and str(row.get("Exchange","")) not in {"A","N","P","Z"}:continue
            if clean_symbol(sym) and name_ok(name):sy.append(str(sym).upper())
    sy=sorted(set(sy)); UNIVERSE_CACHE.update({"ts":now,"symbols":sy,"count":len(sy)}); return UNIVERSE_CACHE


def prefilter(universe,max_candidates=700):
    try:
        q=yf.EquityQuery('and',[yf.EquityQuery('eq',['region','us']),yf.EquityQuery('is-in',['exchange','NMS','NGM','NCM','NYQ','ASE']),yf.EquityQuery('gte',['intradayprice',2]),yf.EquityQuery('gte',['avgdailyvol3m',200000]),yf.EquityQuery('gte',['intradaymarketcap',50000000])])
        rows=[]; offset=0
        while offset<5000:
            resp=yf.screen(q,offset=offset,size=250,sortField='avgdailyvol3m',sortAsc=False); quotes=resp.get('quotes',[]) if isinstance(resp,dict) else []
            if not quotes:break
            for x in quotes:
                s=str(x.get('symbol','')).upper()
                if s in universe:rows.append(s)
            offset+=len(quotes)
            if len(quotes)<250:break
        return list(dict.fromkeys(rows))[:max_candidates],len(rows)
    except Exception:return list(universe)[:max_candidates],len(universe)


def batch_scan(symbols,market):
    results=[]; failed=[]
    for start in range(0,len(symbols),160):
        chunk=symbols[start:start+160]
        try:bulk=yf.download(" ".join(chunk),period="10mo",interval="1d",auto_adjust=False,group_by="ticker",threads=True,progress=False)
        except Exception as e:failed.extend({"symbol":s,"reason":str(e)} for s in chunk);continue
        for s in chunk:
            try:
                d=bulk.copy() if len(chunk)==1 else bulk[s].copy(); d=d.dropna(subset=["Open","High","Low","Close"])
                if len(d)<120:raise ValueError("일봉 120개 미만")
                r=swing_score(d)
                if market.get("state")=="조심":r["score"]=max(0,r["score"]-5);r["grade"]="S" if r["score"]>=82 else "A" if r["score"]>=72 else "B" if r["score"]>=58 else "C"
                r["bb_label"]=bb_label(r["bb_pos"]); results.append({"symbol":s,**r})
            except Exception as e:failed.append({"symbol":s,"reason":str(e)})
    results.sort(key=lambda x:x["score"],reverse=True); return results,failed


@lru_cache(maxsize=256)
def history(symbol,period="10y"):
    d=yf.Ticker(symbol).history(period=period,auto_adjust=False)
    if d is None or d.empty:raise ValueError("가격 데이터를 찾지 못했습니다")
    return d.dropna(subset=["Open","High","Low","Close"]).copy()


@app.route("/")
def index():return send_from_directory("static","v5.html")

@app.route("/health")
def health():return jsonify({"ok":True,"version":"5.0"})

@app.route("/api/universe")
def universe():
    try:
        u=load_universe(request.args.get("refresh")=="1"); return jsonify({"count":u["count"],"source":u["source"]})
    except Exception as e:return jsonify({"error":str(e)}),500

@app.route("/api/scan-all")
def scan_all():
    global SCAN_CACHE
    refresh=request.args.get("refresh")=="1"; today=datetime.utcnow().strftime('%Y-%m-%d')
    if not refresh and SCAN_CACHE.get("date")==today and SCAN_CACHE.get("payload"):return jsonify({**SCAN_CACHE["payload"],"cached":True})
    try:
        u=load_universe(); universe=set(u["symbols"]); stage1,liquid=prefilter(universe); market=market_state(); base,failed=batch_scan(stage1,market); final=[]
        for r in base[:30]:
            try:
                d=history(r["symbol"],"10y"); plan=trade_plan(d); hist=historical_stats(d); score=float(r["score"])
                if plan["rr_quality"]=="나쁨":score-=7
                elif plan["rr_quality"]=="좋음":score+=3
                if hist["trades"]>=8 and hist["win_rate"] is not None:score+=max(-4,min(4,(hist["win_rate"]-50)/5))
                r["score"]=round(max(0,min(100,score)),1); r["grade"]="S" if r["score"]>=82 else "A" if r["score"]>=72 else "B" if r["score"]>=58 else "C"; r["trade_plan"]=plan; r["history_stats"]=hist; final.append(r)
            except Exception as e:r["detail_error"]=str(e);final.append(r)
        final.sort(key=lambda x:x["score"],reverse=True)
        payload={"results":final,"failed":failed[:30],"failed_count":len(failed),"market":market,"universe_count":u["count"],"liquid_count":liquid,"stage2_count":len(stage1),"scanned_at":datetime.now().isoformat(timespec='seconds')}; SCAN_CACHE={"date":today,"payload":payload}; return jsonify(payload)
    except Exception as e:return jsonify({"error":str(e)}),500

@app.route("/api/detail/<symbol>")
def detail(symbol):
    try:
        s=symbol.upper().strip(); d=history(s,"10y"); sig=swing_score(d); hist=historical_stats(d); plan=trade_plan(d); fx=None
        try:
            f=yf.Ticker("KRW=X").history(period="5d"); fx=float(f["Close"].dropna().iloc[-1]) if not f.empty else None
        except:pass
        earnings={"status":"확인 불가","date":None,"days":None}
        try:
            cal=yf.Ticker(s).calendar; vals=[]
            if isinstance(cal,dict):
                for k,v in cal.items():
                    if "Earnings" in str(k):vals.extend(v if isinstance(v,(list,tuple)) else [v])
            clean=[pd.to_datetime(x) for x in vals if pd.notna(pd.to_datetime(x,errors='coerce'))]
            if clean:
                ed=min(clean); days=(ed.tz_localize(None).normalize()-pd.Timestamp.now().normalize()).days if getattr(ed,'tzinfo',None) else (ed.normalize()-pd.Timestamp.now().normalize()).days; earnings={"status":"주의" if 0<=days<=7 else "여유","date":str(ed.date()),"days":int(days)}
        except:pass
        return jsonify({"symbol":s,"signal":sig,"history_stats":hist,"trade_plan":plan,"usdkrw":fx,"earnings":earnings,"market":market_state()})
    except Exception as e:return jsonify({"error":str(e)}),500

if __name__=="__main__":app.run(host="0.0.0.0",port=8766,debug=False)
