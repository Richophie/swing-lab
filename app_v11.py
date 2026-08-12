from pathlib import Path
import json
from flask import jsonify, request, Response

from app_v10 import app, index_v10
from app_v6 import CACHE_FILE

HISTORY_FILE = Path(__file__).parent / 'static' / 'trade_history.json'


def _load(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def _strategy_fallback(row):
    """Old v9-era cache rows were produced only by the confirmed-pullback core."""
    if row.get('strategy_name'):
        return row
    row = dict(row)
    row['strategy_name'] = '확인형 눌림반등'
    row['strategy_id'] = 'confirmed_pullback'
    row['strategy_reason'] = row.get('strategy_reason') or '가격이 충분히 눌린 뒤 반전 여부를 확인하는 기존 코어 전략입니다.'
    row['strategy_agreement'] = row.get('strategy_agreement') or 1
    return row


def latest_v11():
    data = _load(CACHE_FILE, {'status': 'pending', 'results': []})
    rows = [_strategy_fallback(r) for r in (data.get('results') or [])]
    data['results'] = [r for r in rows if r.get('grade') in {'S', 'A'} and r.get('eligible', True)]
    data['version'] = '11.1'
    data['display_filter'] = 'A/S only'
    return jsonify(data)


@app.route('/api/history')
def history_v11():
    data = _load(HISTORY_FILE, {'days': [], 'summary': {}})
    days = data.get('days') or []
    for day in days:
        day['items'] = [_strategy_fallback(x) for x in (day.get('items') or [])]
    try: page = max(0, int(request.args.get('page', 0)))
    except Exception: page = 0
    try: size = min(10, max(1, int(request.args.get('size', 5))))
    except Exception: size = 5
    start = page * size; end = start + size
    return jsonify({
        'version': data.get('version'), 'updated_at': data.get('updated_at'), 'summary': data.get('summary') or {},
        'days': days[start:end], 'page': page, 'size': size, 'has_more': end < len(days), 'total_days': len(days)
    })


app.view_functions['latest'] = latest_v11


def index_v11():
    base = index_v10()
    html = base.get_data(as_text=True) if hasattr(base, 'get_data') else str(base)
    html = html.replace('PRO LIVE v10.2', 'PRO LIVE v11.1').replace('MULTI-STRATEGY ROUTER', 'DAILY SIGNAL JOURNAL')

    history_block = '''<div class="card" id="historyWrap"><div class="head"><div><div class="mut">추천 기록</div><h2>지난 추천도 그대로 남겨둬요</h2></div><div id="historySummary" class="mut">기록을 불러오는 중…</div></div><p class="mut">추천 당시의 BUY·TARGET·STOP과 전략을 고정 저장하고, 이후 결과만 업데이트합니다.</p><div id="historyDays"></div><div id="historySentinel" class="status">아래로 내리면 이전 날짜를 더 불러옵니다.</div></div>'''
    html = html.replace('</div></section><section id="one"', '</div>' + history_block + '</section><section id="one"', 1)

    helpers = r'''
function strategyExplain(x){let id=x.strategy_id||'';if(id==='confirmed_pullback')return '충분히 눌린 뒤 실제 반전 신호가 나타나기 시작한 자리';if(id==='rsi2_trend_reversion')return '큰 상승추세 안에서 단기적으로 과하게 빠진 반등 자리';if(id==='momentum_pullback')return '원래 강했던 종목이 잠깐 쉬었다가 다시 힘을 받는 자리';if(id==='volatility_breakout')return '움직임이 조용해진 뒤 고점을 뚫기 시작한 돌파 자리';return x.strategy_reason||'당시 가장 강했던 매수 전략';}
function outcomeText(x){let r=x.outcome_return_pct, pct=(r==null?'':` (${r>=0?'+':''}${Number(r).toFixed(2)}%)`);if(x.status_code==='SUCCESS')return '성공'+pct;if(x.status_code==='STOP')return '손절'+pct;if(String(x.status_code||'').startsWith('EXPIRED'))return '목표미달'+pct;return '진행중';}
function outcomeClass(x){if(x.status_code==='SUCCESS')return 'good';if(x.status_code==='STOP'||x.status_code==='EXPIRED_LOSS')return 'bad';if(String(x.status_code||'').startsWith('EXPIRED'))return 'warn';return '';}
function historyCard(x){let p={entry_low:x.entry_low,entry_high:x.entry_high,target:x.target,stop:x.stop},r={sparkline:x.sparkline||[],trade_plan:p};return `<div class="pick"><div class="picktop"><div><div class="ticker">${x.symbol}</div><div class="mut">${x.strategy_name||'확인형 눌림반등'}</div></div><div style="text-align:right"><div class="grade ${x.grade==='S'?'good':'warn'}">${x.grade}</div><b class="${outcomeClass(x)}">${outcomeText(x)}</b></div></div><div class="chartmini">${mini(r)}</div><div class="levels"><div>BUY<b>$${x.entry_low??'-'}~${x.entry_high??'-'}</b></div><div>TARGET<b>$${x.target??'-'}</b></div><div>STOP<b>$${x.stop??'-'}</b></div></div><div class="metrics"><span>RSI ${x.rsi??'-'}</span><span>120일선 ${x.d120??'-'}%</span><span>볼린저 ${x.bb_pos??'-'}%</span><span>목표 ${x.target_days_low??'-'}~${x.target_days_high??'-'}일</span></div><div class="result" style="margin-top:8px;padding:9px 10px"><b>추천 방식 · ${x.strategy_name||'확인형 눌림반등'}</b><br><span class="mut">${strategyExplain(x)}</span></div>${x.outcome_note?`<div class="e" style="margin-top:7px">${x.outcome_note}</div>`:''}</div>`;}

function cachedDetailFromRow(r){let p=r.trade_plan||{};let e=p.target_days||{};DETAIL={symbol:r.symbol,signal:r,trade_plan:p,usdkrw:1350,ensemble:r.ensemble||null};lastSymbol=r.symbol;$('detail').style.display='block';$('decision').textContent=r.symbol+' · '+r.grade+' · '+gt(r.grade);$('score').textContent=Math.round(r.score||0);$('entry').textContent='$'+(p.entry_low??'-')+' ~ $'+(p.entry_high??'-');$('target').textContent='$'+(p.target??'-')+(p.target_pct!=null?' (+'+p.target_pct+'%)':'');$('targetWhy').textContent=p.target_reason||'';$('eta').textContent=e.days_low?e.days_low+'~'+e.days_high+' 거래일':'—';$('etaWhy').textContent=e.method||'';$('stop').textContent='$'+(p.stop??'-')+(p.stop_pct!=null?' (-'+p.stop_pct+'%)':'');$('stopWhy').textContent=p.stop_reason||'';let nm=r.strategy_name||'확인형 눌림반등';$('detailMetrics').innerHTML=`<b>추천 방식 · ${nm}</b><br>${strategyExplain(r)}<br><br><b>지금 자리를 쉽게 보면</b><br>• RSI ${r.rsi??'-'}${r.rsi!=null?' → '+rsiText(r.rsi):''}<br>• 120일선 ${r.d120??'-'}%${r.d120!=null?' → '+maText(r.d120):''}<br>• 볼린저 ${r.bb_pos??'-'}%${r.bb_pos!=null?' → '+bbText(r.bb_pos):''}${p.risk_reward!=null?'<br>• 손익비 1:'+p.risk_reward:''}`;let series=(r.sparkline||[]).map(v=>({close:v,sma120:null,bb_low:null,bb_high:null,rsi:null}));if(series.length&&p.target&&p.stop){$('bigChart').innerHTML=drawChart({series:series,trade_plan:p})}else{$('bigChart').innerHTML='<div class="status">차트 상세 데이터를 불러오는 중…</div>'}$('oneStatus').className='status ok';$('oneStatus').textContent='✓ 저장된 최신 추천 기준으로 바로 열었습니다. 최신 차트는 뒤에서 확인 중…';calc();}

openTicker=async function(s){document.querySelector('[data-tab="one"]').click();$('ticker').value=s;let r=(CUR&&CUR.results||[]).find(x=>x.symbol===s);if(r)cachedDetailFromRow(r);else{$('oneStatus').className='status loading';$('oneStatus').textContent=s+' 불러오는 중…'}try{let c=await j('/api/chart/'+encodeURIComponent(s));if(c&&!c.error&&c.series){$('bigChart').innerHTML=drawChart(c)}$('oneStatus').className='status ok';$('oneStatus').textContent='✓ '+s+' 상세 화면 · 최신 차트 반영 완료'}catch(e){$('oneStatus').className='status ok';$('oneStatus').textContent='✓ '+s+' 추천 상세를 표시했습니다. 최신 차트 갱신은 다음 확인 때 다시 시도합니다.'}}

let HIST_PAGE=0,HIST_LOADING=false,HIST_MORE=true;
async function loadHistory(){if(HIST_LOADING||!HIST_MORE)return;HIST_LOADING=true;let s=$('historySentinel');if(s){s.className='status loading';s.textContent='이전 추천 기록 불러오는 중…'}try{let d=await j('/api/history?page='+HIST_PAGE+'&size=5');let sum=d.summary||{};let hs=$('historySummary');if(hs)hs.textContent=`누적 ${sum.total_signals||0}건 · 성공 ${sum.success||0} · 손절 ${sum.stop||0} · 목표미달 ${sum.target_miss||0}`;let wrap=$('historyDays');(d.days||[]).forEach(day=>{let sec=document.createElement('div');sec.innerHTML=`<div class="head" style="margin-top:22px"><h2 style="font-size:18px">${day.date}</h2><div class="mut">${(day.items||[]).length}개 추천</div></div><div class="grid">${(day.items||[]).map(historyCard).join('')}</div>`;wrap.appendChild(sec)});HIST_MORE=!!d.has_more;HIST_PAGE++;if(s){s.className='status';s.textContent=HIST_MORE?'아래로 내리면 이전 날짜를 더 불러옵니다.':'가장 오래된 기록까지 모두 불러왔어요.'}}catch(e){if(s){s.className='status err';s.textContent='기록 불러오기 실패 · '+e.message}}finally{HIST_LOADING=false}}
const histObserver=new IntersectionObserver(es=>{if(es.some(e=>e.isIntersecting))loadHistory()},{rootMargin:'500px'});
setTimeout(()=>{let s=$('historySentinel');if(s)histObserver.observe(s);loadHistory()},100);
'''
    html = html.replace('cached();</script>', 'cached();' + helpers + '</script>')
    html = html.replace("4개 전략 중 ${en.agreement}개가 현재 매수 신호 · 확신도 ${en.confidence}", "현재 매수 신호 · ${en.best_strategy.name} | ${friendlyEnsemble(en)}")
    return Response(html, mimetype='text/html')


app.view_functions['index'] = index_v11


@app.route('/api/version-v11')
def version_v11():
    return {'version': '11.1', 'features': ['A/S-only public dashboard', 'strategy name always available', 'instant card-to-detail rendering', 'lazy chart refresh', 'immutable daily recommendation snapshots', 'infinite date history', 'success/stop/target-miss outcome tracking']}
