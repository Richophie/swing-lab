from __future__ import annotations

import re
from flask import jsonify, request, Response

from app_v13 import app, index_v13, _load, _norm_row, HISTORY_FILE
from app_v6 import CACHE_FILE, market_live
from app_v8 import load_df
from core_v4 import playbooks, trade_plan_for

PUBLIC_STRATEGIES = {'confirmed_pullback','rsi2_trend_reversion','momentum_pullback'}
HIDDEN_EXPERIMENTAL = {'volatility_breakout'}


def _public_row(row):
    r=_norm_row(row); sigs=[s for s in (r.get('strategy_signals') or []) if s.get('strategy_id') in PUBLIC_STRATEGIES and float(s.get('strategy_score',0))>=85]
    if not sigs:return None
    sigs.sort(key=lambda s:float(s.get('strategy_score',0)),reverse=True); best=sigs[0]
    r['strategy_signals']=sigs; r['strategy_id']=best.get('strategy_id'); r['strategy_name']=best.get('strategy_name'); r['strategy_reason']=best.get('evidence') or best.get('why'); r['score']=float(best.get('strategy_score',r.get('score',0)))
    plans=r.get('strategy_trade_plans') or {}; r['trade_plan']=plans.get(r['strategy_id']) or r.get('trade_plan') or {}; r['grade']='S'; return r


def latest_v14():
    data=_load(CACHE_FILE,{'status':'pending','results':[]}); rows=[]
    for raw in data.get('results') or []:
        r=_public_row(raw)
        if r is not None: rows.append(r)
    rows.sort(key=lambda x:float(x.get('score',0)),reverse=True); data['results']=rows; data['display_filter']='S only / 3 public strategies; breakout hidden for validation'; data['ui_version']='14.1'; data['hidden_strategy']='volatility_breakout'; return jsonify(data)


def detail_v14(symbol):
    try:
        s=symbol.upper().strip(); d=load_df(s,'10y'); state=None
        try: state=market_live().get('state')
        except Exception: pass
        ens=playbooks(d,state); public=[q for q in ens.get('strategies',[]) if q.get('id') in PUBLIC_STRATEGIES and q.get('active')]; public.sort(key=lambda q:float(q.get('score',0)),reverse=True)
        best=public[0] if public else next((q for q in ens.get('strategies',[]) if q.get('id') in PUBLIC_STRATEGIES),ens.get('best_strategy')); sid=request.args.get('strategy') or (best or {}).get('id') or 'confirmed_pullback'
        if sid not in PUBLIC_STRATEGIES:sid=(best or {}).get('id') or 'confirmed_pullback'
        plan=trade_plan_for(d,sid)
        return jsonify({'symbol':s,'strategy_id':sid,'strategy_name':next((q.get('name') for q in ens.get('strategies',[]) if q.get('id')==sid),sid),'ensemble':ens,'trade_plan':plan,'signal':{'score':next((q.get('score') for q in ens.get('strategies',[]) if q.get('id')==sid),0)},'market':market_live()})
    except Exception as e:return jsonify({'error':str(e)}),400

app.view_functions['latest']=latest_v14
app.view_functions['detail']=detail_v14


def index_v14():
    base=index_v13(); html=base.get_data(as_text=True) if hasattr(base,'get_data') else str(base)
    html=re.sub(r'<title>.*?</title>','<title>오늘의 스윙자리 · v14.1</title>',html,count=1,flags=re.S); html=re.sub(r'PRO LIVE v\d+(?:\.\d+)?','PRO LIVE v14.1',html); html=re.sub(r'오늘의 스윙자리(?:\s*[·v]\s*v?\d+(?:\.\d+)?)?','오늘의 스윙자리',html,count=1); html=html.replace('S-CLASS STRATEGY BOARD','S-CLASS STRATEGY BOARD · 3 STRATEGIES')
    if 'id="todayStrategyTabs"' not in html: html=html.replace('<div id="grid" class="grid"></div>','<div id="todayStrategyTabs"></div><div id="grid" class="grid"></div>',1)
    html=html.replace('종가 · 120일선 · 볼린저 상/하단 · BUY 구간 · TARGET · STOP · RSI 30/70','<span class="lg close">종가</span> · <span class="lg sma">120일선</span> · <span class="lg bb">볼린저 상/하단</span> · <span class="lg buy">BUY 구간</span> · <span class="lg target">TARGET</span> · <span class="lg stop">STOP</span> · <span class="lg rsi">RSI 30/70</span>')
    css='''<style>
    .exp-note{margin-top:8px;padding:10px 12px;border-radius:12px;background:#f7f7f5;color:var(--mut);font-size:11px;line-height:1.5}.calc-disabled{color:var(--mut);background:#f7f7f5}.lg{font-weight:800}.lg.close{color:#111}.lg.sma{color:#4676c5}.lg.bb{color:#b5bbb5}.lg.buy{color:#4f9c72}.lg.target{color:#147552}.lg.stop{color:#b34843}.lg.rsi{color:#7867a7}.bigchart{padding-right:0}.chartmini svg{width:100%;height:100%}
    </style>'''; html=html.replace('</head>',css+'</head>')
    js=r'''
<script>
const TODAY_PUBLIC_STRATEGIES=[['all','종합'],['confirmed_pullback','확인형 눌림반등'],['rsi2_trend_reversion','RSI2'],['momentum_pullback','모멘텀']];
function publicSignals(r){return (sSignals(r)||[]).filter(x=>x.strategy_id!=='volatility_breakout')}
filteredToday=function(rows,sid){let out=[];(rows||[]).forEach(r=>{let sigs=publicSignals(r),sig=sid==='all'?sigs.slice().sort((a,b)=>Number(b.strategy_score)-Number(a.strategy_score))[0]:sigs.find(x=>x.strategy_id===sid);if(!sig)return;let plans=r.strategy_trade_plans||{},p=planNorm(plans[sig.strategy_id]||r.trade_plan||{});out.push({...r,score:Number(sig.strategy_score||0),strategy_id:sig.strategy_id,strategy_name:sig.strategy_name,strategy_reason:sig.evidence||sig.why,trade_plan:p,grade:'S'})});out.sort((a,b)=>b.score-a.score);if(sid==='all'){let seen=new Set();out=out.filter(r=>{if(seen.has(r.symbol))return false;seen.add(r.symbol);return true})}return out}
strategyTabsHtml=function(rows,active,scope){let list=scope==='today'?TODAY_PUBLIC_STRATEGIES:STRATEGIES;return `<div class="strategy-tabs">${list.map(([id,n])=>{let c=scope==='today'?filteredToday(rows,id).length:0;return `<button class="strategy-tab ${active===id?'on':''}" data-scope="${scope}" data-strategy="${id}">${n}${scope==='today'?`<span class="strategy-count">${c}</span>`:''}</button>`}).join('')}</div>${scope==='today'?'<div class="exp-note">돌파 전략은 현재 메인 추천에서 숨김 · 과거 기록에서는 검증용으로 계속 추적합니다.</div>':''}`}
function safePlan(p){p=planNorm(p||{});for(const k of ['entry_low','entry_high','target','stop']){let n=Number(p[k]);p[k]=Number.isFinite(n)?n:null}return p}function planReady(p){p=safePlan(p);return[p.entry_low,p.entry_high,p.target,p.stop].every(v=>Number.isFinite(v))}

mini=function(r){let v=(r.sparkline||[]).map(Number).filter(Number.isFinite);if(v.length<2)return'';let p=safePlan(r.trade_plan),current=v[v.length-1],bbh=(r.bb_high_spark||[]).map(Number),bbl=(r.bb_low_spark||[]).map(Number);let all=v.concat([p.entry_low,p.entry_high,p.target,p.stop,current]).concat(bbh,bbl).filter(Number.isFinite),mn=Math.min(...all),mx=Math.max(...all),margin=(mx-mn||1)*.08;mn-=margin;mx+=margin;let w=280,h=120,pad=10,X=i=>pad+i/(v.length-1)*(w-pad*2),Y=x=>h-pad-(x-mn)/(mx-mn)*(h-pad*2),mk=a=>a.length===v.length?a.map((x,i)=>Number.isFinite(x)?(i?'L':'M')+X(i).toFixed(1)+' '+Y(x).toFixed(1):'').filter(Boolean).join(' '):'';let closePath=mk(v),up=mk(bbh),lo=mk(bbl),buyA=p.entry_low,buyB=p.entry_high;return `<svg viewBox="0 0 ${w} ${h}"><rect width="${w}" height="${h}" fill="#fafbf8"/>${up?`<path d="${up}" fill="none" stroke="#d3d7d2" stroke-width="1"/>`:''}${lo?`<path d="${lo}" fill="none" stroke="#d3d7d2" stroke-width="1"/>`:''}${Number.isFinite(buyA)&&Number.isFinite(buyB)?`<rect x="${pad}" y="${Math.min(Y(buyA),Y(buyB))}" width="${w-pad*2}" height="${Math.max(3,Math.abs(Y(buyA)-Y(buyB)))}" fill="#e7f6ed"/>`:''}<path d="${closePath}" fill="none" stroke="#171817" stroke-width="2"/>${Number.isFinite(p.target)?`<line x1="${pad}" x2="${w-pad}" y1="${Y(p.target)}" y2="${Y(p.target)}" stroke="#147552" stroke-width="1.2" stroke-dasharray="4 4"/>`:''}${Number.isFinite(p.stop)?`<line x1="${pad}" x2="${w-pad}" y1="${Y(p.stop)}" y2="${Y(p.stop)}" stroke="#b34843" stroke-width="1.2" stroke-dasharray="4 4"/>`:''}<circle cx="${w-pad}" cy="${Y(current)}" r="3.5" fill="#111"/></svg>`}

drawChart=function(c){let s=c.series||[];if(!s.length)return '<div class="status">차트 데이터가 없어요.</div>';let q=safePlan(c.trade_plan),w=1100,h=450,padL=52,plotR=920,railX=940,priceBottom=318,rsiTop=350,rsiH=64;let priceVals=s.flatMap(x=>[x.close,x.sma120,x.bb_low,x.bb_high]).concat([q.entry_low,q.entry_high,q.target,q.stop]).map(Number).filter(Number.isFinite),mn=Math.min(...priceVals),mx=Math.max(...priceVals),m=(mx-mn||1)*.08;mn-=m;mx+=m;let X=i=>padL+i/Math.max(1,s.length-1)*(plotR-padL),Y=v=>priceBottom-padL-(Number(v)-mn)/(mx-mn)*(priceBottom-padL*2),RY=v=>rsiTop+rsiH-(Number(v)/100)*rsiH;let pathFor=k=>s.map((x,i)=>x[k]==null?'':[(i?'L':'M')+X(i).toFixed(1),Y(x[k]).toFixed(1)].join(' ')).filter(Boolean).join(' '),rsi=s.map((x,i)=>x.rsi==null?'':[(i?'L':'M')+X(i).toFixed(1),RY(x.rsi).toFixed(1)].join(' ')).filter(Boolean).join(' '),current=Number(s[s.length-1].close);let rail=(txt,val,color,bg='#fff')=>Number.isFinite(Number(val))?`<line x1="${padL}" x2="${plotR}" y1="${Y(val)}" y2="${Y(val)}" stroke="${color}" stroke-width="1.25" stroke-dasharray="6 5"/><line x1="${plotR}" x2="${railX}" y1="${Y(val)}" y2="${Y(val)}" stroke="${color}"/><rect x="${railX}" y="${Y(val)-12}" width="142" height="24" rx="7" fill="${bg}" stroke="${color}"/><text x="${railX+8}" y="${Y(val)+4}" font-size="11" font-weight="800" fill="${color}">${txt}  $${Number(val).toFixed(2)}</text>`:'';return `<svg viewBox="0 0 ${w} ${h}"><rect width="${w}" height="${h}" fill="#fbfcfa"/>${Number.isFinite(q.entry_low)&&Number.isFinite(q.entry_high)?`<rect x="${padL}" y="${Math.min(Y(q.entry_low),Y(q.entry_high))}" width="${plotR-padL}" height="${Math.max(4,Math.abs(Y(q.entry_low)-Y(q.entry_high)))}" fill="#e8f6ed"/>`:''}<path d="${pathFor('bb_high')}" fill="none" stroke="#d3d7d2" stroke-width="1.1"/><path d="${pathFor('bb_low')}" fill="none" stroke="#d3d7d2" stroke-width="1.1"/><path d="${pathFor('sma120')}" fill="none" stroke="#4676c5" stroke-width="1.7"/><path d="${pathFor('close')}" fill="none" stroke="#111" stroke-width="2.4"/>${rail('TARGET',q.target,'#147552','#f2faf5')}${rail('NOW',current,'#111','#fff')}${rail('STOP',q.stop,'#b34843','#fff5f3')}<line x1="${padL}" x2="${plotR}" y1="${RY(70)}" y2="${RY(70)}" stroke="#ddd"/><line x1="${padL}" x2="${plotR}" y1="${RY(30)}" y2="${RY(30)}" stroke="#ddd"/><path d="${rsi}" fill="none" stroke="#7867a7" stroke-width="1.6"/><text x="${padL}" y="${rsiTop-8}" font-size="11" font-weight="700" fill="#7867a7">RSI</text></svg>`}

function todayCard(r,i){let p=safePlan(r.trade_plan),e=p.target_days||{},now=(r.sparkline||[]).slice(-1)[0];return `<div class="pick" onclick="openTicker('${r.symbol}','${r.strategy_id}')"><div class="picktop"><div><div class="mut">#${i+1}</div><div class="ticker">${r.symbol}</div></div><div class="grade good">S</div></div><div class="chartmini">${mini(r)}</div><div class="levels"><div>현재가<b>$${now??'-'}</b></div><div>BUY<b>$${p.entry_low??'-'}~${p.entry_high??'-'}</b></div><div>TARGET<b>$${p.target??'-'}</b></div><div>STOP<b>$${p.stop??'-'}</b></div></div><div class="metrics"><span>RSI ${r.rsi??'-'}</span><span>120일선 ${r.d120??'-'}%</span><span>볼린저 ${r.bb_pos??'-'}%</span><span>${e.days_low?e.days_low+'~'+e.days_high+'일':'-'}</span></div><div style="margin-top:8px"><b>${Math.round(r.score)}점 · 좋은 자리</b></div><div class="result" style="margin-top:8px;padding:9px 10px"><b>추천 방식 · ${r.strategy_name}</b><br><span class="mut">${strategyExplain(r)}</span></div></div>`}

const _oldCachedDetail=cachedDetailFromRow;cachedDetailFromRow=function(r){r={...r,trade_plan:safePlan(r.trade_plan)};_oldCachedDetail(r);if(!planReady(r.trade_plan)){$('entry').textContent='계산 준비 중';$('target').textContent='—';$('stop').textContent='—';$('capitalOut').className='result calc-disabled';$('capitalOut').textContent='BUY 가격이 확인되면 계산합니다.';$('wantOut').className='result calc-disabled';$('wantOut').textContent='BUY 가격이 확인되면 계산합니다.';}}
const _oldCalc=calc;calc=function(){if(!DETAIL||!planReady(DETAIL.trade_plan)){$('capitalOut').className='result calc-disabled';$('capitalOut').textContent='BUY 가격이 확인되면 계산합니다.';$('wantOut').className='result calc-disabled';$('wantOut').textContent='BUY 가격이 확인되면 계산합니다.';return}_oldCalc()}
render=function(d){CUR=d;let rs=d.results||[];if(TODAY_STRATEGY==='volatility_breakout')TODAY_STRATEGY='all';let holder=document.getElementById('todayStrategyTabs');holder.innerHTML=strategyTabsHtml(rs,TODAY_STRATEGY,'today');let show=filteredToday(rs,TODAY_STRATEGY);$('grid').innerHTML=show.length?show.map(todayCard).join(''):`<div class="strategy-empty" style="grid-column:1/-1">이 전략에서 오늘 S급 신호는 없어요.</div>`;$('status').className='status ok';$('status').textContent=`✓ S급 ${show.length}개 · Core 4.0 · UI v14.1 · 전체 스캔 ${fmt(d.scanned_at)}`;bindStrategyTabs()}
setTimeout(()=>{if(CUR)render(CUR)},50);
</script>'''
    html=html.replace('</body>',js+'</body>'); return Response(html,mimetype='text/html')

app.view_functions['index']=index_v14

@app.route('/api/version-v14')
def version_v14(): return {'version':'14.1','core':'4.0','public_strategies':['confirmed_pullback','rsi2_trend_reversion','momentum_pullback'],'experimental_hidden':['volatility_breakout'],'chart':'right price rail + differentiated colors + bollinger mini chart'}
