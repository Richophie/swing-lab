from pathlib import Path
import json
from flask import jsonify, request, Response

from app_v11 import app, index_v11, _strategy_fallback
from app_v6 import CACHE_FILE, indicators
from app_v8 import load_df
from core_v4 import trade_plan_for

HISTORY_FILE=Path(__file__).parent/'static'/'trade_history.json'


def _load(path,default):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception:return default


def _norm_plan(p):
    p=dict(p or {})
    if p.get('entry_low') is None:p['entry_low']=p.get('buy_low')
    if p.get('entry_high') is None:p['entry_high']=p.get('buy_high')
    if p.get('risk_reward') is None:p['risk_reward']=p.get('rr')
    if not p.get('target_days'):
        p['target_days']={'days_low':p.get('days_min'),'days_high':p.get('days_max'),'method':p.get('basis')}
    if p.get('target_reason') is None:p['target_reason']=p.get('basis')
    if p.get('stop_reason') is None:p['stop_reason']=p.get('basis')
    return p


def _norm_row(row):
    r=_strategy_fallback(row)
    r=dict(r)
    r['trade_plan']=_norm_plan(r.get('trade_plan'))
    r['strategy_trade_plans']={k:_norm_plan(v) for k,v in (r.get('strategy_trade_plans') or {}).items()}
    return r


def latest_v13():
    data=_load(CACHE_FILE,{'status':'pending','results':[]})
    rows=[_norm_row(r) for r in (data.get('results') or [])]
    data['results']=[r for r in rows if r.get('grade')=='S' and r.get('eligible',True)]
    data['display_filter']='S only / strategy tabs'
    data['ui_version']='13.1'
    return jsonify(data)


def history_v13():
    data=_load(HISTORY_FILE,{'days':[],'summary':{}});days=data.get('days') or []
    try:page=max(0,int(request.args.get('page',0)))
    except Exception:page=0
    try:size=min(10,max(1,int(request.args.get('size',5))))
    except Exception:size=5
    start=page*size;end=start+size
    return jsonify({'version':data.get('version'),'updated_at':data.get('updated_at'),'summary':data.get('summary') or {},'days':days[start:end],'page':page,'size':size,'has_more':end<len(days),'total_days':len(days)})


def chart_v13(symbol):
    try:
        s=symbol.upper().strip(); sid=request.args.get('strategy','confirmed_pullback')
        d=load_df(s,'2y'); ind=indicators(d); p=_norm_plan(trade_plan_for(d,sid))
        x=d.join(ind[['sma120','rsi','bb_low','bb_high']],how='left').tail(180)
        rows=[]
        for idx,r in x.iterrows():
            rows.append({'date':idx.strftime('%Y-%m-%d'),'close':round(float(r['Close']),2),'sma120':None if r['sma120']!=r['sma120'] else round(float(r['sma120']),2),'bb_low':None if r['bb_low']!=r['bb_low'] else round(float(r['bb_low']),2),'bb_high':None if r['bb_high']!=r['bb_high'] else round(float(r['bb_high']),2),'rsi':None if r['rsi']!=r['rsi'] else round(float(r['rsi']),1)})
        return jsonify({'symbol':s,'strategy_id':sid,'series':rows,'trade_plan':p,'current_price':rows[-1]['close'] if rows else None})
    except Exception as e:return jsonify({'error':str(e)}),400

app.view_functions['latest']=latest_v13
app.view_functions['history_v11']=history_v13
app.view_functions['chart']=chart_v13


def index_v13():
    base=index_v11();html=base.get_data(as_text=True) if hasattr(base,'get_data') else str(base)
    html=html.replace('<title>오늘의 스윙자리 v8</title>','<title>오늘의 스윙자리 · v13.1</title>')
    html=html.replace('오늘의 스윙자리 v10','오늘의 스윙자리 · v13.1')
    html=html.replace('PRO LIVE v11.1','PRO LIVE v13.1').replace('DAILY SIGNAL JOURNAL','S-CLASS STRATEGY BOARD')
    html=html.replace('PRO LIVE v10.2','PRO LIVE v13.1').replace('MULTI-STRATEGY ROUTER','S-CLASS STRATEGY BOARD')
    css='''<style>.strategy-tabs{display:flex;gap:6px;flex-wrap:wrap;margin:14px 0 4px}.strategy-tab{border:1px solid var(--line);background:#fff;border-radius:999px;padding:8px 11px;font-size:11px;font-weight:800;cursor:pointer}.strategy-tab.on{background:#111;color:#fff;border-color:#111}.strategy-count{opacity:.55;margin-left:3px}.day-strategy-wrap{margin-top:8px}.strategy-empty{padding:28px 12px;text-align:center;color:var(--mut);font-size:12px}.price-now{font-size:10px;font-weight:800}.chartmini svg{width:100%;height:100%}</style>'''
    html=html.replace('</head>',css+'</head>')
    js=r'''
<script>
const STRATEGIES=[['all','종합'],['confirmed_pullback','확인형 눌림반등'],['rsi2_trend_reversion','RSI2'],['momentum_pullback','모멘텀'],['volatility_breakout','돌파']];
let TODAY_STRATEGY='all';
function planNorm(p){p={...(p||{})};if(p.entry_low==null)p.entry_low=p.buy_low;if(p.entry_high==null)p.entry_high=p.buy_high;if(p.risk_reward==null)p.risk_reward=p.rr;if(!p.target_days)p.target_days={days_low:p.days_min,days_high:p.days_max,method:p.basis};return p}
function sSignals(r){let a=r.strategy_signals||[];if(!a.length&&r.grade==='S')a=[{strategy_id:r.strategy_id,strategy_name:r.strategy_name,strategy_score:r.score,why:r.strategy_reason,evidence:r.strategy_reason}];return a.filter(x=>Number(x.strategy_score||0)>=85)}
function viewForStrategy(r,sid){let sigs=sSignals(r),sig=sid==='all'?sigs.slice().sort((a,b)=>Number(b.strategy_score)-Number(a.strategy_score))[0]:sigs.find(x=>x.strategy_id===sid);if(!sig)return null;let plans=r.strategy_trade_plans||{},p=planNorm(plans[sig.strategy_id]||r.trade_plan||{});return {...r,score:Number(sig.strategy_score||r.score||0),strategy_id:sig.strategy_id,strategy_name:sig.strategy_name||r.strategy_name,strategy_reason:sig.evidence||sig.why||r.strategy_reason,trade_plan:p,grade:'S'}}
function filteredToday(rows,sid){let out=(rows||[]).map(r=>viewForStrategy(r,sid)).filter(Boolean);let seen=new Set();return out.sort((a,b)=>b.score-a.score).filter(r=>{if(sid!=='all')return true;if(seen.has(r.symbol))return false;seen.add(r.symbol);return true})}
function strategyTabsHtml(rows,active,scope){return `<div class="strategy-tabs">${STRATEGIES.map(([id,n])=>{let c=filteredToday(rows,id).length;return `<button class="strategy-tab ${active===id?'on':''}" data-scope="${scope}" data-strategy="${id}">${n}<span class="strategy-count">${c}</span></button>`}).join('')}</div>`}

mini=function(r){let v=(r.sparkline||[]).map(Number).filter(Number.isFinite);if(v.length<2)return'';let p=planNorm(r.trade_plan),current=v[v.length-1];let levels=[p.entry_low,p.entry_high,p.target,p.stop,current].map(Number).filter(Number.isFinite);let all=v.concat(levels),mn=Math.min(...all),mx=Math.max(...all),margin=(mx-mn||1)*.08;mn-=margin;mx+=margin;let w=280,h=120,pad=10,X=i=>pad+i/(v.length-1)*(w-pad*2),Y=x=>h-pad-(x-mn)/(mx-mn)*(h-pad*2),line=v.map((x,i)=>(i?'L':'M')+X(i).toFixed(1)+' '+Y(x).toFixed(1)).join(' ');let buyA=Number(p.entry_low),buyB=Number(p.entry_high);return `<svg viewBox="0 0 ${w} ${h}"><rect width="${w}" height="${h}" fill="#fafbf8"/>${Number.isFinite(buyA)&&Number.isFinite(buyB)?`<rect x="${pad}" y="${Math.min(Y(buyA),Y(buyB))}" width="${w-pad*2}" height="${Math.max(3,Math.abs(Y(buyA)-Y(buyB)))}" fill="#e7f6ed"/>`:''}<path d="${line}" fill="none" stroke="#171817" stroke-width="2"/>${Number.isFinite(Number(p.target))?`<line x1="${pad}" x2="${w-pad}" y1="${Y(Number(p.target))}" y2="${Y(Number(p.target))}" stroke="#147552" stroke-width="1.2" stroke-dasharray="4 4"/>`:''}${Number.isFinite(Number(p.stop))?`<line x1="${pad}" x2="${w-pad}" y1="${Y(Number(p.stop))}" y2="${Y(Number(p.stop))}" stroke="#b34843" stroke-width="1.2" stroke-dasharray="4 4"/>`:''}<circle cx="${w-pad}" cy="${Y(current)}" r="3.5" fill="#111"/><text x="${w-pad-4}" y="${Math.max(10,Y(current)-6)}" text-anchor="end" font-size="9" font-weight="700">NOW $${current.toFixed(2)}</text></svg>`}

drawChart=function(c){let s=c.series||[];if(!s.length)return '<div class="status">차트 데이터가 없어요.</div>';let q=planNorm(c.trade_plan),w=1000,h=450,pad=52,priceBottom=318,rsiTop=350,rsiH=64;let priceVals=s.flatMap(x=>[x.close,x.sma120,x.bb_low,x.bb_high]).concat([q.entry_low,q.entry_high,q.target,q.stop]).map(Number).filter(Number.isFinite);let mn=Math.min(...priceVals),mx=Math.max(...priceVals),m=(mx-mn||1)*.08;mn-=m;mx+=m;let X=i=>pad+i/Math.max(1,s.length-1)*(w-pad*2),Y=v=>priceBottom-pad-(Number(v)-mn)/(mx-mn)*(priceBottom-pad*2),RY=v=>rsiTop+rsiH-(Number(v)/100)*rsiH;let line=k=>s.map((x,i)=>x[k]==null?'':[(i?'L':'M')+X(i).toFixed(1),Y(x[k]).toFixed(1)].join(' ')).filter(Boolean).join(' '),rsi=s.map((x,i)=>x.rsi==null?'':[(i?'L':'M')+X(i).toFixed(1),RY(x.rsi).toFixed(1)].join(' ')).filter(Boolean).join(' ');let current=Number(s[s.length-1].close);let label=(txt,val,color)=>Number.isFinite(Number(val))?`<line x1="${pad}" x2="${w-pad}" y1="${Y(val)}" y2="${Y(val)}" stroke="${color}" stroke-width="1.3" stroke-dasharray="6 5"/><text x="${w-pad-4}" y="${Y(val)-5}" text-anchor="end" font-size="11" font-weight="700" fill="${color}">${txt} $${Number(val).toFixed(2)}</text>`:'';return `<svg viewBox="0 0 ${w} ${h}"><rect width="${w}" height="${h}" fill="#fbfcfa"/>${Number.isFinite(Number(q.entry_low))&&Number.isFinite(Number(q.entry_high))?`<rect x="${pad}" y="${Math.min(Y(q.entry_low),Y(q.entry_high))}" width="${w-pad*2}" height="${Math.max(4,Math.abs(Y(q.entry_low)-Y(q.entry_high)))}" fill="#e8f6ed"/>`:''}<path d="${line('bb_high')}" fill="none" stroke="#c6cbc5" stroke-width="1"/><path d="${line('bb_low')}" fill="none" stroke="#c6cbc5" stroke-width="1"/><path d="${line('sma120')}" fill="none" stroke="#8a918a" stroke-width="1.5"/><path d="${line('close')}" fill="none" stroke="#111" stroke-width="2.3"/>${label('TARGET',q.target,'#147552')}${label('STOP',q.stop,'#b34843')}${label('NOW',current,'#111')}<line x1="${pad}" x2="${w-pad}" y1="${RY(70)}" y2="${RY(70)}" stroke="#ddd"/><line x1="${pad}" x2="${w-pad}" y1="${RY(30)}" y2="${RY(30)}" stroke="#ddd"/><path d="${rsi}" fill="none" stroke="#555" stroke-width="1.5"/><text x="${pad}" y="${rsiTop-8}" font-size="11" font-weight="700">RSI</text></svg>`}

function todayCard(r,i){let p=planNorm(r.trade_plan),e=p.target_days||{},now=(r.sparkline||[]).slice(-1)[0];return `<div class="pick" onclick="openTicker('${r.symbol}','${r.strategy_id}')"><div class="picktop"><div><div class="mut">#${i+1}</div><div class="ticker">${r.symbol}</div></div><div class="grade good">S</div></div><div class="chartmini">${mini(r)}</div><div class="levels"><div>현재가<b>$${now??'-'}</b></div><div>BUY<b>$${p.entry_low??'-'}~${p.entry_high??'-'}</b></div><div>TARGET<b>$${p.target??'-'}</b></div><div>STOP<b>$${p.stop??'-'}</b></div></div><div class="metrics"><span>RSI ${r.rsi??'-'}</span><span>120일선 ${r.d120??'-'}%</span><span>볼린저 ${r.bb_pos??'-'}%</span><span>${e.days_low?e.days_low+'~'+e.days_high+'일':'-'}</span></div><div style="margin-top:8px"><b>${Math.round(r.score)}점 · 좋은 자리</b></div><div class="result" style="margin-top:8px;padding:9px 10px"><b>추천 방식 · ${r.strategy_name}</b><br><span class="mut">${strategyExplain(r)}</span></div></div>`}

render=function(d){CUR=d;let rs=d.results||[];let holder=document.getElementById('todayStrategyTabs');if(!holder){holder=document.createElement('div');holder.id='todayStrategyTabs';$('grid').parentNode.insertBefore(holder,$('grid'))}holder.innerHTML=strategyTabsHtml(rs,TODAY_STRATEGY,'today');let show=filteredToday(rs,TODAY_STRATEGY);$('grid').innerHTML=show.length?show.map(todayCard).join(''):`<div class="strategy-empty" style="grid-column:1/-1">이 전략에서 오늘 S급 신호는 없어요.</div>`;$('status').className='status ok';$('status').textContent=`✓ S급 ${show.length}개 · Core 4.0 · UI v13.1 · 전체 스캔 ${fmt(d.scanned_at)}`;bindStrategyTabs()}
function bindStrategyTabs(){document.querySelectorAll('.strategy-tab[data-scope="today"]').forEach(b=>b.onclick=()=>{TODAY_STRATEGY=b.dataset.strategy;render(CUR)})}

openTicker=async function(s,sid){document.querySelector('[data-tab="one"]').click();$('ticker').value=s;let base=(CUR&&CUR.results||[]).find(x=>x.symbol===s);let r=base?viewForStrategy(base,sid||TODAY_STRATEGY):null;if(r)cachedDetailFromRow(r);else{$('oneStatus').className='status loading';$('oneStatus').textContent=s+' 불러오는 중…'}let strategy=(r&&r.strategy_id)||sid||'confirmed_pullback';try{let c=await j('/api/chart/'+encodeURIComponent(s)+'?strategy='+encodeURIComponent(strategy));if(c&&!c.error&&c.series){$('bigChart').innerHTML=drawChart(c);if(r){r.trade_plan=planNorm(c.trade_plan);cachedDetailFromRow(r);$('bigChart').innerHTML=drawChart(c)}}$('oneStatus').className='status ok';$('oneStatus').textContent='✓ '+s+' · '+(r?r.strategy_name:strategy)+' 최신 차트/매매계획 반영'}catch(e){$('oneStatus').className='status ok';$('oneStatus').textContent='✓ 저장된 추천 상세 표시 · 최신 차트 갱신 실패: '+e.message}}

function histFiltered(items,sid){let rows=(items||[]).filter(x=>x.grade==='S');if(sid==='all'){let best={};rows.forEach(x=>{if(!best[x.symbol]||Number(x.score||0)>Number(best[x.symbol].score||0))best[x.symbol]=x});return Object.values(best).sort((a,b)=>Number(b.score||0)-Number(a.score||0))}return rows.filter(x=>x.strategy_id===sid).sort((a,b)=>Number(b.score||0)-Number(a.score||0))}
function historyDaySection(day){let id='day_'+String(day.date).replace(/[^0-9]/g,''),items=day.items||[];let tabs=`<div class="day-strategy-wrap">${STRATEGIES.map(([sid,n])=>`<button class="strategy-tab ${sid==='all'?'on':''}" data-day="${id}" data-strategy="${sid}">${n}<span class="strategy-count">${histFiltered(items,sid).length}</span></button>`).join('')}</div>`;let cards=histFiltered(items,'all');return `<div class="history-day" id="${id}"><div class="head" style="margin-top:22px"><h2 style="font-size:18px">${day.date}</h2><div class="mut">S급 ${cards.length}종목</div></div>${tabs}<div class="grid day-grid">${cards.length?cards.map(historyCard).join(''):'<div class="strategy-empty" style="grid-column:1/-1">S급 추천이 없어요.</div>'}</div></div>`}
function bindDayTabs(dayMap){document.querySelectorAll('.strategy-tab[data-day]').forEach(b=>b.onclick=()=>{let wrap=document.getElementById(b.dataset.day),day=dayMap[b.dataset.day];wrap.querySelectorAll('.strategy-tab').forEach(x=>x.classList.toggle('on',x===b));let rows=histFiltered(day.items||[],b.dataset.strategy);wrap.querySelector('.day-grid').innerHTML=rows.length?rows.map(historyCard).join(''):'<div class="strategy-empty" style="grid-column:1/-1">이 전략에서 S급 추천이 없어요.</div>';wrap.querySelector('.head .mut').textContent=`S급 ${rows.length}종목`})}
HIST_PAGE=0;HIST_LOADING=false;HIST_MORE=true;window.__DAYMAP={};
loadHistory=async function(){if(HIST_LOADING||!HIST_MORE)return;HIST_LOADING=true;let s=$('historySentinel');if(s){s.className='status loading';s.textContent='이전 추천 기록 불러오는 중…'}try{let d=await j('/api/history?page='+HIST_PAGE+'&size=5');let sum=d.summary||{};let hs=$('historySummary');if(hs)hs.textContent=`누적 S신호 ${sum.total_signals||0}건 · 성공 ${sum.success||0} · 손절 ${sum.stop||0} · 목표미달 ${sum.target_miss||0}`;let wrap=$('historyDays');(d.days||[]).forEach(day=>{let key='day_'+String(day.date).replace(/[^0-9]/g,'');window.__DAYMAP[key]=day;let sec=document.createElement('div');sec.innerHTML=historyDaySection(day);wrap.appendChild(sec)});bindDayTabs(window.__DAYMAP);HIST_MORE=!!d.has_more;HIST_PAGE++;if(s){s.className='status';s.textContent=HIST_MORE?'아래로 내리면 이전 날짜를 더 불러옵니다.':'가장 오래된 기록까지 모두 불러왔어요.'}}catch(e){if(s){s.className='status err';s.textContent='기록 불러오기 실패 · '+e.message}}finally{HIST_LOADING=false}}
</script>
'''
    html=html.replace('</body>',js+'</body>')
    return Response(html,mimetype='text/html')

app.view_functions['index']=index_v13

@app.route('/api/version-v13')
def version_v13():return {'version':'13.1','core':'4.0','display':'S-only strategy tabs','chart':'strategy-aware shared-scale renderer','tabs':['종합','확인형 눌림반등','RSI2','모멘텀','돌파'],'journal':'symbol+strategy immutable S snapshots'}
