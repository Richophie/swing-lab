from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import json
import pandas as pd
import yfinance as yf
from flask import Flask, jsonify, request, send_from_directory

from config import APP_VERSION, CORE_VERSION, PUBLIC_STRATEGIES, ELITE_MAX, S_THRESHOLD
from market_data import load_price_history, fresh_price_history, indicators, market_snapshot
from strategy_engine import evaluate_strategies, trade_plan
from backtest_engine import run_backtest
from stock_names import korean_name

ROOT=Path(__file__).parent;STATIC=ROOT/'static';SCAN_FILE=STATIC/'latest_scan.json';HISTORY_FILE=STATIC/'trade_history.json';app=Flask(__name__,static_folder='static')


def load_json(path,default):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception:return default

def normalize_plan(plan):
    p=dict(plan or {})
    for key in ('entry_low','entry_high','target','stop'):
        try:p[key]=float(p[key]) if p.get(key) is not None else None
        except Exception:p[key]=None
    return p

def public_row(raw):
    row=dict(raw)
    # Strategy tabs must retain their raw S signals. Aggregate filtering happens in the UI from elite_pass.
    signals=[s for s in row.get('strategy_signals',[]) if s.get('strategy_id') in PUBLIC_STRATEGIES and float(s.get('strategy_score',0))>=S_THRESHOLD]
    if not signals:return None
    signals.sort(key=lambda x:(bool(x.get('elite_pass')),float(x.get('elite_score',x.get('strategy_score',0)))),reverse=True)
    best=signals[0];plans=row.get('strategy_trade_plans') or {}
    row['strategy_signals']=signals;row['strategy_id']=best['strategy_id'];row['strategy_name']=best['strategy_name'];row['strategy_reason']=best.get('evidence') or best.get('why');row['selection_reason']=best.get('selection_reason');row['score']=float(best.get('elite_score',best.get('strategy_score',0)));row['trade_plan']=normalize_plan(plans.get(best['strategy_id']) or row.get('trade_plan'));row['aggregate_eligible']=any(bool(s.get('elite_pass')) for s in signals);row['name_ko']=row.get('name_ko') or korean_name(row.get('symbol'),row.get('security_name'));return row

def quote_name(symbol):
    try:
        info=yf.Ticker(symbol).get_info();return info.get('longName') or info.get('shortName') or symbol
    except Exception:return symbol

def usdkrw_rate():
    try:
        d=fresh_price_history('KRW=X','5d');return round(float(d['Close'].dropna().iloc[-1]),2)
    except Exception:return None

def chart_payload(symbol,strategy_id,days=180):
    d=fresh_price_history(symbol,'2y');ind=indicators(d);plan=normalize_plan(trade_plan(d,strategy_id));x=d.join(ind[['sma120','rsi','bb_low','bb_high']],how='left').tail(days);series=[]
    for idx,row in x.iterrows():series.append({'date':idx.strftime('%Y-%m-%d'),'close':round(float(row['Close']),2),'sma120':None if pd.isna(row['sma120']) else round(float(row['sma120']),2),'bb_low':None if pd.isna(row['bb_low']) else round(float(row['bb_low']),2),'bb_high':None if pd.isna(row['bb_high']) else round(float(row['bb_high']),2),'rsi':None if pd.isna(row['rsi']) else round(float(row['rsi']),1)})
    return {'symbol':symbol,'strategy_id':strategy_id,'series':series,'trade_plan':plan,'current_price':series[-1]['close'] if series else None}

@app.route('/')
def index():return send_from_directory('static','dashboard.html')
@app.route('/health')
def health():return jsonify({'ok':True,'version':APP_VERSION,'core':CORE_VERSION,'architecture':'clean'})
@app.route('/api/version')
def version():return jsonify({'version':APP_VERSION,'core':CORE_VERSION,'architecture':'standalone','public_strategies':list(PUBLIC_STRATEGIES),'elite_max':ELITE_MAX})
@app.route('/api/latest')
def latest():
    data=load_json(SCAN_FILE,{'status':'pending','results':[]});rows=[]
    for raw in data.get('results') or []:
        row=public_row(raw)
        if row:rows.append(row)
    rows.sort(key=lambda x:(bool(x.get('aggregate_eligible')),x['score']),reverse=True);data['results']=rows;data['ui_version']=APP_VERSION;data['display_filter']='strategy tabs: raw S / aggregate: conservative top 5';data['elite_max']=ELITE_MAX;data['usdkrw']=usdkrw_rate();return jsonify(data)
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
    return jsonify({'version':data.get('version'),'updated_at':data.get('updated_at'),'summary':data.get('summary') or {},'days':days[start:end],'page':page,'size':size,'has_more':end<len(days),'total_days':len(days),'usdkrw':usdkrw_rate(),'legacy_entries_repaired':data.get('legacy_entries_repaired',0)})
@app.route('/api/market')
def market():return jsonify(market_snapshot())
@app.route('/api/detail/<symbol>')
def detail(symbol):
    try:
        s=symbol.upper().strip();d=fresh_price_history(s,'10y');market=market_snapshot();ev=evaluate_strategies(d,market.get('state'));public=[x for x in ev['strategies'] if x['id'] in PUBLIC_STRATEGIES];public.sort(key=lambda x:(x['active'],x['score']),reverse=True);requested=request.args.get('strategy');sid=requested if requested in PUBLIC_STRATEGIES else public[0]['id'];chosen=next(x for x in ev['strategies'] if x['id']==sid);plan=normalize_plan(trade_plan(d,sid));official=quote_name(s)
        return jsonify({'symbol':s,'name_ko':korean_name(s,official),'security_name':official,'strategy_id':sid,'strategy_name':chosen['name'],'strategy_reason':chosen['evidence'],'signal':{'score':chosen['score'],'active':chosen['active'],**ev['metrics']},'strategies':public,'trade_plan':plan,'usdkrw':usdkrw_rate(),'market':market})
    except Exception as exc:return jsonify({'error':str(exc)}),400
@app.route('/api/chart/<symbol>')
def chart(symbol):
    try:
        sid=request.args.get('strategy') or 'confirmed_pullback'
        if sid not in PUBLIC_STRATEGIES:sid='confirmed_pullback'
        return jsonify(chart_payload(symbol.upper().strip(),sid))
    except Exception as exc:return jsonify({'error':str(exc)}),400
@lru_cache(maxsize=256)
def cached_backtest(symbol,strategy_id):return run_backtest(symbol,strategy_id)
@app.route('/api/backtest/<symbol>')
def backtest(symbol):
    try:
        sid=request.args.get('strategy') or 'confirmed_pullback'
        if sid not in PUBLIC_STRATEGIES:sid='confirmed_pullback'
        return jsonify(cached_backtest(symbol.upper().strip(),sid))
    except Exception as exc:return jsonify({'error':str(exc)}),400

if __name__=='__main__':app.run(host='0.0.0.0',port=8766,debug=False)
