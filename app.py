from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import hashlib
import json
import pandas as pd
import yfinance as yf
from flask import Flask, jsonify, request, send_from_directory

from config import APP_VERSION, CORE_VERSION, PUBLIC_STRATEGIES, S_THRESHOLD
from market_data import fresh_price_history, indicators, market_snapshot
from strategy_engine import evaluate_strategies, trade_plan
from backtest_engine import run_backtest
from stock_names import korean_name

ROOT=Path(__file__).parent;STATIC=ROOT/'static';SCAN_FILE=STATIC/'latest_scan.json';HISTORY_FILE=STATIC/'trade_history.json';SIGNAL_EVENTS_FILE=STATIC/'signal_events.json';FX_FILE=STATIC/'fx_cache.json';PAPER_CLIENT_DIR=ROOT/'runtime'/'paper_clients';app=Flask(__name__,static_folder='static')

def load_json(path, default):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception:return default

def normalize_plan(plan):
    p=dict(plan or {})
    for key in ('entry_low','entry_high','target','stop'):
        try:p[key]=float(p[key]) if p.get(key) is not None else None
        except Exception:p[key]=None
    return p

def public_row(raw):
    row=dict(raw);signals=[s for s in row.get('strategy_signals',[]) if s.get('strategy_id') in PUBLIC_STRATEGIES and float(s.get('strategy_score',0))>=S_THRESHOLD]
    if not signals:return None
    signals.sort(key=lambda x:(bool(x.get('elite_pass')),float(x.get('elite_score',x.get('strategy_score',0)))),reverse=True);best=signals[0];plans=row.get('strategy_trade_plans') or {};row['strategy_signals']=signals;row['strategy_id']=best['strategy_id'];row['strategy_name']=best['strategy_name'];row['strategy_reason']=best.get('evidence') or best.get('why');row['selection_reason']=best.get('selection_reason');row['score']=float(best.get('elite_score',best.get('strategy_score',0)));row['trade_plan']=normalize_plan(plans.get(best['strategy_id']) or row.get('trade_plan'));row['aggregate_eligible']=any(bool(s.get('elite_pass')) for s in signals);row['name_ko']=row.get('name_ko') or korean_name(row.get('symbol'),row.get('security_name'));return row

def _valid_fx(v):
    try:return 500<float(v)<3000
    except Exception:return False

def usdkrw_rate():
    cached=load_json(FX_FILE,{});cached_value=cached.get('usdkrw')
    if _valid_fx(cached_value):return float(cached_value)
    value=None
    try:d=fresh_price_history('KRW=X','5d');value=float(d['Close'].dropna().iloc[-1])
    except Exception:
        try:
            d=yf.download('KRW=X',period='5d',interval='1d',auto_adjust=False,progress=False,timeout=8)
            if not d.empty:value=float(d['Close'].dropna().iloc[-1])
        except Exception:pass
    if _valid_fx(value):
        value=round(value,2)
        try:FX_FILE.write_text(json.dumps({'usdkrw':value},ensure_ascii=False),encoding='utf-8')
        except Exception:pass
        return value
    return None

def _find_scan(symbol, strategy_id=None):
    data=load_json(SCAN_FILE,{'results':[]})
    for raw in data.get('results') or []:
        if str(raw.get('symbol','')).upper()!=symbol:continue
        signals=raw.get('strategy_signals') or [];sig=next((s for s in signals if s.get('strategy_id')==strategy_id),None) if strategy_id else None
        if sig is None:
            pub=[s for s in signals if s.get('strategy_id') in PUBLIC_STRATEGIES];pub.sort(key=lambda s:(bool(s.get('elite_pass')),float(s.get('elite_score',s.get('strategy_score',0)))),reverse=True);sig=pub[0] if pub else (signals[0] if signals else None)
        return raw,sig
    return None,None

def _find_history(symbol, strategy_id=None):
    data=load_json(HISTORY_FILE,{'days':[]})
    for day in data.get('days') or []:
        for item in day.get('items') or []:
            if str(item.get('symbol','')).upper()!=symbol:continue
            if strategy_id and item.get('strategy_id')!=strategy_id:continue
            return item
    return None

def _open_history_index():
    data=load_json(HISTORY_FILE,{'days':[]});out={}
    for day in reversed(data.get('days') or []):
        for item in day.get('items') or []:
            if item.get('status_code')!='OPEN':continue
            key=f"{str(item.get('symbol','')).upper()}|{item.get('strategy_id')}"
            if item.get('symbol') and item.get('strategy_id') and key not in out:out[key]=item
    return out

def _lifecycle(item,current_price):
    if not item:return None
    lo=item.get('entry_low');hi=item.get('entry_high');target=item.get('target');stop=item.get('stop')
    try:now=float(current_price)
    except Exception:now=None
    try:lo=float(lo);hi=float(hi)
    except Exception:lo=hi=None
    try:target=float(target)
    except Exception:target=None
    try:stop=float(stop)
    except Exception:stop=None
    ref=(lo+hi)/2 if lo is not None and hi is not None else None
    ret=round((now/ref-1)*100,2) if now is not None and ref else None
    if now is None:state,label,note='TRACKING','추천 유지','최초 추천가 기준으로 추적 중'
    elif target is not None and now>=target:state,label,note='TARGET_NEAR','목표 도달권','최초 추천 목표가에 도달한 가격대'
    elif stop is not None and now<=stop:state,label,note='STOP_ZONE','손절 구간','최초 추천 손절가 이하'
    elif lo is not None and hi is not None and lo<=now<=hi:state,label,note='ENTRY','진입구간','최초 추천 BUY 구간 안에 있음'
    elif hi is not None and now>hi:state,label,note='ENTRY_MISSED','진입가 이탈','최초 추천 BUY 상단을 넘어 신규 추격 진입은 주의'
    elif lo is not None and now<lo:state,label,note='BELOW_ENTRY','진입가 하회','최초 추천 BUY 하단보다 낮아져 재확인 필요'
    else:state,label,note='TRACKING','추천 유지','최초 추천가 기준으로 추적 중'
    return {'state':state,'label':label,'note':note,'recommended_at':item.get('recommended_at'),'market_date':item.get('market_date'),'entry_low':lo,'entry_high':hi,'target':target,'stop':stop,'current_return_pct':ret,'bars_observed':item.get('bars_observed',0),'best_high':item.get('best_high'),'worst_low':item.get('worst_low')}

def _plan_from_history(item):
    if not item:return {}
    return normalize_plan({'entry_low':item.get('entry_low'),'entry_high':item.get('entry_high'),'target':item.get('target'),'stop':item.get('stop'),'target_pct':item.get('target_pct'),'stop_pct':item.get('stop_pct'),'risk_reward':item.get('risk_reward'),'days_min':item.get('target_days_low'),'days_max':item.get('target_days_high'),'target_days':{'days_low':item.get('target_days_low'),'days_high':item.get('target_days_high')},'strategy_id':item.get('strategy_id'),'entry_status':'추천 당시 진입구간','signal_active':True})

def _cached_detail(symbol,strategy_id=None):
    row,sig=_find_scan(symbol,strategy_id)
    if row and sig:
        sid=sig.get('strategy_id');plans=row.get('strategy_trade_plans') or {};plan=normalize_plan(plans.get(sid) or row.get('trade_plan'));active=bool(sig.get('strict',True))
        return {'symbol':symbol,'name_ko':row.get('name_ko') or korean_name(symbol,row.get('security_name')),'security_name':row.get('security_name'),'strategy_id':sid,'strategy_name':sig.get('strategy_name'),'strategy_reason':sig.get('evidence') or sig.get('why') or row.get('strategy_reason'),'analysis_label':'추천 이유' if active else '현재 분석','signal':{'score':sig.get('elite_score',sig.get('strategy_score',row.get('score',0))),'active':active,'rsi':row.get('rsi'),'d120':row.get('d120'),'bb_pos':row.get('bb_pos'),'atr_pct':row.get('atr_pct')},'flow':row.get('flow') or {},'trade_plan':plan,'usdkrw':usdkrw_rate(),'source':'saved_scan'}
    item=_find_history(symbol,strategy_id)
    if item:return {'symbol':symbol,'name_ko':item.get('name_ko') or korean_name(symbol,item.get('security_name')),'security_name':item.get('security_name'),'strategy_id':item.get('strategy_id'),'strategy_name':item.get('strategy_name'),'strategy_reason':item.get('strategy_reason'),'analysis_label':'추천 이유','signal':{'score':item.get('score',0),'active':True,'rsi':item.get('rsi'),'d120':item.get('d120'),'bb_pos':item.get('bb_pos'),'atr_pct':item.get('atr_pct')},'trade_plan':_plan_from_history(item),'usdkrw':usdkrw_rate(),'source':'saved_history'}
    return None

def _cached_chart(symbol,strategy_id):
    row,_=_find_scan(symbol,strategy_id)
    if row:
        closes=row.get('sparkline') or [];hi=row.get('bb_high_spark') or [];lo=row.get('bb_low_spark') or [];plans=row.get('strategy_trade_plans') or {};plan=normalize_plan(plans.get(strategy_id) or row.get('trade_plan'));series=[{'date':str(i+1),'close':c,'sma120':None,'bb_low':lo[i] if i<len(lo) else None,'bb_high':hi[i] if i<len(hi) else None,'rsi':None} for i,c in enumerate(closes)];return {'symbol':symbol,'strategy_id':strategy_id,'series':series,'trade_plan':plan,'current_price':closes[-1] if closes else None,'source':'saved_scan'}
    item=_find_history(symbol,strategy_id)
    if item:
        closes=item.get('sparkline') or [];series=[{'date':str(i+1),'close':c,'sma120':None,'bb_low':None,'bb_high':None,'rsi':None} for i,c in enumerate(closes)];return {'symbol':symbol,'strategy_id':strategy_id,'series':series,'trade_plan':_plan_from_history(item),'current_price':closes[-1] if closes else None,'source':'saved_history'}
    return None

def _cached_backtest(symbol,strategy_id):
    row,sig=_find_scan(symbol,strategy_id)
    if row and sig and sig.get('backtest'):return sig['backtest']
    return None

def chart_payload(symbol,strategy_id,days=180):
    d=fresh_price_history(symbol,'2y');ind=indicators(d);plan=normalize_plan(trade_plan(d,strategy_id));x=d.join(ind[['sma120','rsi','bb_low','bb_high']],how='left').tail(days);series=[]
    for idx,row in x.iterrows():series.append({'date':idx.strftime('%Y-%m-%d'),'close':round(float(row['Close']),2),'sma120':None if pd.isna(row['sma120']) else round(float(row['sma120']),2),'bb_low':None if pd.isna(row['bb_low']) else round(float(row['bb_low']),2),'bb_high':None if pd.isna(row['bb_high']) else round(float(row['bb_high']),2),'rsi':None if pd.isna(row['rsi']) else round(float(row['rsi']),1)})
    return {'symbol':symbol,'strategy_id':strategy_id,'series':series,'trade_plan':plan,'current_price':series[-1]['close'] if series else None,'source':'live'}

def _decorate_paper_snapshot(data):
    out=dict(data or {});orders=[]
    for raw_order in out.get('orders') or []:
        order=dict(raw_order);symbol=str(order.get('symbol') or '').upper();row,_=_find_scan(symbol,order.get('strategy_id'));order['name_ko']=(row or {}).get('name_ko') or korean_name(symbol,(row or {}).get('security_name'));orders.append(order)
    out['orders']=orders;return out

def _paper_state_path():
    raw=str(request.headers.get('X-Paper-Client') or '').strip()
    if not raw:raw=f"anonymous:{request.remote_addr or 'unknown'}"
    token=hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]
    return PAPER_CLIENT_DIR/f'{token}.json'

@app.route('/')
def index():return send_from_directory('static','dashboard.html')
@app.route('/health')
def health():return jsonify({'ok':True,'version':APP_VERSION,'core':CORE_VERSION,'architecture':'clean'})
@app.route('/api/version')
def version():return jsonify({'version':APP_VERSION,'core':CORE_VERSION,'architecture':'standalone','public_strategies':list(PUBLIC_STRATEGIES),'aggregate_cap':None})
@app.route('/api/latest')
def latest():
    data=load_json(SCAN_FILE,{'status':'pending','results':[]});rows=[];open_idx=_open_history_index()
    for raw in data.get('results') or []:
        row=public_row(raw)
        if not row:continue
        now=(row.get('sparkline') or [None])[-1]
        for sig in row.get('strategy_signals') or []:
            key=f"{str(row.get('symbol','')).upper()}|{sig.get('strategy_id')}";old=open_idx.get(key)
            if old:sig['lifecycle']=_lifecycle(old,now)
        key=f"{str(row.get('symbol','')).upper()}|{row.get('strategy_id')}";old=open_idx.get(key);row['lifecycle']=_lifecycle(old,now) if old else None
        if old:
            row['trade_plan']=_plan_from_history(old);row['original_recommendation']=True
            plans=dict(row.get('strategy_trade_plans') or {});plans[row['strategy_id']]=row['trade_plan'];row['strategy_trade_plans']=plans
        rows.append(row)
    rows.sort(key=lambda x:(bool(x.get('aggregate_eligible')),x['score']),reverse=True);data['results']=rows;data['ui_version']=APP_VERSION;data['display_filter']='live candidates are mutable intraday; confirmed history is frozen after US daily close';data['usdkrw']=usdkrw_rate();return jsonify(data)
@app.route('/api/history')
def history():
    data=load_json(HISTORY_FILE,{'days':[],'summary':{}})
    try:page=max(0,int(request.args.get('page',0)))
    except Exception:page=0
    try:size=min(10,max(1,int(request.args.get('size',5))))
    except Exception:size=5
    start=page*size;end=start+size;days=data.get('days') or []
    for day in days[start:end]:
        for item in day.get('items') or []:item['name_ko']=item.get('name_ko') or korean_name(item.get('symbol'),item.get('security_name'))
    return jsonify({'version':data.get('version'),'updated_at':data.get('updated_at'),'summary':data.get('summary') or {},'days':days[start:end],'page':page,'size':size,'has_more':end<len(days),'total_days':len(days),'usdkrw':usdkrw_rate(),'legacy_entries_repaired':data.get('legacy_entries_repaired',0),'publication_policy':data.get('publication_policy'),'last_publish_check':data.get('last_publish_check')})
@app.route('/api/signal-events')
def signal_events():
    data=load_json(SIGNAL_EVENTS_FILE,{'active':{},'events':[]})
    try:limit=min(200,max(1,int(request.args.get('limit',50))))
    except Exception:limit=50
    events=list(reversed(data.get('events') or []))[:limit]
    return jsonify({'updated_at':data.get('updated_at'),'market_date':data.get('market_date'),'active_count':len(data.get('active') or {}),'events':events})
@app.route('/api/market')
def market():return jsonify(market_snapshot())
@app.route('/api/detail/<symbol>')
def detail(symbol):
    s=symbol.upper().strip();requested=request.args.get('strategy');sid=requested if requested in PUBLIC_STRATEGIES else requested;cached=_cached_detail(s,sid)
    if cached:return jsonify(cached)
    try:
        d=fresh_price_history(s,'10y');market=market_snapshot();ev=evaluate_strategies(d,market.get('state'));public=[x for x in ev['strategies'] if x['id'] in PUBLIC_STRATEGIES];public.sort(key=lambda x:(x['active'],x['score']),reverse=True);sid=requested if requested in PUBLIC_STRATEGIES else public[0]['id'];chosen=next(x for x in ev['strategies'] if x['id']==sid);plan=normalize_plan(trade_plan(d,sid));active=bool(chosen['active']);reason=chosen['evidence'] if active else f"현재는 매수 신호가 아닙니다. 가장 가까운 전략 조건: {chosen['why']}"
        return jsonify({'symbol':s,'name_ko':korean_name(s,s),'security_name':s,'strategy_id':sid,'strategy_name':chosen['name'],'strategy_reason':reason,'analysis_label':'추천 이유' if active else '현재 분석','signal':{'score':chosen['score'],'active':active,**ev['metrics']},'flow':ev.get('flow') or {},'strategies':public,'trade_plan':plan,'usdkrw':usdkrw_rate(),'market':market,'source':'live'})
    except Exception as exc:return jsonify({'error':str(exc)}),400
@app.route('/api/chart/<symbol>')
def chart(symbol):
    s=symbol.upper().strip();sid=request.args.get('strategy') or 'confirmed_pullback';cached=_cached_chart(s,sid)
    try:return jsonify(chart_payload(s,sid))
    except Exception as exc:
        if cached:cached['warning']='최신 차트 호출이 제한되어 저장된 추천 차트를 표시합니다.';return jsonify(cached)
        return jsonify({'error':str(exc)}),400
@lru_cache(maxsize=256)
def live_backtest(symbol,strategy_id):return run_backtest(symbol,strategy_id)
@app.route('/api/backtest/<symbol>')
def backtest(symbol):
    s=symbol.upper().strip();sid=request.args.get('strategy') or 'confirmed_pullback';cached=_cached_backtest(s,sid)
    if cached:return jsonify(cached)
    try:return jsonify(live_backtest(s,sid))
    except Exception as exc:return jsonify({'error':str(exc)}),400

@app.route('/api/paper',methods=['GET'])
def paper_status_api():
    try:
        from paper_broker_service import status
        return jsonify(_decorate_paper_snapshot(status(state_path=_paper_state_path())))
    except Exception as exc:return jsonify({'error':str(exc)}),400
@app.route('/api/paper/submit',methods=['POST'])
def paper_submit_api():
    body=request.get_json(silent=True) or {};symbol=str(body.get('symbol') or '').upper().strip();strategy=body.get('strategy')
    if not symbol:return jsonify({'error':'symbol이 필요합니다'}),400
    try:
        from paper_broker_service import submit_from_latest,status
        path=_paper_state_path();submit_from_latest(symbol,strategy,state_path=path);return jsonify(_decorate_paper_snapshot(status(state_path=path)))
    except Exception as exc:return jsonify({'error':str(exc)}),400
@app.route('/api/paper/refresh',methods=['POST'])
def paper_refresh_api():
    try:
        from paper_broker_service import refresh_active
        return jsonify(_decorate_paper_snapshot(refresh_active(state_path=_paper_state_path())))
    except Exception as exc:return jsonify({'error':str(exc)}),400
@app.route('/api/paper/reset',methods=['POST'])
def paper_reset_api():
    try:
        from paper_broker_service import reset
        return jsonify(_decorate_paper_snapshot(reset(state_path=_paper_state_path())))
    except Exception as exc:return jsonify({'error':str(exc)}),400

if __name__=='__main__':app.run(host='0.0.0.0',port=8766,debug=False)
