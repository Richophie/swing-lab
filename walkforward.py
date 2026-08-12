from __future__ import annotations

import json
from pathlib import Path
import numpy as np

from market_data import load_price_history
from backtest_engine import simulate

STRATEGIES={'confirmed_pullback':'확인형 눌림반등','rsi2_trend_reversion':'RSI2 추세내 과매도','momentum_pullback':'모멘텀 눌림 지속','volatility_breakout':'변동성 수축 돌파'}
SYMBOLS=['AAPL','MSFT','AMZN','META','NVDA','GOOGL','JPM','XOM','JNJ','PG','HD','CAT','AMD','QCOM','CRM','DIS','NKE','F','PLD','PYPL']
OUT=Path(__file__).parent/'static'/'walkforward_report.json'


def fold_stats(trades):
    if not trades:return {'trades':0,'win_rate':None,'avg_trade':None,'profit_factor':None}
    r=np.array([t['ret'] for t in trades],dtype=float);pos=r[r>0].sum();neg=-r[r<0].sum()
    return {'trades':len(r),'win_rate':round(float((r>0).mean()*100),1),'avg_trade':round(float(r.mean()*100),3),'profit_factor':None if neg==0 else round(float(pos/neg),2)}


def validate(strategy_id):
    folds=[]
    for symbol in SYMBOLS:
        try:d=load_price_history(symbol,'10y').dropna()
        except Exception:continue
        n=len(d)
        for fold,(a,b) in enumerate(((.60,.70),(.70,.80),(.80,.90),(.90,1.0)),1):
            start=max(0,int(n*a)-220);end=int(n*b);ctx=d.iloc[start:end].copy();oos_start=int(n*a)-start;trades=[t for t in simulate(ctx,strategy_id) if t['entry_i']>=oos_start];st=fold_stats(trades);st.update({'symbol':symbol,'fold':fold});folds.append(st)
    valid=[f for f in folds if f['trades']];total=sum(f['trades'] for f in valid);avg=sum((f['avg_trade'] or 0)*f['trades'] for f in valid)/total if total else 0;win=sum((f['win_rate'] or 0)*f['trades'] for f in valid)/total if total else 0;rob=sum(1 for f in valid if (f['avg_trade'] or 0)>0)/len(valid) if valid else 0;passed=bool(total>=40 and avg>0 and win>=45 and rob>=.55)
    return {'strategy_id':strategy_id,'strategy_name':STRATEGIES[strategy_id],'oos_trades':total,'oos_win_rate':round(win,1),'oos_avg_trade':round(avg,3),'positive_fold_ratio':round(rob,3),'passed':passed,'folds':folds}


def main():
    rows=[validate(s) for s in STRATEGIES];payload={'engine':'Swing Lab clean core','method':'fixed-rule chronological OOS walk-forward; no test-window tuning','promotion_gate':'OOS trades >=40, avg trade >0, win rate >=45%, positive folds >=55%','strategies':rows};OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    for r in rows:print(r['strategy_name'],'PASS' if r['passed'] else 'FAIL',r['oos_trades'],r['oos_win_rate'],r['oos_avg_trade'])

if __name__=='__main__':main()
