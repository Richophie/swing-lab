from datetime import datetime
import pandas as pd
import yfinance as yf
from backtesting import Backtest, Strategy

from app_v7 import app
from app_v6 import indicators, trade_plan


def load_df(symbol, period='10y'):
    d=yf.Ticker(symbol).history(period=period,auto_adjust=False)
    if d is None or d.empty: raise ValueError('가격 데이터를 찾지 못했습니다')
    d=d.dropna(subset=['Open','High','Low','Close']).copy()
    d.index=pd.to_datetime(d.index)
    if getattr(d.index,'tz',None) is not None: d.index=d.index.tz_localize(None)
    return d


def chart_payload(symbol, days=180):
    d=load_df(symbol,'2y'); ind=indicators(d); p=trade_plan(d)
    x=d.join(ind[['sma120','rsi','bb_low','bb_high']],how='left').tail(days)
    rows=[]
    for idx,r in x.iterrows():
        rows.append({'date':idx.strftime('%Y-%m-%d'),'close':round(float(r['Close']),2),'sma120':None if pd.isna(r['sma120']) else round(float(r['sma120']),2),'bb_low':None if pd.isna(r['bb_low']) else round(float(r['bb_low']),2),'bb_high':None if pd.isna(r['bb_high']) else round(float(r['bb_high']),2),'rsi':None if pd.isna(r['rsi']) else round(float(r['rsi']),1)})
    return {'symbol':symbol,'series':rows,'trade_plan':p}


def bt_frame(d):
    i=indicators(d); o=d[['Open','High','Low','Close','Volume']].copy(); o['RSI']=i['rsi']; o['BBPOS']=i['bb_pos']; o['SMA120']=i['sma120']; o['ATR14']=i['atr14']; o['MACDH']=i['macd_hist']; return o.dropna()


class SwingPullback(Strategy):
    hold_days=5
    def init(self): self.entry_bar=-1
    def next(self):
        i=len(self.data.Close)-1; price=float(self.data.Close[-1]); rsi=float(self.data.RSI[-1]); bb=float(self.data.BBPOS[-1]); s120=float(self.data.SMA120[-1]); atr=float(self.data.ATR14[-1]); d120=price/s120-1 if s120 else 99
        setup=(28<=rsi<=45 and bb<=.32 and abs(d120)<=.035)
        if not self.position and setup:
            stop=max(price*.94,min(price*.988,min(price-atr*1.20,s120-atr*.15))); target=min(price*1.08,max(price*1.01,price+atr*1.65))
            if stop<price<target: self.buy(sl=stop,tp=target); self.entry_bar=i
        elif self.position and self.entry_bar>=0 and i-self.entry_bar>=self.hold_days: self.position.close()


def stats_dict(s):
    def g(k,d=0):
        v=s.get(k,d)
        try:
            if pd.isna(v): return d
        except: pass
        return v
    return {'return_pct':round(float(g('Return [%]')),2),'buy_hold_pct':round(float(g('Buy & Hold Return [%]')),2),'win_rate':round(float(g('Win Rate [%]')),1),'trades':int(g('# Trades')),'max_drawdown':round(float(g('Max. Drawdown [%]')),2),'profit_factor':None if g('Profit Factor',None) is None else round(float(g('Profit Factor')),2),'sharpe':None if g('Sharpe Ratio',None) is None else round(float(g('Sharpe Ratio')),2),'avg_trade':round(float(g('Avg. Trade [%]')),2),'best_trade':round(float(g('Best Trade [%]')),2),'worst_trade':round(float(g('Worst Trade [%]')),2),'exposure':round(float(g('Exposure Time [%]')),1)}


def run_bt(d):
    f=bt_frame(d)
    if len(f)<260: raise ValueError('백테스트에 필요한 일봉이 부족합니다')
    return stats_dict(Backtest(f,SwingPullback,cash=10000,commission=.001,exclusive_orders=True,finalize_trades=True).run())


@app.route('/api/chart/<symbol>')
def chart(symbol):
    try:return chart_payload(symbol.upper().strip())
    except Exception as e:return {'error':str(e)},400


@app.route('/api/backtest/<symbol>')
def backtest(symbol):
    try:
        s=symbol.upper().strip(); d=load_df(s,'10y'); recent=d.tail(504)
        return {'symbol':s,'engine':'Backtesting.py','strategy':'RSI 28~45 + 볼린저 하단권 + 120일선 ±3.5% / ATR 목표·손절 / 최대 5거래일','assumptions':{'commission_pct':0.1,'cash_usd':10000,'max_hold_days':5},'full_10y':run_bt(d),'recent_2y':run_bt(recent) if len(recent)>=260 else None}
    except Exception as e:return {'error':str(e)},400


def index_v8(): return app.send_static_file('v8.html')
app.view_functions['index']=index_v8

@app.route('/api/version-v8')
def version_v8(): return {'version':'8.0','features':['chart','rsi','bollinger','sma120','buy-target-stop','backtest']}
