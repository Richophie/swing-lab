from __future__ import annotations

import re
from flask import jsonify, request, Response

from app_v13 import app, index_v13, _load, _norm_row, HISTORY_FILE
from app_v6 import CACHE_FILE, market_live
from app_v8 import load_df
from core_v4 import playbooks, trade_plan_for

PUBLIC_STRATEGIES = {
    'confirmed_pullback',
    'rsi2_trend_reversion',
    'momentum_pullback',
}
HIDDEN_EXPERIMENTAL = {'volatility_breakout'}


def _public_row(row):
    r = _norm_row(row)
    sigs = [s for s in (r.get('strategy_signals') or []) if s.get('strategy_id') in PUBLIC_STRATEGIES and float(s.get('strategy_score', 0)) >= 85]
    if not sigs:
        return None
    sigs.sort(key=lambda s: float(s.get('strategy_score', 0)), reverse=True)
    best = sigs[0]
    r['strategy_signals'] = sigs
    r['strategy_id'] = best.get('strategy_id')
    r['strategy_name'] = best.get('strategy_name')
    r['strategy_reason'] = best.get('evidence') or best.get('why')
    r['score'] = float(best.get('strategy_score', r.get('score', 0)))
    plans = r.get('strategy_trade_plans') or {}
    r['trade_plan'] = plans.get(r['strategy_id']) or r.get('trade_plan') or {}
    r['grade'] = 'S'
    return r


def latest_v14():
    data = _load(CACHE_FILE, {'status':'pending','results':[]})
    rows = []
    for raw in data.get('results') or []:
        r = _public_row(raw)
        if r is not None:
            rows.append(r)
    rows.sort(key=lambda x: float(x.get('score',0)), reverse=True)
    data['results'] = rows
    data['display_filter'] = 'S only / 3 public strategies; breakout hidden for validation'
    data['ui_version'] = '14.0'
    data['hidden_strategy'] = 'volatility_breakout'
    return jsonify(data)


def detail_v14(symbol):
    try:
        s = symbol.upper().strip()
        d = load_df(s, '10y')
        state = None
        try:
            state = market_live().get('state')
        except Exception:
            pass
        ens = playbooks(d, state)
        public = [q for q in ens.get('strategies', []) if q.get('id') in PUBLIC_STRATEGIES and q.get('active')]
        public.sort(key=lambda q: float(q.get('score',0)), reverse=True)
        best = public[0] if public else next((q for q in ens.get('strategies',[]) if q.get('id') in PUBLIC_STRATEGIES), ens.get('best_strategy'))
        sid = request.args.get('strategy') or (best or {}).get('id') or 'confirmed_pullback'
        if sid not in PUBLIC_STRATEGIES:
            sid = (best or {}).get('id') or 'confirmed_pullback'
        plan = trade_plan_for(d, sid)
        return jsonify({
            'symbol': s,
            'strategy_id': sid,
            'strategy_name': next((q.get('name') for q in ens.get('strategies',[]) if q.get('id') == sid), sid),
            'ensemble': ens,
            'trade_plan': plan,
            'signal': {'score': next((q.get('score') for q in ens.get('strategies',[]) if q.get('id') == sid), 0)},
            'market': market_live(),
        })
    except Exception as e:
        return jsonify({'error':str(e)}), 400


app.view_functions['latest'] = latest_v14
app.view_functions['detail'] = detail_v14


def index_v14():
    base = index_v13()
    html = base.get_data(as_text=True) if hasattr(base, 'get_data') else str(base)

    # Make visible version labels impossible to drift from the running UI version.
    html = re.sub(r'<title>.*?</title>', '<title>오늘의 스윙자리 · v14.0</title>', html, count=1, flags=re.S)
    html = re.sub(r'PRO LIVE v\d+(?:\.\d+)?', 'PRO LIVE v14.0', html)
    html = re.sub(r'오늘의 스윙자리(?:\s*[·v]\s*v?\d+(?:\.\d+)?)?', '오늘의 스윙자리', html, count=1)
    html = html.replace('S-CLASS STRATEGY BOARD', 'S-CLASS STRATEGY BOARD · 3 STRATEGIES')

    # Always reserve a physical slot for today's tabs instead of relying on a race-prone dynamic insertion.
    if 'id="todayStrategyTabs"' not in html:
        html = html.replace('<div id="grid" class="grid"></div>', '<div id="todayStrategyTabs"></div><div id="grid" class="grid"></div>', 1)

    css = '''<style>
    .exp-note{margin-top:8px;padding:10px 12px;border-radius:12px;background:#f7f7f5;color:var(--mut);font-size:11px;line-height:1.5}
    .calc-disabled{color:var(--mut);background:#f7f7f5}
    </style>'''
    html = html.replace('</head>', css + '</head>')

    js = r'''
<script>
const TODAY_PUBLIC_STRATEGIES=[['all','종합'],['confirmed_pullback','확인형 눌림반등'],['rsi2_trend_reversion','RSI2'],['momentum_pullback','모멘텀']];
function publicSignals(r){return (sSignals(r)||[]).filter(x=>x.strategy_id!=='volatility_breakout')}
filteredToday=function(rows,sid){let out=[];(rows||[]).forEach(r=>{let sigs=publicSignals(r);let sig=sid==='all'?sigs.slice().sort((a,b)=>Number(b.strategy_score)-Number(a.strategy_score))[0]:sigs.find(x=>x.strategy_id===sid);if(!sig)return;let plans=r.strategy_trade_plans||{},p=planNorm(plans[sig.strategy_id]||r.trade_plan||{});out.push({...r,score:Number(sig.strategy_score||0),strategy_id:sig.strategy_id,strategy_name:sig.strategy_name,strategy_reason:sig.evidence||sig.why,trade_plan:p,grade:'S'})});out.sort((a,b)=>b.score-a.score);if(sid==='all'){let seen=new Set();out=out.filter(r=>{if(seen.has(r.symbol))return false;seen.add(r.symbol);return true})}return out}
strategyTabsHtml=function(rows,active,scope){let list=scope==='today'?TODAY_PUBLIC_STRATEGIES:STRATEGIES;return `<div class="strategy-tabs">${list.map(([id,n])=>{let c=scope==='today'?filteredToday(rows,id).length:0;return `<button class="strategy-tab ${active===id?'on':''}" data-scope="${scope}" data-strategy="${id}">${n}${scope==='today'?`<span class="strategy-count">${c}</span>`:''}</button>`}).join('')}</div>${scope==='today'?'<div class="exp-note">돌파 전략은 현재 메인 추천에서 숨김 · 과거 기록에서는 검증용으로 계속 추적합니다.</div>':''}`}

function safePlan(p){p=planNorm(p||{});let vals=['entry_low','entry_high','target','stop'];for(const k of vals){let n=Number(p[k]);p[k]=Number.isFinite(n)?n:null}return p}
function planReady(p){p=safePlan(p);return [p.entry_low,p.entry_high,p.target,p.stop].every(v=>Number.isFinite(v))}

const _oldCachedDetail=cachedDetailFromRow;
cachedDetailFromRow=function(r){r={...r,trade_plan:safePlan(r.trade_plan)};_oldCachedDetail(r);let p=r.trade_plan||{};if(!planReady(p)){$('entry').textContent='계산 준비 중';$('target').textContent='—';$('stop').textContent='—';$('capitalOut').className='result calc-disabled';$('capitalOut').textContent='BUY 가격이 확인되면 계산합니다.';$('wantOut').className='result calc-disabled';$('wantOut').textContent='BUY 가격이 확인되면 계산합니다.';}}

const _oldCalc=calc;
calc=function(){if(!DETAIL||!planReady(DETAIL.trade_plan)){$('capitalOut').className='result calc-disabled';$('capitalOut').textContent='BUY 가격이 확인되면 계산합니다.';$('wantOut').className='result calc-disabled';$('wantOut').textContent='BUY 가격이 확인되면 계산합니다.';return}_oldCalc()}

render=function(d){CUR=d;let rs=d.results||[];if(TODAY_STRATEGY==='volatility_breakout')TODAY_STRATEGY='all';let holder=document.getElementById('todayStrategyTabs');holder.innerHTML=strategyTabsHtml(rs,TODAY_STRATEGY,'today');let show=filteredToday(rs,TODAY_STRATEGY);$('grid').innerHTML=show.length?show.map(todayCard).join(''):`<div class="strategy-empty" style="grid-column:1/-1">이 전략에서 오늘 S급 신호는 없어요.</div>`;$('status').className='status ok';$('status').textContent=`✓ S급 ${show.length}개 · Core 4.0 · UI v14.0 · 전체 스캔 ${fmt(d.scanned_at)}`;bindStrategyTabs()}

setTimeout(()=>{if(CUR)render(CUR)},50);
</script>
'''
    html = html.replace('</body>', js + '</body>')
    return Response(html, mimetype='text/html')


app.view_functions['index'] = index_v14


@app.route('/api/version-v14')
def version_v14():
    return {
        'version':'14.0',
        'core':'4.0',
        'public_strategies':['confirmed_pullback','rsi2_trend_reversion','momentum_pullback'],
        'experimental_hidden':['volatility_breakout'],
        'policy':'breakout remains in raw scan/journal for validation but is excluded from public today/combined recommendations',
    }
