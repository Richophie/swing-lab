from __future__ import annotations

from functools import lru_cache
from io import StringIO
import re
import requests
import numpy as np
import pandas as pd
import yfinance as yf

from config import MAIN_MIN_MARKET_CAP, MAIN_MIN_AVG_DAILY_VOLUME, MAIN_MIN_PRICE
from stock_names import canonical_symbol


def indicators(df: pd.DataFrame) -> pd.DataFrame:
    c=df['Close'].astype(float); h=df['High'].astype(float); l=df['Low'].astype(float)
    v=df['Volume'].astype(float) if 'Volume' in df else pd.Series(0,index=df.index)
    o=pd.DataFrame(index=df.index)
    o['close']=c; o['sma5']=c.rolling(5).mean(); o['sma20']=c.rolling(20).mean(); o['sma50']=c.rolling(50).mean(); o['sma60']=c.rolling(60).mean(); o['sma120']=c.rolling(120).mean(); o['sma200']=c.rolling(200).mean()
    d=c.diff(); g=d.clip(lower=0); loss=-d.clip(upper=0)
    ag=g.ewm(alpha=1/14,adjust=False,min_periods=14).mean(); al=loss.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    o['rsi']=100-100/(1+ag/al.replace(0,np.nan))
    mid=c.rolling(20).mean(); sd=c.rolling(20).std(ddof=0)
    o['bb_low']=mid-2*sd; o['bb_high']=mid+2*sd; o['bb_pos']=(c-o['bb_low'])/(o['bb_high']-o['bb_low'])
    e12=c.ewm(span=12,adjust=False).mean(); e26=c.ewm(span=26,adjust=False).mean(); macd=e12-e26
    o['macd_hist']=macd-macd.ewm(span=9,adjust=False).mean()
    prev=c.shift(1); tr=pd.concat([(h-l).abs(),(h-prev).abs(),(l-prev).abs()],axis=1).max(axis=1)
    o['atr14']=tr.rolling(14).mean(); o['vol20']=v.rolling(20).mean(); o['volume']=v
    return o


def wilder_rsi(series: pd.Series, period: int) -> pd.Series:
    d=series.astype(float).diff(); gain=d.clip(lower=0); loss=-d.clip(upper=0)
    ag=gain.ewm(alpha=1/period,adjust=False,min_periods=period).mean(); al=loss.ewm(alpha=1/period,adjust=False,min_periods=period).mean()
    rs=ag/al.replace(0,np.nan); out=100-100/(1+rs)
    return out.fillna(100.0)


def _normalize_history(d: pd.DataFrame) -> pd.DataFrame:
    if d is None or d.empty: raise ValueError('가격 데이터를 찾지 못했습니다')
    d=d.dropna(subset=['Open','High','Low','Close']).copy(); idx=pd.to_datetime(d.index)
    if getattr(idx,'tz',None) is not None: idx=idx.tz_localize(None)
    d.index=idx; return d


@lru_cache(maxsize=512)
def load_price_history(symbol: str, period: str='10y') -> pd.DataFrame:
    return _normalize_history(yf.Ticker(canonical_symbol(symbol)).history(period=period,auto_adjust=False))


def fresh_price_history(symbol: str, period: str='2y') -> pd.DataFrame:
    return _normalize_history(yf.Ticker(canonical_symbol(symbol)).history(period=period,auto_adjust=False))


def market_snapshot() -> dict:
    details={}; total=0; panic={'active':False,'triggered':False,'label':'평상시','message':'SPY RSI가 패닉 기준보다 높습니다.'}
    for symbol in ('SPY','QQQ'):
        try:
            d=fresh_price_history(symbol,'2y')
            if len(d)<205: raise ValueError('일봉 부족')
            ind=indicators(d);x=ind.iloc[-1];above120=bool(x['close']>x['sma120']);above200=bool(x['close']>x['sma200']);rsi=float(x['rsi'])
            score=int(above120)+int(above200)+int(rsi>45); total+=score; details[symbol]={'score':score,'rsi':round(rsi,1),'above120':above120,'above200':above200}
            if symbol=='SPY':
                bar=d.iloc[-1];low=float(bar['Low']);close=float(bar['Close']);rebound=(close/low-1)*100 if low>0 else 0
                active=rsi<=35;triggered=active and rebound>=.5
                panic={'active':active,'triggered':triggered,'rsi':round(rsi,1),'rebound_from_low_pct':round(rebound,2),'label':'패닉 반등 확인' if triggered else '패닉 구간 감시' if active else '평상시','message':f"SPY RSI {rsi:.1f} · 당일 저가 대비 {rebound:+.2f}%" + (' · 바닥 반등 조건 충족' if triggered else ' · 아직 반등 확인 전' if active else '')}
        except Exception as exc: details[symbol]={'error':str(exc),'score':0}
    usable=sum('error' not in x for x in details.values())
    if usable==0:return {'state':'확인 실패','score':0,'details':details,'brief':'시장 데이터를 불러오지 못했습니다.','action':'시장 상태를 다시 확인한 뒤 진입','panic_setup':panic}
    state='좋음' if total>=5 else '중립' if total>=3 else '조심'; reasons=[]
    for s,q in details.items(): reasons.append(f'{s} 확인 실패' if 'error' in q else f"{s} {'120·200일선 위' if q['above120'] and q['above200'] else '장기선 일부 이탈'} · RSI {q['rsi']}")
    action='눌림 후보를 관찰하되 추격매수는 자제' if state=='좋음' else '조건이 겹치는 종목만 선별' if state=='중립' else '현금 비중과 손절 기준을 보수적으로'
    return {'state':state,'score':total,'details':details,'brief':' / '.join(reasons),'action':action,'panic_setup':panic}


def clean_symbol(sym: str) -> bool:return bool(re.match(r'^[A-Z][A-Z0-9.\-]{0,7}$',str(sym or '').strip().upper()))


def security_name_ok(name: str) -> bool:
    n=str(name or '').lower();bad=[' warrant',' warrants',' units',' unit ',' rights',' right ',' preferred',' preference',' depositary shares',' notes due',' bond',' etf',' etn'];return not any(x in n for x in bad)


def load_us_universe() -> list[dict]:
    sources=[('https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt','nasdaq'),('https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt','other')];rows=[]
    for url,kind in sources:
        r=requests.get(url,timeout=25,headers={'User-Agent':'Mozilla/5.0'});r.raise_for_status();df=pd.read_csv(StringIO(r.text),sep='|')
        for _,row in df.iterrows():
            symbol=row.get('Symbol') if kind=='nasdaq' else row.get('ACT Symbol');name=str(row.get('Security Name',''))
            if str(row.get('ETF','N'))!='N' or str(row.get('Test Issue','N'))!='N':continue
            if kind=='other' and str(row.get('Exchange','')) not in {'A','N','P','Z'}:continue
            symbol=canonical_symbol(symbol)
            if clean_symbol(symbol) and security_name_ok(name):rows.append({'symbol':symbol,'security_name':name})
    dedup={r['symbol']:r for r in rows};return [dedup[k] for k in sorted(dedup)]


def prefilter_symbols(universe: list[dict], limit: int=500) -> list[str]:
    """Main universe: established, liquid US-listed operating companies.

    This intentionally avoids scanning thousands of micro/small caps. Selection is
    objective rather than hand-picked: market cap, price and sustained liquidity.
    """
    uset={x['symbol'] for x in universe};found=[]
    try:
        q=yf.EquityQuery('and',[
            yf.EquityQuery('eq',['region','us']),
            yf.EquityQuery('is-in',['exchange','NMS','NGM','NCM','NYQ','ASE']),
            yf.EquityQuery('gte',['intradayprice',MAIN_MIN_PRICE]),
            yf.EquityQuery('gte',['avgdailyvol3m',MAIN_MIN_AVG_DAILY_VOLUME]),
            yf.EquityQuery('gte',['intradaymarketcap',MAIN_MIN_MARKET_CAP]),
        ])
        offset=0
        while offset<5000 and len(found)<limit:
            resp=yf.screen(q,offset=offset,size=250,sortField='intradaymarketcap',sortAsc=False);quotes=resp.get('quotes',[]) if isinstance(resp,dict) else []
            if not quotes:break
            for x in quotes:
                s=canonical_symbol(x.get('symbol',''))
                if s in uset:found.append(s)
            offset+=len(quotes)
            if len(quotes)<250:break
    except Exception:pass
    # Recognizable liquid names retained as a resilient fallback if screener is rate-limited.
    fallback=['AAPL','MSFT','NVDA','AMZN','META','GOOGL','AVGO','TSLA','JPM','V','WMT','MA','NFLX','COST','HD','PG','JNJ','BAC','CRM','AMD','PLTR','CSCO','CVX','IBM','GE','CAT','KO','PEP','DIS','QCOM','MU','UBER','SOFI','RBLX','COIN','SHOP','PYPL','NKE','F','GM','O','PLD','DOC','HST','LLY','UNH','XOM','RTX','LMT','AMT']
    if len(found)<100:found.extend([s for s in fallback if s in uset])
    return list(dict.fromkeys(found))[:limit]
