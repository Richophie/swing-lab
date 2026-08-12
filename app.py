
from flask import Flask, request, jsonify, send_from_directory
import yfinance as yf
import pandas as pd
import numpy as np
try:
    from backtesting import Backtest, Strategy
    HAS_BACKTESTING = True
except Exception:
    HAS_BACKTESTING = False
from functools import lru_cache
from datetime import datetime, timedelta

app = Flask(__name__, static_folder="static")

def clean_num(v):
    try:
        if v is None or (isinstance(v,float) and np.isnan(v)): return None
        return float(v)
    except: return None

def indicators(df):
    c = df["Close"].astype(float)
    h = df["High"].astype(float)
    l = df["Low"].astype(float)
    v = df["Volume"].astype(float) if "Volume" in df else pd.Series(index=df.index, data=0)

    out = pd.DataFrame(index=df.index)
    out["close"] = c
    out["sma50"] = c.rolling(50).mean()
    out["sma120"] = c.rolling(120).mean()
    out["sma200"] = c.rolling(200).mean()

    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    ag = gain.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    al = loss.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rs = ag / al.replace(0, np.nan)
    out["rsi"] = 100 - 100/(1+rs)

    mid = c.rolling(20).mean()
    sd = c.rolling(20).std(ddof=0)
    out["bb_low"] = mid - 2*sd
    out["bb_mid"] = mid
    out["bb_high"] = mid + 2*sd
    out["bb_pos"] = (c - out["bb_low"]) / (out["bb_high"] - out["bb_low"])

    e12 = c.ewm(span=12, adjust=False).mean()
    e26 = c.ewm(span=26, adjust=False).mean()
    macd = e12-e26
    sig = macd.ewm(span=9, adjust=False).mean()
    out["macd_hist"] = macd-sig

    prev = c.shift(1)
    tr = pd.concat([(h-l).abs(), (h-prev).abs(), (l-prev).abs()], axis=1).max(axis=1)
    out["atr14"] = tr.rolling(14).mean()
    out["vol20"] = v.rolling(20).mean()
    out["volume"] = v
    return out

def swing_score(df):
    ind = indicators(df)
    x = ind.iloc[-1]
    close = x["close"]; rsi = x["rsi"]; bbpos = x["bb_pos"]; sma120 = x["sma120"]
    mh = x["macd_hist"]; sma50=x["sma50"]; atr=x["atr14"]
    volratio = x["volume"]/x["vol20"] if x["vol20"] and not pd.isna(x["vol20"]) else np.nan

    rsiS = 100 if 30<=rsi<=42 else 35 if rsi<25 else 70 if rsi<30 else 75 if rsi<=50 else 45 if rsi<=60 else 20
    bbS = 100 if bbpos<=.12 else 85 if bbpos<=.30 else 60 if bbpos<=.50 else 35 if bbpos<=.75 else 15
    d120 = close/sma120-1 if not pd.isna(sma120) else np.nan
    s120S = 100 if abs(d120)<=.025 else 78 if -.06<d120<.05 else 42 if .05<=d120<.12 else 20
    macdS = 82 if mh>0 else 30
    trendS = 85 if (not pd.isna(sma50) and not pd.isna(sma120) and sma50>=sma120) else 45
    atrpct = atr/close if not pd.isna(atr) else np.nan
    riskS = 85 if atrpct<=.025 else 70 if atrpct<=.04 else 45 if atrpct<=.06 else 20
    volS = 85 if not pd.isna(volratio) and 1.1<=volratio<=2.5 else 65 if not pd.isna(volratio) and volratio>.75 else 40

    score = rsiS*.18 + bbS*.17 + s120S*.22 + macdS*.16 + trendS*.12 + volS*.07 + riskS*.08
    if rsi<22 and close<sma120*.93: score -= 12
    score = max(0,min(100,score))
    grade = "S" if score>=82 else "A" if score>=72 else "B" if score>=58 else "C"
    return {
        "score": round(score,1), "grade": grade, "rsi": round(float(rsi),1),
        "bb_pos": round(float(bbpos)*100,1), "d120": round(float(d120)*100,2),
        "macd_hist": round(float(mh),4), "close": round(float(close),2),
        "sma120": round(float(sma120),2), "atr_pct": round(float(atrpct)*100,2)
    }

def backtest(df, horizon=5, tp=.03, sl=.02, cooldown=5):
    ind = indicators(df)
    events=[]; last_i=-999
    for i in range(200, len(df)-horizon):
        r=ind.iloc[i]
        if pd.isna(r["rsi"]) or pd.isna(r["sma120"]) or pd.isna(r["bb_pos"]): continue
        cond=(28<=r["rsi"]<=45 and r["bb_pos"]<=.32 and abs(r["close"]/r["sma120"]-1)<=.035)
        if not cond or i-last_i<=cooldown: continue
        last_i=i; p=float(r["close"]); fut=df.iloc[i+1:i+1+horizon]
        ret=None
        for _,d in fut.iterrows():
            ht=float(d["High"])>=p*(1+tp); hs=float(d["Low"])<=p*(1-sl)
            if ht and hs: ret=-sl; break
            if hs: ret=-sl; break
            if ht: ret=tp; break
        if ret is None: ret=float(fut.iloc[-1]["Close"])/p-1
        events.append(ret)
    if not events:return {"trades":0}
    arr=np.array(events); eq=np.cumprod(1+arr); peak=np.maximum.accumulate(eq); mdd=np.min(eq/peak-1)
    return {"trades":int(len(arr)),"win_rate":round(float((arr>0).mean()*100),1),
            "expectancy":round(float(arr.mean()*100),2),"compound":round(float((eq[-1]-1)*100),1),
            "mdd":round(float(mdd*100),1)}

def chart_rows(df, n=260):
    d=df.tail(n); ind=indicators(d)
    out=[]
    for i,(idx,row) in enumerate(d.iterrows()):
        x=ind.iloc[i]
        out.append({"date":str(idx.date()),"close":round(float(row["Close"]),2),
                    "sma50":clean_num(x["sma50"]),"sma120":clean_num(x["sma120"]),
                    "sma200":clean_num(x["sma200"]),"bb_low":clean_num(x["bb_low"]),
                    "bb_high":clean_num(x["bb_high"])})
    return out


def simple_market_state():
    try:
        bulk = yf.download("SPY QQQ", period="1y", interval="1d", auto_adjust=False,
                           group_by="ticker", threads=True, progress=False)
        scores = []
        details = {}
        for s in ["SPY","QQQ"]:
            df = bulk[s].dropna(subset=["Open","High","Low","Close"])
            sig = swing_score(df)
            ind = indicators(df)
            x = ind.iloc[-1]
            score = 0
            if not pd.isna(x["sma120"]) and x["close"] > x["sma120"]: score += 1
            if not pd.isna(x["sma200"]) and x["close"] > x["sma200"]: score += 1
            if not pd.isna(x["rsi"]) and x["rsi"] > 45: score += 1
            scores.append(score)
            details[s] = {"score":score,"rsi":round(float(x["rsi"]),1) if not pd.isna(x["rsi"]) else None,
                          "d120":round(float((x["close"]/x["sma120"]-1)*100),2) if not pd.isna(x["sma120"]) else None}
        total = sum(scores)
        state = "좋음" if total >= 5 else "중립" if total >= 3 else "조심"
        return {"state":state,"score":total,"details":details}
    except Exception as e:
        return {"state":"확인 실패","score":None,"details":{},"error":str(e)}

def historical_setup_stats(df, horizon=5):
    ind = indicators(df)
    events=[]; last_i=-999
    for i in range(200, len(df)-horizon):
        r=ind.iloc[i]
        if pd.isna(r["rsi"]) or pd.isna(r["sma120"]) or pd.isna(r["bb_pos"]): continue
        ok=(28<=r["rsi"]<=45 and r["bb_pos"]<=.32 and abs(r["close"]/r["sma120"]-1)<=.035)
        if not ok or i-last_i<=5: continue
        last_i=i
        p=float(r["close"]); fut=df.iloc[i+1:i+1+horizon]
        ret=float(fut.iloc[-1]["Close"])/p-1
        events.append(ret)
    if not events:
        return {"trades":0,"win_rate":None,"avg_return":None}
    a=np.array(events)
    return {"trades":int(len(a)),"win_rate":round(float((a>0).mean()*100),1),
            "avg_return":round(float(a.mean()*100),2)}

def run_backtesting_py(df, tp=.03, sl=.02, max_hold=5):
    if not HAS_BACKTESTING or len(df) < 250:
        return None
    try:
        z = df[["Open","High","Low","Close","Volume"]].copy()
        class SwingRule(Strategy):
            tpv=tp; slv=sl; hold=max_hold
            def init(self):
                close = pd.Series(self.data.Close)
                def rsi_arr(a):
                    s=pd.Series(a)
                    d=s.diff(); g=d.clip(lower=0); l=-d.clip(upper=0)
                    ag=g.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
                    al=l.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
                    return (100-100/(1+ag/al.replace(0,np.nan))).values
                def sma_arr(a,p):
                    return pd.Series(a).rolling(p).mean().values
                def bbpos_arr(a):
                    s=pd.Series(a); m=s.rolling(20).mean(); sd=s.rolling(20).std(ddof=0)
                    lo=m-2*sd; hi=m+2*sd
                    return ((s-lo)/(hi-lo)).values
                self.rsi=self.I(rsi_arr,self.data.Close)
                self.s120=self.I(lambda a:sma_arr(a,120),self.data.Close)
                self.bb=self.I(bbpos_arr,self.data.Close)
                self.entry_bar=None
            def next(self):
                if self.position:
                    if self.entry_bar is not None and len(self.data)-self.entry_bar>=self.hold:
                        self.position.close()
                    return
                c=float(self.data.Close[-1]); r=float(self.rsi[-1]); s=float(self.s120[-1]); b=float(self.bb[-1])
                if np.isfinite(r) and np.isfinite(s) and np.isfinite(b) and 28<=r<=45 and b<=.32 and abs(c/s-1)<=.035:
                    self.buy(sl=c*(1-self.slv), tp=c*(1+self.tpv))
                    self.entry_bar=len(self.data)
        bt=Backtest(z, SwingRule, cash=100000, commission=.0015, exclusive_orders=True, trade_on_close=True)
        st=bt.run()
        return {"trades":int(st["# Trades"]),"win_rate":round(float(st["Win Rate [%]"]),1),
                "return":round(float(st["Return [%]"]),1),"max_dd":round(float(st["Max. Drawdown [%]"]),1),
                "expectancy":round(float(st["Expectancy [%]"]),2) if "Expectancy [%]" in st else None,
                "profit_factor":round(float(st["Profit Factor"]),2) if pd.notna(st["Profit Factor"]) else None}
    except Exception:
        return None

def bollinger_label(v):
    if v is None: return "확인 불가"
    if v < 0: return "하단 이탈 · 급락주의"
    if v <= 20: return "하단 아주 가까움"
    if v <= 35: return "하단 근처"
    if v <= 70: return "중간 구간"
    if v <= 100: return "상단 근처 · 추격주의"
    return "상단 돌파 · 과열주의"

DUPLICATE_GROUPS = {
    "GOOG":"GOOGL",
    "BRK-B":"BRK-B"
}

def dedupe_results(results):
    seen=set(); out=[]
    for r in results:
        key=DUPLICATE_GROUPS.get(r.get("symbol"), r.get("symbol"))
        if key in seen: continue
        seen.add(key); out.append(r)
    return out

@lru_cache(maxsize=256)
def get_history(symbol, period="10y"):
    t=yf.Ticker(symbol)
    df=t.history(period=period, auto_adjust=False)
    if df is None or df.empty: raise ValueError("가격 데이터를 찾지 못했습니다.")
    df=df.dropna(subset=["Open","High","Low","Close"]).copy()
    return df

@app.route("/")
def index():
    return send_from_directory("static","index.html")

@app.route("/api/search")
def search():
    q=request.args.get("q","").strip()
    if not q: return jsonify([])
    try:
        s=yf.Search(q, max_results=8)
        quotes=[]
        for x in getattr(s,"quotes",[])[:8]:
            if x.get("symbol"):
                quotes.append({
                    "symbol":x.get("symbol"),
                    "name":x.get("shortname") or x.get("longname") or "",
                    "exchange":x.get("exchange") or "",
                    "type":x.get("quoteType") or ""
                })
        return jsonify(quotes)
    except Exception as e:
        return jsonify({"error":str(e)}),500

@app.route("/api/analyze/<symbol>")
def analyze(symbol):
    symbol=symbol.upper().strip()
    try:
        df=get_history(symbol,"10y")
        sig=swing_score(df)
        bt=backtest(df)
        price=sig["close"]; atrpct=sig["atr_pct"]/100
        stop_pct=max(.012,min(.06,atrpct*1.35))
        plan={"entry_low":round(price*.992,2),"entry_high":round(price*1.004,2),
              "stop":round(price*(1-stop_pct),2),"stop_pct":round(stop_pct*100,2),
              "target1":round(price*1.01,2),"target3":round(price*1.03,2),"target5":round(price*1.05,2),
              "loss_3m":round(3000000*stop_pct)}
        return jsonify({"symbol":symbol,"bars":len(df),"from":str(df.index[0].date()),"to":str(df.index[-1].date()),
                        "signal":sig,"backtest":bt,"plan":plan,"chart":chart_rows(df)})
    except Exception as e:return jsonify({"error":str(e)}),500

@app.route("/api/backtest/<symbol>")
def custom_backtest(symbol):
    try:
        df=get_history(symbol.upper().strip(),"10y")
        h=max(1,min(20,int(request.args.get("h",5))))
        tp=max(.002,min(.2,float(request.args.get("tp",3))/100))
        sl=max(.002,min(.2,float(request.args.get("sl",2))/100))
        return jsonify(backtest(df,h,tp,sl))
    except Exception as e:return jsonify({"error":str(e)}),500

@app.route("/api/scan", methods=["POST"])
def scan():
    data=request.get_json(force=True) or {}
    symbols=[str(s).upper().strip() for s in data.get("symbols",[]) if str(s).strip()][:120]
    if not symbols:
        return jsonify({"results":[],"failed":[],"market":simple_market_state()})

    results=[]; failed=[]
    try:
        bulk=yf.download(tickers=" ".join(symbols),period="2y",interval="1d",auto_adjust=False,
                         group_by="ticker",threads=True,progress=False)
    except Exception as e:
        return jsonify({"results":[],"failed":[{"symbol":"ALL","reason":str(e)}],"market":simple_market_state()}),500

    market=simple_market_state()
    for s in symbols:
        try:
            if len(symbols)==1:
                df=bulk.copy()
            else:
                if s not in bulk.columns.get_level_values(0):
                    raise ValueError("데이터 없음")
                df=bulk[s].copy()
            df=df.dropna(subset=["Open","High","Low","Close"])
            if len(df)<120: raise ValueError("일봉 120개 미만")
            r=swing_score(df)
            if market.get("state")=="조심":
                r["score"]=round(max(0,r["score"]-5),1)
                r["grade"]="S" if r["score"]>=82 else "A" if r["score"]>=72 else "B" if r["score"]>=58 else "C"
            r["bb_label"]=bollinger_label(r.get("bb_pos"))
            results.append({"symbol":s,**r})
        except Exception as e:
            failed.append({"symbol":s,"reason":str(e)})

    results.sort(key=lambda x:x.get("score",0), reverse=True)
    results=dedupe_results(results)
    return jsonify({"results":results,"failed":failed,"market":market})

@app.route("/api/detail/<symbol>")
def detail(symbol):
    symbol=symbol.upper().strip()
    try:
        df=get_history(symbol,"10y")
        sig=swing_score(df)
        hist=historical_setup_stats(df)
        btpy=run_backtesting_py(df)
        t=yf.Ticker(symbol)

        earnings={"status":"확인 불가","date":None,"days":None}
        try:
            cal=t.calendar
            dates=[]
            if isinstance(cal,dict):
                for k,v in cal.items():
                    if "Earnings" in str(k):
                        if isinstance(v,(list,tuple)): dates.extend(v)
                        else: dates.append(v)
            elif hasattr(cal,"index"):
                for idx in cal.index:
                    if "Earnings" in str(idx):
                        v=cal.loc[idx]
                        if hasattr(v,"tolist"): dates.extend(v.tolist())
            clean=[]
            for x in dates:
                try:
                    d=pd.to_datetime(x)
                    if pd.notna(d): clean.append(d)
                except: pass
            if clean:
                d=min(clean,key=lambda x:abs((x-pd.Timestamp.now(tz=x.tz if getattr(x,'tzinfo',None) else None)).days))
                days=(d.tz_localize(None).normalize()-pd.Timestamp.now().normalize()).days if getattr(d,'tzinfo',None) else (d.normalize()-pd.Timestamp.now().normalize()).days
                earnings={"status":"주의" if 0<=days<=7 else "여유","date":str(d.date()),"days":int(days)}
        except Exception:
            pass

        fx=None
        try:
            fxdf=yf.Ticker("KRW=X").history(period="5d")
            if fxdf is not None and not fxdf.empty: fx=float(fxdf["Close"].dropna().iloc[-1])
        except: pass

        return jsonify({"symbol":symbol,"signal":sig,"history_stats":hist,"backtesting_py":btpy,
                        "earnings":earnings,"market":simple_market_state(),"usdkrw":fx,
                        "bars":len(df),"from":str(df.index[0].date()),"to":str(df.index[-1].date())})
    except Exception as e:
        return jsonify({"error":str(e)}),500

if __name__=="__main__":
    app.run(host="127.0.0.1", port=8766, debug=False)
