from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import pandas as pd
import yfinance as yf

ROOT=Path(__file__).parent;SCAN_FILE=ROOT/'static'/'latest_scan.json';JOURNAL_FILE=ROOT/'static'/'trade_history.json';NY=ZoneInfo('America/New_York');CLOSED={'SUCCESS','STOP','EXPIRED_GAIN','EXPIRED_LOSS','EXPIRED_FLAT'}


def load(path,default):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception:return default

def save(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

def market_date(value):
    try:
        d=datetime.fromisoformat(value.replace('Z','+00:00'));d=d if d.tzinfo else d.replace(tzinfo=timezone.utc);return d.astimezone(NY).date().isoformat()
    except Exception:return datetime.now(timezone.utc).astimezone(NY).date().isoformat()


def freeze_signal(row,sig,plan,at,day):
    td=plan.get('target_days') or {};sid=sig['strategy_id']
    return {'signal_key':f"{row['symbol']}|{sid}",'symbol':row['symbol'],'name_ko':row.get('name_ko'),'security_name':row.get('security_name'),'grade':'S','score':sig.get('elite_score',sig.get('strategy_score',row.get('score'))),'raw_strategy_score':sig.get('strategy_score'),'strategy_id':sid,'strategy_name':sig.get('strategy_name'),'strategy_reason':sig.get('evidence') or sig.get('why'),'selection_reason':sig.get('selection_reason'),'experimental':bool(sig.get('experimental')),'recommended_at':at,'market_date':day,'rsi':row.get('rsi'),'d120':row.get('d120'),'bb_pos':row.get('bb_pos'),'sparkline':row.get('sparkline') or [],'bb_high_spark':row.get('bb_high_spark') or [],'bb_low_spark':row.get('bb_low_spark') or [],'entry_low':plan.get('entry_low'),'entry_high':plan.get('entry_high'),'target':plan.get('target'),'stop':plan.get('stop'),'target_pct':plan.get('target_pct'),'stop_pct':plan.get('stop_pct'),'target_days_low':int(td.get('days_low') or plan.get('days_min') or 1),'target_days_high':int(td.get('days_high') or plan.get('days_max') or 5),'target_reason':plan.get('target_reason'),'stop_reason':plan.get('stop_reason'),'risk_reward':plan.get('risk_reward'),'status':'진행중','status_code':'OPEN','outcome_at':None,'outcome_price':None,'outcome_return_pct':None,'outcome_note':'추천 다음 거래일부터 판정합니다.','bars_observed':0,'best_high':None,'worst_low':None}


def _derived_key(x):return x.get('signal_key') or (f"{x.get('symbol')}|{x.get('strategy_id')}" if x.get('symbol') and x.get('strategy_id') else None)


def append_current_scan(scan,journal):
    at=scan.get('scanned_at') or datetime.now(timezone.utc).isoformat(timespec='seconds');day_id=market_date(at);days=journal.setdefault('days',[]);day=next((d for d in days if d.get('date')==day_id),None)
    if day is None:day={'date':day_id,'created_at':at,'updated_at':at,'items':[]};days.append(day)
    existing={_derived_key(x) for x in day.get('items',[]) if _derived_key(x)}
    for row in scan.get('results') or []:
        plans=row.get('strategy_trade_plans') or {}
        for sig in row.get('strategy_signals') or []:
            experimental=bool(sig.get('experimental'));qualified=experimental or bool(sig.get('elite_pass'))
            if not qualified:continue
            sid=sig.get('strategy_id');key=f"{row.get('symbol')}|{sid}";plan=plans.get(sid)
            if row.get('symbol') and sid and plan and key not in existing:day['items'].append(freeze_signal(row,sig,plan,at,day_id));existing.add(key)
    day['updated_at']=at;days.sort(key=lambda x:x.get('date',''),reverse=True)


def _entry_center_from_legacy(item):
    target=item.get('target');stop=item.get('stop');tp=item.get('target_pct');sp=item.get('stop_pct');rr=item.get('risk_reward')
    try:
        if target is not None and tp is not None and float(tp)>0:return float(target)/(1+float(tp)/100),'기존 목표수익률 역산'
    except Exception:pass
    try:
        if stop is not None and sp is not None and 0<float(sp)<100:return float(stop)/(1-float(sp)/100),'기존 손절률 역산'
    except Exception:pass
    try:
        if target is not None and stop is not None and rr is not None and float(rr)>0:return (float(target)+float(rr)*float(stop))/(1+float(rr)),'기존 손익비 역산'
    except Exception:pass
    try:
        spark=[float(v) for v in item.get('sparkline') or [] if v is not None]
        if spark:return spark[-1],'추천 당시 마지막 종가'
    except Exception:pass
    return None,None


def repair_legacy_entries(journal):
    repaired=0
    for day in journal.get('days',[]):
        for item in day.get('items',[]):
            item['signal_key']=_derived_key(item)
            if item.get('entry_low') is not None and item.get('entry_high') is not None:continue
            center,basis=_entry_center_from_legacy(item)
            if center is None or center<=0:continue
            target=item.get('target');stop=item.get('stop')
            if target is not None and center>=float(target):continue
            if stop is not None and center<=float(stop):continue
            item['entry_low']=round(center*.9965,2);item['entry_high']=round(center*1.0035,2)
            if target is not None:item['target_pct']=round((float(target)/center-1)*100,2)
            if stop is not None:item['stop_pct']=round((center-float(stop))/center*100,2)
            item['entry_repaired']=True;item['entry_repair_basis']=basis+' 기준 ±0.35% 복원';repaired+=1
    return repaired


def fetch_frames(symbols):
    if not symbols:return None
    try:return yf.download(' '.join(symbols),period='3mo',interval='1d',auto_adjust=False,group_by='ticker',threads=True,progress=False,timeout=30)
    except Exception:return None

def frame_for(bulk,symbol,count):
    try:
        d=bulk.copy() if count==1 else bulk[symbol].copy();d=d.dropna(subset=['High','Low','Close']).copy();idx=pd.to_datetime(d.index);d.index=idx.tz_localize(None) if getattr(idx,'tz',None) is not None else idx;return d
    except Exception:return pd.DataFrame()
def entry_price(item):
    vals=[float(v) for v in (item.get('entry_low'),item.get('entry_high')) if v is not None];return sum(vals)/len(vals) if vals else None

def finish(item,code,label,when,price,note):
    entry=entry_price(item);ret=((float(price)/entry)-1)*100 if entry and price is not None else None;item.update({'status':label,'status_code':code,'outcome_at':when,'outcome_price':round(float(price),4),'outcome_return_pct':round(ret,2) if ret is not None else None,'outcome_note':note})

def evaluate(item,d):
    if item.get('status_code') in CLOSED or d.empty:return
    target,stop=item.get('target'),item.get('stop');entry=entry_price(item)
    if target is None or stop is None or entry is None:return
    rec=pd.Timestamp(item['market_date']);future=d[d.index.normalize()>rec.normalize()];limit=max(1,int(item.get('target_days_high') or 5));window=future.iloc[:limit];item['bars_observed']=len(window)
    if len(window):item['best_high']=round(float(window['High'].max()),4);item['worst_low']=round(float(window['Low'].min()),4)
    for idx,row in window.iterrows():
        hit_target=float(row['High'])>=float(target);hit_stop=float(row['Low'])<=float(stop)
        if hit_stop:finish(item,'STOP','손절',idx.date().isoformat(),stop,'손절가를 먼저 터치했거나 같은 일봉에서 목표/손절을 모두 터치했습니다.');return
        if hit_target:finish(item,'SUCCESS','성공',idx.date().isoformat(),target,'목표기간 안에 목표가를 달성했습니다.');return
    if len(future)>=limit and len(window):
        close=float(window.iloc[-1]['Close']);ret=((close/entry)-1)*100;code='EXPIRED_GAIN' if ret>.05 else 'EXPIRED_LOSS' if ret<-.05 else 'EXPIRED_FLAT';finish(item,code,'목표미달',window.index[-1].date().isoformat(),close,'목표기간 종료 종가 기준 수익률입니다.')


def summarize(journal):
    items=[x for d in journal.get('days',[]) for x in d.get('items',[])];closed=[x for x in items if x.get('status_code') in CLOSED];returns=[float(x['outcome_return_pct']) for x in closed if x.get('outcome_return_pct') is not None];by={}
    for x in closed:
        sid=x.get('strategy_id');b=by.setdefault(sid,{'closed':0,'success':0,'stop':0,'target_miss':0,'returns':[]});b['closed']+=1;b['success']+=x.get('status_code')=='SUCCESS';b['stop']+=x.get('status_code')=='STOP';b['target_miss']+=str(x.get('status_code','')).startswith('EXPIRED')
        if x.get('outcome_return_pct') is not None:b['returns'].append(float(x['outcome_return_pct']))
    for b in by.values():b['success_rate_pct']=round(b['success']/b['closed']*100,1) if b['closed'] else None;b['avg_return_pct']=round(sum(b['returns'])/len(b['returns']),2) if b['returns'] else None;b.pop('returns',None)
    return {'total_signals':len(items),'closed_signals':len(closed),'success':sum(x.get('status_code')=='SUCCESS' for x in closed),'stop':sum(x.get('status_code')=='STOP' for x in closed),'target_miss':sum(str(x.get('status_code','')).startswith('EXPIRED') for x in closed),'avg_outcome_return_pct':round(sum(returns)/len(returns),2) if returns else None,'by_strategy':by}


def main():
    scan=load(SCAN_FILE,{});journal=load(JOURNAL_FILE,{'version':'4.1','days':[]});repaired=repair_legacy_entries(journal);append_current_scan(scan,journal);open_items=[x for d in journal.get('days',[]) for x in d.get('items',[]) if x.get('status_code') not in CLOSED];symbols=sorted({x['symbol'] for x in open_items if x.get('symbol')});bulk=fetch_frames(symbols)
    if bulk is not None:
        for item in open_items:evaluate(item,frame_for(bulk,item['symbol'],len(symbols)))
    journal['version']='4.1';journal['updated_at']=datetime.now(timezone.utc).isoformat(timespec='seconds');journal['summary']=summarize(journal);journal['legacy_entries_repaired']=repaired;save(JOURNAL_FILE,journal);print('saved journal',journal['summary'],'repaired',repaired)

if __name__=='__main__':main()
