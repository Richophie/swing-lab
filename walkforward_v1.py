"""Out-of-sample / walk-forward validation for Swing Lab Core 4.0.
This does NOT tune parameters on the test window. It measures whether each fixed
playbook remains viable across unseen chronological folds.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
from app_v8 import load_df
from app_v12 import _simulate

STRATEGIES={
 'confirmed_pullback':'확인형 눌림반등',
 'rsi2_trend_reversion':'RSI2 추세내 과매도',
 'momentum_pullback':'모멘텀 눌림 지속',
 'volatility_breakout':'변동성 수축 돌파',
}
DEFAULT_SYMBOLS=['AAPL','MSFT','AMZN','META','NVDA','GOOGL','JPM','XOM','JNJ','PG','HD','CAT','AMD','QCOM','CRM','DIS','NKE','F','PLD','PYPL']
OUT=Path(__file__).parent/'static'/'walkforward_report.json'


def fold_stats(trades):
    if not trades: return {'trades':0,'win_rate':None,'avg_trade':None,'profit_factor':None,'compound':0}
    r=np.array([t['ret'] for t in trades],dtype=float); pos=r[r>0].sum(); neg=-r[r<0].sum()
    return {'trades':len(r),'win_rate':round(float((r>0).mean()*100),1),'avg_trade':round(float(r.mean()*100),3),'profit_factor':None if neg==0 else round(float(pos/neg),2),'compound':round(float((np.prod(1+r)-1)*100),2)}


def validate_strategy(strategy_id,symbols=DEFAULT_SYMBOLS):
    folds=[]
    for symbol in symbols:
        try: d=load_df(symbol,'10y').dropna()
        except Exception: continue
        n=len(d)
        # Chronological OOS folds: 60% train context + successive 10% unseen windows.
        cuts=[(.60,.70),(.70,.80),(.80,.90),(.90,1.00)]
        for fi,(a,b) in enumerate(cuts,1):
            start=max(0,int(n*a)-220); end=int(n*b); context=d.iloc[start:end].copy(); oos_start=int(n*a)-start
            ts=_simulate(context,strategy_id)
            oos=[t for t in ts if t['entry_i']>=oos_start]
            st=fold_stats(oos); st.update({'symbol':symbol,'fold':fi}); folds.append(st)
    valid=[f for f in folds if f['trades']>0]
    total=sum(f['trades'] for f in valid)
    weighted_avg=sum((f['avg_trade'] or 0)*f['trades'] for f in valid)/total if total else 0
    weighted_win=sum((f['win_rate'] or 0)*f['trades'] for f in valid)/total if total else 0
    pf_num=sum(max((f['compound'] or 0),0) for f in valid); pf_den=sum(max(-(f['compound'] or 0),0) for f in valid)
    positive_folds=sum(1 for f in valid if (f['avg_trade'] or 0)>0)
    robustness=positive_folds/len(valid) if valid else 0
    # Conservative promotion gate: enough OOS trades, positive expectancy and majority-positive folds.
    passed=bool(total>=40 and weighted_avg>0 and weighted_win>=45 and robustness>=.55)
    return {'strategy_id':strategy_id,'strategy_name':STRATEGIES[strategy_id],'oos_trades':total,'oos_win_rate':round(weighted_win,1),'oos_avg_trade':round(weighted_avg,3),'positive_fold_ratio':round(robustness,3),'passed':passed,'folds':folds}


def main():
    reports=[validate_strategy(s) for s in STRATEGIES]
    payload={'engine':'Swing Lab Core 4.0','method':'fixed-rule chronological OOS walk-forward; no test-window tuning','promotion_gate':'OOS trades >=40, avg trade >0, win rate >=45%, positive folds >=55%','strategies':reports}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    for r in reports: print(r['strategy_name'], 'PASS' if r['passed'] else 'FAIL', r['oos_trades'], r['oos_win_rate'], r['oos_avg_trade'], r['positive_fold_ratio'])

if __name__=='__main__': main()
