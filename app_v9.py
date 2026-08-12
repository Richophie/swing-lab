import pandas as pd
import yfinance as yf
from backtesting import Backtest, Strategy
from flask import Response

from app_v8 import app, load_df, chart_payload, stats_dict
from app_v6 import trade_plan, historical_stats
from core_v2 import score_v2, point_in_time_levels


def _market_frame(period='10y'):
    spy=load_df('SPY',period)
    c=spy['Close'].astype(float)
    spy['M120']=c.rolling(120).mean(); spy['M200']=c.rolling(200).mean()
    spy['MARKET_OK']=(c>=spy['M120']) & (c>=spy['M200'])
    return spy[['MARKET_OK']]


def _bt_frame_v2(d, market):
    rows=[]
    for i in range(205,len(d)):
        sl=d.iloc[:i+1]
        try:
            sig=score_v2(sl, None); lv=point_in_time_levels(sl)
            rows.append((d.index[i],sig,lv))
        except Exception:
            continue
    f=d[['Open','High','Low','Close','Volume']].copy()
    f['SCORE']=0.0; f['ELIGIBLE']=0; f['TARGETP']=0.0; f['STOPP']=0.0; f['CONFIRM']=0
    for idx,sig,lv in rows:
        f.loc[idx,'SCORE']=sig['score']; f.loc[idx,'ELIGIBLE']=1 if sig['eligible'] else 0
        f.loc[idx,'TARGETP']=lv['target_pct']; f.loc[idx,'STOPP']=lv['stop_pct']; f.loc[idx,'CONFIRM']=sig['confirm_count']
    f=f.join(market,how='left'); f['MARKET_OK']=f['MARKET_OK'].ffill().fillna(False).astype(int)
    return f.dropna()


class SwingCoreV2(Strategy):
    hold_days=5
    min_score=72
    def init(self): self.entry_bar=-1
    def next(self):
        i=len(self.data.Close)-1
        if not self.position:
            if int(self.data.ELIGIBLE[-1]) and int(self.data.MARKET_OK[-1]) and float(self.data.SCORE[-1])>=self.min_score:
                px=float(self.data.Close[-1]); tp=float(self.data.TARGETP[-1]); sp=float(self.data.STOPP[-1])
                if tp>0 and sp>0:
                    stop=px*(1-sp); target=px*(1+tp)
                    if stop < px < target:
                        self.buy(sl=stop,tp=target); self.entry_bar=i
        elif self.entry_bar>=0 and i-self.entry_bar>=self.hold_days:
            self.position.close()


def run_bt_v2(d, market):
    f=_bt_frame_v2(d,market)
    if len(f)<260: raise ValueError('백테스트에 필요한 일봉이 부족합니다')
    bt=Backtest(f,SwingCoreV2,cash=10000,commission=.001,exclusive_orders=True,finalize_trades=True)
    return stats_dict(bt.run())


def detail_v2(symbol):
    try:
        s=symbol.upper().strip(); d=load_df(s,'10y')
        try:
            from app_v6 import market_live
            market=market_live(); state=market.get('state')
        except Exception:
            market={}; state=None
        sig=score_v2(d,state)
        plan=trade_plan(d); hist=historical_stats(d)
        fx=None
        try:
            q=yf.Ticker('KRW=X').history(period='5d'); fx=float(q['Close'].dropna().iloc[-1]) if not q.empty else None
        except Exception: pass
        return {'symbol':s,'signal':sig,'trade_plan':plan,'history_stats':hist,'usdkrw':fx,'market':market,
                'core_version':'2.0','note':'A/S 등급은 반전 확인 3개 이상 + 장기추세 방어 + 시장 조심 아님을 요구합니다.'}
    except Exception as e:
        return {'error':str(e)},400


def backtest_v2(symbol):
    try:
        s=symbol.upper().strip(); d=load_df(s,'10y'); m=_market_frame('10y')
        recent=d.tail(504); recent_m=m.reindex(recent.index).ffill()
        return {
            'symbol':s,'engine':'Backtesting.py','core_version':'2.0',
            'strategy':'전체 점수>=72 + 반전확인 3/4 + 120일선 하락/200일선 붕괴 방어 + 역사적 SPY 120·200일선 시장필터 + 시점별 구조적 목표/손절 + 최대 5거래일',
            'assumptions':{'commission_pct':0.1,'cash_usd':10000,'max_hold_days':5,'entry_execution':'신호 다음 거래일 시장가'},
            'full_10y':run_bt_v2(d,m),
            'recent_2y':run_bt_v2(recent,recent_m) if len(recent)>=260 else None,
            'warning':'현재 상장 종목의 과거 데이터 기반이라 상장폐지 종목을 포함한 완전한 point-in-time universe 백테스트는 아닙니다.'
        }
    except Exception as e:
        return {'error':str(e)},400

app.view_functions['detail']=detail_v2
app.view_functions['backtest']=backtest_v2


def index_v9():
    html=(app.static_folder and open(app.static_folder+'/v8.html',encoding='utf-8').read())
    html=html.replace('오늘의 스윙자리 v8','오늘의 스윙자리 v9')
    html=html.replace('PRO LIVE v8.0','PRO LIVE v9.0')
    html=html.replace('TECH CHART + BACKTEST','CONFIRMED CORE + BACKTEST')
    html=html.replace('현재 엔진 규칙을 과거 봉에 그대로 적용합니다.','현재 추천과 동일한 전체점수·반전확인·시장필터로 과거를 검증합니다.')
    return Response(html,mimetype='text/html')
app.view_functions['index']=index_v9

@app.route('/api/version-v9')
def version_v9():
    return {'version':'9.0','core':'2.0','changes':['full-score backtest alignment','reversal confirmation','trend gate','historical SPY regime filter','point-in-time target/stop']}
