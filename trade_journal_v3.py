from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import pandas as pd
import yfinance as yf

ROOT=Path(__file__).parent
SCAN_FILE=ROOT/'static'/'latest_scan.json'
JOURNAL_FILE=ROOT/'static'/'trade_history.json'
NY=ZoneInfo('America/New_York')
CLOSED={'SUCCESS','STOP','EXPIRED_GAIN','EXPIRED_LOSS','EXPIRED_FLAT'}


def load(path,default):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception:return default

def save(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def market_date(v):
    try:
        d=datetime.fromisoformat(v.replace('Z','+00:00'));d=d if d.tzinfo else d.replace(tzinfo=timezone.utc);return d.astimezone(NY).date().isoformat()
    except Exception:return datetime.now(timezone.utc).astimezone(NY).date().isoformat()

def frozen(row,sig,plan,at,day):
    td=plan.get('target_days') or {};sid=sig.get('strategy_id') or row.get('strategy_id');name=sig.get('strategy_name') or row.get('strategy_name')
    return {'signal_key':f"{row.get('symbol')}|{sid}",'symbol':row.get('symbol'),'grade':'S','score':sig.get('strategy_score',row.get('score')),'strategy_id':sid,'strategy_name':name,'strategy_reason':sig.get('evidence') or row.get('strategy_reason'),'recommended_at':at,'market_date':day,'rsi':row.get('rsi'),'d120':row.get('d120'),'bb_pos':row.get('bb_pos'),'sparkline':row.get('sparkline') or [],'entry_low':plan.get('entry_low'),'entry_high':plan.get('entry_high'),'target':plan.get('target'),'stop':plan.get('stop'),'target_pct':plan.get('target_pct'),'stop_pct':plan.get('stop_pct'),'target_days_low':int(td.get('days_low') or plan.get('days_min') or 1),'target_days_high':int(td.get('days_high') or plan.get('days_max') or 5),'target_reason':plan.get('target_reason'),'stop_reason':plan.get('stop_reason'),'risk_reward':plan.get('risk_reward'),'status':'진행중','status_code':'OPEN','outcome_at':None,'outcome_price':None,'outcome_return_pct':None,'outcome_note':'추천 다음 거래일부터 판정합니다.','bars_observed':0,'best_high':None,'worst_low':None}

def append_today(scan,journal):
    at=scan.get('scanned_at') or datetime.now(timezone.utc).isoformat(timespec='seconds');day_id=market_date(at);days=journal.setdefault('days',[]);day=next((d for d in days if d.get('date')==day_id),None)
    if day is None:day={'date':day_id,'created_at':at,'updated_at':at,'items':[]};days.append(day)
    existing={x.get('signal_key') or f"{x.get('symbol')}|{x.get('strategy_id')}" for x in day.get('items',[])}
    for row in scan.get('results') or []:
        if row.get('grade')!='S' or not row.get('eligible',True):continue
        signals=row.get('strategy_signals') or [{'strategy_id':row.get('strategy_id'),'strategy_name':row.get('strategy_name'),'strategy_score':row.get('score'),'evidence':row.get('strategy_reason')}]
        plans=row.get('strategy_trade_plans') or {}
        for sig in signals:
            sid=sig.get('strategy_id');key=f"{row.get('symbol')}|{sid}";plan=plans.get(sid) or row.get('trade_plan') or {}
            if row.get('symbol') and sid and key not in existing:day['items'].append(frozen(row,sig,plan,at,day_id));existing.add(key)
    day['updated_at']=at;days.sort(key=lambda x:x.get('date',''),reverse=True)

def fetch_frames(symbols):
    if not symbols:return None
    try:return yf.download(' '.join(symbols),period='3mo',interval='1d',auto_adjust=False,group_by='ticker',threads=True,progress=False,timeout=30)
    except Exception:return None

def frame(bulk,s,count):
    try:
        d=bulk.copy() if count==1 else bulk[s].copy();d=d.dropna(subset=['High','Low','Close']).copy();idx=pd.to_datetime(d.index);d.index=idx.tz_localize(None) if getattr(idx,'tz',None) is not None else idx;return d
    except Exception:return pd.DataFrame()
def entry(item):
    a=[float(v) for v in [item.get('entry_low'),item.get('entry_high')] if v is not None];return sum(a)/len(a) if a else None
def finish(x,code,label,when,price,note):
    e=entry(x);ret=((float(price)/e)-1)*100 if e and price is not None else None;x.update({'status':label,'status_code':code,'outcome_at':when,'outcome_price':round(float(price),4),'outcome_return_pct':round(ret,2) if ret is not None else None,'outcome_note':note})
def evaluate(x,d):
    if x.get('status_code') in CLOSED or d.empty:return
    target,stop=x.get('target'),x.get('stop')
    if target is None or stop is None:return
    rec=pd.Timestamp(x['market_date']);future=d[d.index.normalize()>rec.normalize()];maxd=max(1,int(x.get('target_days_high') or 5));w=future.iloc[:maxd];x['bars_observed']=len(w)
    if len(w):x['best_high']=round(float(w['High'].max()),4);x['worst_low']=round(float(w['Low'].min()),4)
    for idx,r in w.iterrows():
        ht=float(r['High'])>=float(target);hs=float(r['Low'])<=float(stop)
        if hs:finish(x,'STOP','손절',idx.date().isoformat(),stop,'목표가보다 손절가를 먼저 터치했거나 같은 일봉에서 둘 다 터치했습니다.');return
        if ht:finish(x,'SUCCESS','성공',idx.date().isoformat(),target,'목표기간 안에 목표가를 달성했습니다.');return
    if len(future)>=maxd and len(w):
        close=float(w.iloc[-1]['Close']);e=entry(x);ret=((close/e)-1)*100 if e else 0;code='EXPIRED_GAIN' if ret>.05 else 'EXPIRED_LOSS' if ret<-.05 else 'EXPIRED_FLAT';finish(x,code,'목표미달',w.index[-1].date().isoformat(),close,'목표기간 종료 종가 기준 수익률입니다.')
def summarize(j):
    items=[x for d in j.get('days',[]) for x in d.get('items',[])];closed=[x for x in items if x.get('status_code') in CLOSED];rets=[float(x['outcome_return_pct']) for x in closed if x.get('outcome_return_pct') is not None]
    by={}
    for x in closed:
        sid=x.get('strategy_id');b=by.setdefault(sid,{'closed':0,'success':0,'stop':0,'target_miss':0,'returns':[]});b['closed']+=1;b['success']+=x.get('status_code')=='SUCCESS';b['stop']+=x.get('status_code')=='STOP';b['target_miss']+=str(x.get('status_code','')).startswith('EXPIRED');
        if x.get('outcome_return_pct') is not None:b['returns'].append(float(x['outcome_return_pct']))
    for b in by.values():b['success_rate_pct']=round(b['success']/b['closed']*100,1) if b['closed'] else None;b['avg_return_pct']=round(sum(b['returns'])/len(b['returns']),2) if b['returns'] else None;b.pop('returns',None)
    return {'total_signals':len(items),'closed_signals':len(closed),'success':sum(x.get('status_code')=='SUCCESS' for x in closed),'stop':sum(x.get('status_code')=='STOP' for x in closed),'target_miss':sum(str(x.get('status_code','')).startswith('EXPIRED') for x in closed),'avg_outcome_return_pct':round(sum(rets)/len(rets),2) if rets else None,'by_strategy':by}
def main():
    scan=load(SCAN_FILE,{});j=load(JOURNAL_FILE,{'version':'3.0','days':[]});append_today(scan,j);open_items=[x for d in j.get('days',[]) for x in d.get('items',[]) if x.get('status_code') not in CLOSED];syms=sorted({x['symbol'] for x in open_items if x.get('symbol')});bulk=fetch_frames(syms)
    if bulk is not None:
        for x in open_items:evaluate(x,frame(bulk,x['symbol'],len(syms)))
    j['version']='3.0';j['updated_at']=datetime.now(timezone.utc).isoformat(timespec='seconds');j['summary']=summarize(j);save(JOURNAL_FILE,j);print('saved journal v3',j['summary'])
if __name__=='__main__':main()
