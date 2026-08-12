from pathlib import Path
import json
from flask import jsonify, request, Response

from app_v11 import app, index_v11, _strategy_fallback
from app_v6 import CACHE_FILE

HISTORY_FILE=Path(__file__).parent/'static'/'trade_history.json'


def _load(path,default):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception:return default


def latest_v13():
    data=_load(CACHE_FILE,{'status':'pending','results':[]})
    rows=[_strategy_fallback(r) for r in (data.get('results') or [])]
    data['results']=[r for r in rows if r.get('grade')=='S' and r.get('eligible',True)]
    data['display_filter']='S only / strategy tabs'
    return jsonify(data)


def history_v13():
    data=_load(HISTORY_FILE,{'days':[],'summary':{}});days=data.get('days') or []
    try:page=max(0,int(request.args.get('page',0)))
    except Exception:page=0
    try:size=min(10,max(1,int(request.args.get('size',5))))
    except Exception:size=5
    start=page*size;end=start+size
    return jsonify({'version':data.get('version'),'updated_at':data.get('updated_at'),'summary':data.get('summary') or {},'days':days[start:end],'page':page,'size':size,'has_more':end<len(days),'total_days':len(days)})

app.view_functions['latest']=latest_v13
app.view_functions['history_v11']=history_v13


def index_v13():
    base=index_v11();html=base.get_data(as_text=True) if hasattr(base,'get_data') else str(base)
    html=html.replace('PRO LIVE v11.1','PRO LIVE v13.0').replace('DAILY SIGNAL JOURNAL','S-CLASS STRATEGY BOARD')
    css='''<style>.strategy-tabs{display:flex;gap:6px;flex-wrap:wrap;margin:14px 0 4px}.strategy-tab{border:1px solid var(--line);background:#fff;border-radius:999px;padding:8px 11px;font-size:11px;font-weight:800;cursor:pointer}.strategy-tab.on{background:#111;color:#fff;border-color:#111}.strategy-count{opacity:.55;margin-left:3px}.day-strategy-wrap{margin-top:8px}.strategy-empty{padding:28px 12px;text-align:center;color:var(--mut);font-size:12px}</style>'''
    html=html.replace('</head>',css+'</head>')
    js=r'''
<script>
const STRATEGIES=[['all','종합'],['confirmed_pullback','확인형 눌림반등'],['rsi2_trend_reversion','RSI2'],['momentum_pullback','모멘텀'],['volatility_breakout','돌파']];
let TODAY_STRATEGY='all';
function sSignals(r){let a=r.strategy_signals||[];if(!a.length&&r.grade==='S')a=[{strategy_id:r.strategy_id,strategy_name:r.strategy_name,strategy_score:r.score,why:r.strategy_reason,evidence:r.strategy_reason}];return a.filter(x=>Number(x.strategy_score||0)>=85)}
function viewForStrategy(r,sid){let sigs=sSignals(r),sig=sid==='all'?sigs.slice().sort((a,b)=>Number(b.strategy_score)-Number(a.strategy_score))[0]:sigs.find(x=>x.strategy_id===sid);if(!sig)return null;let plans=r.strategy_trade_plans||{},p=plans[sig.strategy_id]||r.trade_plan||{};return {...r,score:Number(sig.strategy_score||r.score||0),strategy_id:sig.strategy_id,strategy_name:sig.strategy_name||r.strategy_name,strategy_reason:sig.evidence||sig.why||r.strategy_reason,trade_plan:p,grade:'S'}}
function filteredToday(rows,sid){let out=(rows||[]).map(r=>viewForStrategy(r,sid)).filter(Boolean);let seen=new Set();out=out.sort((a,b)=>b.score-a.score).filter(r=>{if(sid!=='all')return true;if(seen.has(r.symbol))return false;seen.add(r.symbol);return true});return out}
function strategyTabsHtml(rows,active,scope){return `<div class="strategy-tabs">${STRATEGIES.map(([id,n])=>{let c=filteredToday(rows,id).length;return `<button class="strategy-tab ${active===id?'on':''}" data-scope="${scope}" data-strategy="${id}">${n}<span class="strategy-count">${c}</span></button>`}).join('')}</div>`}
function todayCard(r,i){let p=r.trade_plan||{},e=p.target_days||{};return `<div class="pick" onclick="openTicker('${r.symbol}')"><div class="picktop"><div><div class="mut">#${i+1}</div><div class="ticker">${r.symbol}</div></div><div class="grade good">S</div></div><div class="chartmini">${mini(r)}</div><div class="levels"><div>BUY<b>$${p.entry_low??p.buy_low??'-'}~${p.entry_high??p.buy_high??'-'}</b></div><div>TARGET<b>$${p.target??'-'}</b></div><div>STOP<b>$${p.stop??'-'}</b></div></div><div class="metrics"><span>RSI ${r.rsi??'-'}</span><span>120일선 ${r.d120??'-'}%</span><span>볼린저 ${r.bb_pos??'-'}%</span><span>${e.days_low?e.days_low+'~'+e.days_high+'일':(p.days_min?p.days_min+'~'+p.days_max+'일':'-')}</span></div><div style="margin-top:8px"><b>${Math.round(r.score)}점 · 좋은 자리</b></div><div class="result" style="margin-top:8px;padding:9px 10px"><b>추천 방식 · ${r.strategy_name}</b><br><span class="mut">${strategyExplain(r)}</span></div></div>`}
render=function(d){CUR=d;let rs=d.results||[];let holder=document.getElementById('todayStrategyTabs');if(!holder){holder=document.createElement('div');holder.id='todayStrategyTabs';$('grid').parentNode.insertBefore(holder,$('grid'))}holder.innerHTML=strategyTabsHtml(rs,TODAY_STRATEGY,'today');let show=filteredToday(rs,TODAY_STRATEGY);$('grid').innerHTML=show.length?show.map(todayCard).join(''):`<div class="strategy-empty" style="grid-column:1/-1">이 전략에서 오늘 S급 신호는 없어요.</div>`;$('status').className='status ok';$('status').textContent=`✓ S급 ${show.length}개 · 전체 스캔 ${fmt(d.scanned_at)}${d.live_refreshed_at?' · 실시간 '+fmt(d.live_refreshed_at):''}`;bindStrategyTabs()}
function bindStrategyTabs(){document.querySelectorAll('.strategy-tab[data-scope="today"]').forEach(b=>b.onclick=()=>{TODAY_STRATEGY=b.dataset.strategy;render(CUR)})}
function histFiltered(items,sid){let rows=(items||[]).filter(x=>x.grade==='S');if(sid==='all'){let best={};rows.forEach(x=>{if(!best[x.symbol]||Number(x.score||0)>Number(best[x.symbol].score||0))best[x.symbol]=x});return Object.values(best).sort((a,b)=>Number(b.score||0)-Number(a.score||0))}return rows.filter(x=>x.strategy_id===sid).sort((a,b)=>Number(b.score||0)-Number(a.score||0))}
function historyDaySection(day){let id='day_'+String(day.date).replace(/[^0-9]/g,'');let active='all';let items=day.items||[];let tabs=`<div class="day-strategy-wrap">${STRATEGIES.map(([sid,n])=>`<button class="strategy-tab ${sid==='all'?'on':''}" data-day="${id}" data-strategy="${sid}">${n}<span class="strategy-count">${histFiltered(items,sid).length}</span></button>`).join('')}</div>`;let cards=histFiltered(items,'all');return `<div class="history-day" id="${id}"><div class="head" style="margin-top:22px"><h2 style="font-size:18px">${day.date}</h2><div class="mut">S급 ${cards.length}종목</div></div>${tabs}<div class="grid day-grid">${cards.length?cards.map(historyCard).join(''):'<div class="strategy-empty" style="grid-column:1/-1">S급 추천이 없어요.</div>'}</div></div>`}
function bindDayTabs(dayMap){document.querySelectorAll('.strategy-tab[data-day]').forEach(b=>b.onclick=()=>{let wrap=document.getElementById(b.dataset.day),day=dayMap[b.dataset.day];wrap.querySelectorAll('.strategy-tab').forEach(x=>x.classList.toggle('on',x===b));let rows=histFiltered(day.items||[],b.dataset.strategy);wrap.querySelector('.day-grid').innerHTML=rows.length?rows.map(historyCard).join(''):'<div class="strategy-empty" style="grid-column:1/-1">이 전략에서 S급 추천이 없어요.</div>';wrap.querySelector('.head .mut').textContent=`S급 ${rows.length}종목`})}
HIST_PAGE=0;HIST_LOADING=false;HIST_MORE=true;window.__DAYMAP={};
loadHistory=async function(){if(HIST_LOADING||!HIST_MORE)return;HIST_LOADING=true;let s=$('historySentinel');if(s){s.className='status loading';s.textContent='이전 추천 기록 불러오는 중…'}try{let d=await j('/api/history?page='+HIST_PAGE+'&size=5');let sum=d.summary||{};let hs=$('historySummary');if(hs)hs.textContent=`누적 S신호 ${sum.total_signals||0}건 · 성공 ${sum.success||0} · 손절 ${sum.stop||0} · 목표미달 ${sum.target_miss||0}`;let wrap=$('historyDays');(d.days||[]).forEach(day=>{let key='day_'+String(day.date).replace(/[^0-9]/g,'');window.__DAYMAP[key]=day;let sec=document.createElement('div');sec.innerHTML=historyDaySection(day);wrap.appendChild(sec)});bindDayTabs(window.__DAYMAP);HIST_MORE=!!d.has_more;HIST_PAGE++;if(s){s.className='status';s.textContent=HIST_MORE?'아래로 내리면 이전 날짜를 더 불러옵니다.':'가장 오래된 기록까지 모두 불러왔어요.'}}catch(e){if(s){s.className='status err';s.textContent='기록 불러오기 실패 · '+e.message}}finally{HIST_LOADING=false}}
</script>
'''
    html=html.replace('</body>',js+'</body>')
    return Response(html,mimetype='text/html')

app.view_functions['index']=index_v13

@app.route('/api/version-v13')
def version_v13():
    return {'version':'13.0','core':'4.0','display':'S-only strategy tabs','tabs':['종합','확인형 눌림반등','RSI2','모멘텀','돌파'],'journal':'symbol+strategy immutable S snapshots'}
