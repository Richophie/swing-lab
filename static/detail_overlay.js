(()=>{
  const PAPER_CLIENT_KEY='swingLabPaperClientV1';
  let paperSnapshot=null;

  function esc(value){return String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]))}
  function num(value){const n=Number(value);return Number.isFinite(n)?n:null}
  function krw(value){const n=num(value);return n==null?'—':`${Math.round(n).toLocaleString('ko-KR')}원`}
  function usd(value){const n=num(value);return n==null?'—':`$${n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}`}
  function paperClientId(){
    let id=localStorage.getItem(PAPER_CLIENT_KEY);
    if(!id){id=(window.crypto&&crypto.randomUUID)?crypto.randomUUID():`paper-${Date.now()}-${Math.random().toString(16).slice(2)}`;localStorage.setItem(PAPER_CLIENT_KEY,id)}
    return id;
  }
  async function apiJSON(url,options={}){
    const headers={...(options.headers||{}),'X-Paper-Client':paperClientId()};
    if(options.body&&!headers['Content-Type'])headers['Content-Type']='application/json';
    const response=await fetch(url,{cache:'no-store',...options,headers});
    const text=await response.text();let data;
    try{data=JSON.parse(text)}catch{throw new Error('서버 응답 형식 오류')}
    if(!response.ok||data.error)throw new Error(data.error||`서버 ${response.status}`);
    return data;
  }
  function injectStyles(){
    if(document.getElementById('paperUiStyles'))return;
    const style=document.createElement('style');style.id='paperUiStyles';style.textContent=`
      .pick .reason>span{display:none!important}
      .live-mode-banner{display:flex;gap:12px;align-items:flex-start;margin:0 0 18px;padding:14px 16px;border:1px solid #e3e8e6;background:#f8faf9;border-radius:16px;color:#64706b;font-size:12px;line-height:1.55}.live-mode-badge{flex:0 0 auto;padding:4px 8px;border-radius:999px;background:#17201d;color:#fff;font-size:9px;font-weight:900;letter-spacing:.08em}.live-mode-banner b{display:block;color:#222a27;font-size:13px;margin-bottom:2px}
      .signal-log{display:grid;gap:8px}.signal-event{display:grid;grid-template-columns:64px 1fr auto;gap:12px;align-items:center;padding:11px 0;border-bottom:1px solid #edf0ef}.signal-event:last-child{border-bottom:0}.signal-event .event-badge{font-size:10px;font-weight:900;border-radius:999px;padding:5px 8px;text-align:center;background:#eef5f1;color:#207355}.signal-event.exit .event-badge{background:#f1f2f4;color:#7a8189}.signal-event b{font-size:13px}.signal-event small{display:block;color:#91989f;margin-top:3px;line-height:1.4}.signal-event time{font-size:10px;color:#9ba1a7;white-space:nowrap}
      .detail-insight{margin:18px 0 6px;padding:18px;border:1px solid #e8ebee;border-radius:18px;background:#fafbfc}.detail-insight-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:13px}.detail-insight-head h3{font-size:15px;margin:0}.detail-insight-head span{font-size:10px;color:#989fa6}.detail-insight-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.detail-insight-card{padding:13px 14px;background:#fff;border:1px solid #eceff1;border-radius:14px}.detail-insight-card b{display:block;font-size:11px;margin-bottom:5px;color:#30363b}.detail-insight-card p{margin:0;color:#687078;font-size:12px;line-height:1.6}.detail-insight-note{margin-top:10px;font-size:10px;color:#939aa1;line-height:1.55}
      .paper-buy{border:0;border-radius:12px;background:#151917;color:#fff;padding:10px 14px;font-size:12px;font-weight:850;cursor:pointer}.paper-buy:disabled{opacity:.38;cursor:not-allowed}.paper-detail-message{display:none;margin:10px 0;padding:10px 12px;border-radius:12px;background:#f5f7f6;color:#56615c;font-size:11px}.paper-detail-message.show{display:block}.paper-detail-message.err{background:#fff4f4;color:#a04444}
      .paper-head-note{font-size:11px;color:#8d959b;line-height:1.55;max-width:560px}.paper-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:18px 0}.paper-stat{padding:15px;border:1px solid #e8ebee;border-radius:16px;background:#fff}.paper-stat span{display:block;color:#929aa1;font-size:10px;margin-bottom:5px}.paper-stat b{font-size:17px;letter-spacing:-.04em}.paper-actions{display:flex;gap:8px;flex-wrap:wrap}.paper-orders{display:grid;gap:10px}.paper-order{padding:16px;border:1px solid #e8ebee;border-radius:17px;background:#fff}.paper-order-top{display:flex;justify-content:space-between;gap:12px}.paper-order-name{font-weight:850;font-size:14px}.paper-order-sub{font-size:10px;color:#929aa1;margin-top:3px}.paper-status{font-size:10px;font-weight:900;border-radius:999px;padding:5px 8px;height:max-content;background:#f0f2f3;color:#727a82}.paper-status.filled{background:#eaf6f0;color:#1d7c58}.paper-status.closed{background:#eef2fa;color:#4c66a2}.paper-status.cancelled{background:#f4f4f5;color:#8a8f94}.paper-order-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:13px}.paper-order-grid span{display:block;font-size:9px;color:#9ba1a7;margin-bottom:3px}.paper-order-grid b{font-size:11px}.paper-pnl.up{color:#b33c3c}.paper-pnl.down{color:#3569b5}.paper-empty{padding:24px;border:1px dashed #dfe4e2;border-radius:16px;color:#8b9398;font-size:12px;text-align:center}
      @media(max-width:720px){.detail-insight-grid{grid-template-columns:1fr}.paper-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.paper-order-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.signal-event{grid-template-columns:56px 1fr}.signal-event time{grid-column:2}}
    `;document.head.appendChild(style);
  }
  function isDetailOpen(detail){return !!detail&&(detail.classList.contains('show')||detail.style.display==='block')}
  function closeDetail(){
    const overlay=document.getElementById('detailOverlay');
    const detail=document.getElementById('detail');
    if(detail){detail.classList.remove('show');detail.style.display='none'}
    if(overlay){overlay.classList.remove('open');overlay.setAttribute('aria-hidden','true')}
    document.body.classList.remove('detail-open');
  }
  function openShell(){
    const overlay=document.getElementById('detailOverlay');
    const detail=document.getElementById('detail');
    if(!overlay||!isDetailOpen(detail))return;
    overlay.classList.add('open');overlay.setAttribute('aria-hidden','false');document.body.classList.add('detail-open');overlay.scrollTop=0;
  }
  function rsiCopy(v){const n=num(v);if(n==null)return'RSI 데이터가 없습니다.';if(n<30)return`RSI ${n.toFixed(1)}로 단기 과매도가 강합니다. 반등 여지는 커지지만 하락 추세가 진행 중일 수도 있어 확인이 필요합니다.`;if(n<40)return`RSI ${n.toFixed(1)}로 매도 압력이 꽤 누적된 구간입니다. RSI2 눌림 전략이 선호하는 쪽에 가깝습니다.`;if(n<50)return`RSI ${n.toFixed(1)}로 중립 아래입니다. 과열은 아니지만 과매도 강도는 아주 세지 않습니다.`;return`RSI ${n.toFixed(1)}로 단기 과매도보다는 중립·강세 쪽에 가깝습니다.`}
  function trendCopy(v){const n=num(v);if(n==null)return'120일선 거리 데이터가 없습니다.';const abs=Math.abs(n).toFixed(2);if(Math.abs(n)<=2)return`현재가는 120일선에서 ${abs}% 거리라 장기 추세선 바로 근처입니다. ${n>=0?'추세선 위에서 지지를 시험하는':'추세선 아래로 살짝 밀려 회복 여부를 보는'} 자리입니다.`;if(n>2)return`120일선보다 ${abs}% 위에 있어 장기 상승 흐름은 유지되는 편입니다. 다만 멀어질수록 눌림 매력은 줄어듭니다.`;return`120일선보다 ${abs}% 아래입니다. 싸 보일 수 있지만 장기 추세 훼손 가능성도 함께 봐야 합니다.`}
  function bbCopy(v){const n=num(v);if(n==null)return'볼린저 위치 데이터가 없습니다.';if(n<=10)return`볼린저 밴드 위치 ${n.toFixed(1)}%로 하단에 매우 가깝습니다. 최근 가격이 통계적으로 낮은 쪽에 몰린 눌림입니다.`;if(n<=30)return`볼린저 위치 ${n.toFixed(1)}%로 밴드 하단부입니다. 눌림은 있지만 극단적인 수준은 아닙니다.`;if(n>=80)return`볼린저 위치 ${n.toFixed(1)}%로 상단부라 단기 추격 위험을 더 봐야 합니다.`;return`볼린저 위치 ${n.toFixed(1)}%로 밴드 중간권입니다.`}
  function rrCopy(p){const rr=num(p?.risk_reward),tp=num(p?.target_pct),sp=num(p?.stop_pct);if(rr==null)return'손익비 데이터가 없습니다.';const quality=rr>=1.8?'여유가 좋은 편':rr>=1.4?'무난한 편':'통과는 가능하지만 넉넉하진 않은 편';return`계획 손익비는 1:${rr.toFixed(2)}로 ${quality}입니다.${tp!=null&&sp!=null?` 목표 약 +${Math.abs(tp).toFixed(2)}%, 손절 약 -${Math.abs(sp).toFixed(2)}%를 전제로 합니다.`:''}`}
  function flowCopy(f){
    const rv=num(f?.relative_volume),v5=num(f?.volume_5d_vs_20d??f?.volume_5_20),ud=num(f?.up_down_volume_ratio),rev=num(f?.reversal_volume);
    const bits=[];if(rv!=null)bits.push(`상대거래량 ${rv.toFixed(2)}배`);if(v5!=null)bits.push(`5일/20일 거래량 ${v5.toFixed(2)}배`);if(ud!=null)bits.push(`상승/하락 거래량 ${ud.toFixed(2)}배`);if(rev!=null&&rev>0)bits.push(`반전일 거래량 ${rev.toFixed(2)}배`);
    if(!bits.length)return'거래량 보조지표가 저장되지 않은 신호입니다.';
    let tail='';if(ud!=null)tail=ud>=1.15?' 상승일 쪽 거래량이 상대적으로 우세합니다.':ud<.75?' 하락일 거래량이 더 강해 수급 확인이 필요합니다.':' 상승·하락 거래량은 크게 한쪽으로 기울지 않았습니다.';
    return `${bits.join(' · ')}.${tail}`;
  }
  function renderDetailExplanation(d){
    const host=document.getElementById('detailExplain');if(!host||!d)return;
    const p=d.trade_plan||{},s=d.signal||{},f=d.flow||{};
    host.innerHTML=`<div class="detail-insight-head"><div><h3>이 자리를 어떻게 읽었는지</h3><span>점수는 성공확률이 아니라 현재 조건의 적합도 순위입니다.</span></div></div><div class="detail-insight-grid"><div class="detail-insight-card"><b>단기 과매도 · RSI</b><p>${esc(rsiCopy(s.rsi))}</p></div><div class="detail-insight-card"><b>장기 추세 · 120일선</b><p>${esc(trendCopy(s.d120))}</p></div><div class="detail-insight-card"><b>가격 위치 · 볼린저</b><p>${esc(bbCopy(s.bb_pos))}</p></div><div class="detail-insight-card"><b>손익 구조</b><p>${esc(rrCopy(p))}</p></div><div class="detail-insight-card" style="grid-column:1/-1"><b>거래량·수급 보조 확인</b><p>${esc(flowCopy(f))}</p></div></div><div class="detail-insight-note">엄선 점수는 RSI·추세·수급·손익비 같은 조건을 묶어 후보끼리 우선순위를 정하는 내부 점수입니다. 85점이라고 해서 85% 확률로 오른다는 뜻은 아닙니다.</div>`;
  }
  function statusLabel(status){return({PENDING:'다음 시가 대기',FILLED:'보유 중',CLOSED:'종료',CANCELLED:'취소',REJECTED:'거절'})[status]||status||'—'}
  function statusClass(status){return String(status||'').toLowerCase()}
  function orderHTML(o){
    const pnl=num(o.pnl_krw),ret=num(o.return_pct);const pnlClass=pnl==null?'':pnl>=0?'up':'down';
    const entry=o.entry_fill_usd??o.planned_entry_usd;const cost=o.entry_cost_krw??o.planned_notional_krw;
    return `<div class="paper-order"><div class="paper-order-top"><div><div class="paper-order-name">${esc(o.name_ko||o.symbol)} <span class="ticker">${esc(o.symbol)}</span></div><div class="paper-order-sub">${esc(o.strategy_name||o.strategy_id)} · ${esc(o.signal_date||o.submitted_market_date||'')}</div></div><span class="paper-status ${statusClass(o.status)}">${esc(statusLabel(o.status))}</span></div><div class="paper-order-grid"><div><span>수량</span><b>${Number(o.qty||0).toLocaleString()}주</b></div><div><span>${o.status==='PENDING'?'예정 진입':'체결가'}</span><b>${usd(entry)}</b></div><div><span>가상 투입금</span><b>${krw(cost)}</b></div><div><span>손익</span><b class="paper-pnl ${pnlClass}">${pnl==null?'—':`${pnl>=0?'+':''}${krw(pnl)}${ret!=null?` · ${ret>=0?'+':''}${ret.toFixed(2)}%`:''}`}</b></div><div><span>TARGET</span><b>${usd(o.target)}</b></div><div><span>STOP</span><b>${usd(o.stop)}</b></div><div><span>보유 일봉</span><b>${Number(o.held_bars||0)} / ${Number(o.max_hold_bars||0)}</b></div><div><span>종료 사유</span><b>${esc(o.exit_reason||o.cancel_reason||'—')}</b></div></div></div>`;
  }
  function renderPaper(data){
    paperSnapshot=data;const sum=data?.summary||{};const summary=document.getElementById('paperSummary'),orders=document.getElementById('paperOrders'),meta=document.getElementById('paperMeta');
    if(summary)summary.innerHTML=`<div class="paper-stat"><span>가상 총자산</span><b>${krw(sum.equity_krw)}</b></div><div class="paper-stat"><span>사용가능 현금</span><b>${krw(sum.available_cash_krw)}</b></div><div class="paper-stat"><span>평가손익</span><b>${num(sum.unrealized_pnl_krw)>=0?'+':''}${krw(sum.unrealized_pnl_krw)}</b></div><div class="paper-stat"><span>실현손익</span><b>${num(sum.realized_pnl_krw)>=0?'+':''}${krw(sum.realized_pnl_krw)}</b></div>`;
    if(orders){const rows=[...(data?.orders||[])].reverse();orders.innerHTML=rows.length?rows.map(orderHTML).join(''):'<div class="paper-empty">아직 가상 주문이 없어요. 종목 상세에서 ‘가상매수’를 누르면 다음 거래일 시가 대기 주문이 만들어집니다.</div>'}
    if(meta)meta.textContent=`대기 ${sum.pending_orders||0} · 보유 ${sum.open_positions||0} · 종료 ${sum.closed_trades||0} · 승률 ${Number(sum.win_rate_pct||0).toFixed(1)}% · 실제주문 OFF`;
  }
  async function loadPaper(refresh=false){
    const btn=document.getElementById('paperRefresh');if(btn){btn.disabled=true;btn.textContent=refresh?'시장데이터 반영 중…':'불러오는 중…'}
    try{const data=await apiJSON(refresh?'/api/paper/refresh':'/api/paper',{method:refresh?'POST':'GET'});renderPaper(data)}catch(e){const orders=document.getElementById('paperOrders');if(orders)orders.innerHTML=`<div class="paper-empty">${esc(e.message)}</div>`}finally{if(btn){btn.disabled=false;btn.textContent='시장데이터로 갱신'}}
  }
  function setupPaperSection(detail){
    const nav=document.querySelector('.nav'),shell=document.querySelector('.shell');if(!nav||!shell)return;
    if(!nav.querySelector('[data-page="paper"]')){const b=document.createElement('button');b.dataset.page='paper';b.textContent='가상계좌';nav.appendChild(b)}
    if(!document.getElementById('paper')){
      const section=document.createElement('section');section.id='paper';section.style.display='none';section.innerHTML=`<article class="panel"><div class="panel-head"><div><div class="eyebrow">PAPER BROKER · 실제주문 없음</div><h2>300만원 가상계좌</h2><p class="paper-head-note">실제 시장 데이터를 읽되 주문은 가상 장부에서만 처리합니다. 신호가 나온 날 주문을 만들고 다음 거래일 시가에서 진입 가능 여부를 확인합니다.</p></div><div class="paper-actions"><button class="btn" id="paperRefresh">시장데이터로 갱신</button><button class="btn" id="paperReset">가상계좌 초기화</button></div></div><div class="paper-summary" id="paperSummary"></div><div class="ticker" id="paperMeta">—</div><div style="height:14px"></div><div class="paper-orders" id="paperOrders"><div class="paper-empty">가상계좌를 불러오는 중…</div></div></article>`;detail.parentNode.insertBefore(section,detail);
      document.getElementById('paperRefresh').onclick=()=>loadPaper(true);
      document.getElementById('paperReset').onclick=async()=>{if(!confirm('이 브라우저의 가상계좌 기록을 모두 초기화할까요?'))return;try{renderPaper(await apiJSON('/api/paper/reset',{method:'POST'}))}catch(e){alert(e.message)}};
    }
    document.querySelectorAll('.nav button').forEach(b=>b.onclick=()=>{document.querySelectorAll('.nav button').forEach(x=>x.classList.toggle('on',x===b));['today','search','paper','state'].forEach(id=>{const el=document.getElementById(id);if(el)el.style.display=b.dataset.page===id?'block':'none'});if(b.dataset.page==='paper')loadPaper(false)});
  }
  function setupDetailEnhancements(detail){
    let explain=document.getElementById('detailExplain');if(!explain){explain=document.createElement('div');explain.id='detailExplain';explain.className='detail-insight';const reason=document.getElementById('detailReason');reason?.insertAdjacentElement('afterend',explain)}
    const actions=detail.querySelector('.detail-top .actions');let buy=document.getElementById('paperBuy');if(actions&&!buy){buy=document.createElement('button');buy.id='paperBuy';buy.type='button';buy.className='paper-buy';buy.textContent='가상매수';buy.disabled=true;actions.insertBefore(buy,actions.firstChild)}
    let msg=document.getElementById('paperDetailMessage');if(!msg){msg=document.createElement('div');msg.id='paperDetailMessage';msg.className='paper-detail-message';detail.querySelector('.detail-top')?.insertAdjacentElement('afterend',msg)}
    if(buy)buy.onclick=async()=>{
      let d=null;try{if(typeof detailData!=='undefined')d=detailData}catch{}
      if(!d?.symbol||!d?.strategy_id)return;
      buy.disabled=true;buy.textContent='가상주문 생성 중…';msg.className='paper-detail-message show';msg.textContent='최신 스캔의 BUY/TARGET/STOP으로 다음 거래일 시가 대기 주문을 만들고 있어요.';
      try{const data=await apiJSON('/api/paper/submit',{method:'POST',body:JSON.stringify({symbol:d.symbol,strategy:d.strategy_id})});renderPaper(data);msg.className='paper-detail-message show';msg.textContent='가상주문이 생성됐어요. 가상계좌 탭에서 수량과 상태를 확인할 수 있어요.';buy.textContent='가상주문 생성됨'}catch(e){msg.className='paper-detail-message show err';msg.textContent=e.message;buy.textContent='가상매수';buy.disabled=false}
    };
    const base=typeof window.openDetail==='function'?window.openDetail:null;
    if(base&&!window.__paperWrappedOpenDetail){window.__paperWrappedOpenDetail=true;window.openDetail=async function(symbol,strategy){const result=await base(symbol,strategy);let d=null;try{if(typeof detailData!=='undefined')d=detailData}catch{}renderDetailExplanation(d);const b=document.getElementById('paperBuy'),m=document.getElementById('paperDetailMessage');if(m)m.className='paper-detail-message';if(b){const current=!!d&&d.source!=='saved_history';b.disabled=!current;b.textContent=current?'가상매수':'현재 신호만 가상매수 가능';b.title=current?'최신 스캔 기준으로 다음 거래일 시가 대기 주문을 생성합니다.':'과거 확정 기록은 새 가상주문으로 만들지 않습니다.'}return result}}
  }
  function eventTime(at){try{return new Date(at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}catch{return at||'—'}}
  function renderSignalEvents(data){const host=document.getElementById('signalEventList'),meta=document.getElementById('signalEventMeta');if(meta)meta.textContent=`현재 엄선 ${data?.active_count||0}개 · 포착/이탈은 장중 로그, 공식 추천은 마감 후 별도 확정`;if(!host)return;const events=data?.events||[];host.innerHTML=events.length?events.slice(0,24).map(e=>`<div class="signal-event ${e.event==='EXIT'?'exit':''}"><span class="event-badge">${e.event==='EXIT'?'이탈':'포착'}</span><div><b>${esc(e.name_ko||e.security_name||e.symbol)} · ${esc(e.symbol)}</b><small>${esc(e.strategy_name||e.strategy_id)}${e.score!=null?` · 당시 엄선 ${Math.round(Number(e.score))}점`:''}</small></div><time>${esc(eventTime(e.at))}</time></div>`).join(''):'<div class="paper-empty">아직 저장된 장중 변동 로그가 없어요. 다음 자동 스캔부터 포착/이탈이 기록됩니다.</div>'}
  async function loadSignalEvents(){try{renderSignalEvents(await apiJSON('/api/signal-events?limit=40'))}catch(e){const host=document.getElementById('signalEventList');if(host)host.innerHTML=`<div class="paper-empty">${esc(e.message)}</div>`}}
  function setupSignalPolicy(){
    const todayNav=document.querySelector('.nav button[data-page="today"]');if(todayNav)todayNav.textContent='실시간 후보';
    const grid=document.getElementById('todayGrid'),todayPanel=grid?.closest('.panel');if(todayPanel&&!todayPanel.querySelector('.live-mode-banner')){const banner=document.createElement('div');banner.className='live-mode-banner';banner.innerHTML='<span class="live-mode-badge">LIVE</span><div><b>장중 후보는 움직일 수 있어요</b>RSI·볼린저·현재가가 일봉 형성 중 바뀌면 목록에 들어왔다 빠질 수 있습니다. 포착/이탈은 아래 로그에 남기고, 성과를 평가할 공식 추천은 미국장 마감 후 한 번만 확정합니다.</div>';const tabs=document.getElementById('todayTabs');tabs?.insertAdjacentElement('beforebegin',banner);const h2=todayPanel.querySelector('.panel-head h2');if(h2)h2.textContent='지금 눈여겨볼 자리'}
    const historyDays=document.getElementById('historyDays'),historyPanel=historyDays?.closest('.panel');if(historyPanel){const h2=historyPanel.querySelector('.panel-head h2');if(h2)h2.textContent='마감 확정 추천 기록';const eyebrow=historyPanel.querySelector('.eyebrow');if(eyebrow)eyebrow.textContent='공식 추천 · 일봉 마감 스냅샷'}
    if(todayPanel&&historyPanel&&!document.getElementById('signalEventPanel')){const panel=document.createElement('article');panel.className='panel';panel.id='signalEventPanel';panel.innerHTML='<div class="panel-head"><div><div class="eyebrow">INTRADAY LOG</div><h2>오늘 장중 포착 · 이탈</h2></div><div class="ticker" id="signalEventMeta">—</div></div><div class="signal-log" id="signalEventList"><div class="paper-empty">로그를 불러오는 중…</div></div>';historyPanel.parentNode.insertBefore(panel,historyPanel);loadSignalEvents()}
  }
  window.addEventListener('DOMContentLoaded',()=>{
    injectStyles();const detail=document.getElementById('detail');if(!detail)return;
    setupPaperSection(detail);setupSignalPolicy();setupDetailEnhancements(detail);
    const overlay=document.createElement('div');overlay.id='detailOverlay';overlay.className='detail-overlay';overlay.setAttribute('aria-hidden','true');
    const shell=document.createElement('div');shell.className='detail-overlay-shell';const close=document.createElement('button');close.className='detail-close';close.type='button';close.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg> 상세 닫기';close.onclick=closeDetail;
    detail.parentNode.insertBefore(overlay,detail.nextSibling);shell.appendChild(close);shell.appendChild(detail);overlay.appendChild(shell);document.body.appendChild(overlay);
    const observer=new MutationObserver(()=>{if(isDetailOpen(detail)){openShell()}else{overlay.setAttribute('aria-hidden','true');overlay.classList.remove('open');document.body.classList.remove('detail-open')}});
    observer.observe(detail,{attributes:true,attributeFilter:['class','style']});
    overlay.addEventListener('click',e=>{if(e.target===overlay)closeDetail()});document.addEventListener('keydown',e=>{if(e.key==='Escape'&&overlay.classList.contains('open'))closeDetail()});if(isDetailOpen(detail))openShell();
  });
})();
