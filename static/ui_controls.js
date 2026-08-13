(()=>{
  const CLIENT_KEY='swingLabPaperClientV1';
  let decoratingPaper=false,lastPreviewKey='',labLoading=false;

  function esc(v){return String(v??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]))}
  function num(v){const n=Number(v);return Number.isFinite(n)?n:null}
  function krw(v){const n=num(v);return n==null?'—':`${Math.round(n).toLocaleString('ko-KR')}원`}
  function usd(v){const n=num(v);return n==null?'—':`$${n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}`}
  function clientId(){let id=localStorage.getItem(CLIENT_KEY);if(!id){id=(crypto?.randomUUID?.()||`paper-${Date.now()}-${Math.random().toString(16).slice(2)}`);localStorage.setItem(CLIENT_KEY,id)}return id}
  async function api(url,options={}){const headers={...(options.headers||{})};if(url.startsWith('/api/paper'))headers['X-Paper-Client']=clientId();if(options.body&&!headers['Content-Type'])headers['Content-Type']='application/json';const r=await fetch(url,{cache:'no-store',...options,headers});const data=await r.json();if(!r.ok||data.error)throw new Error(data.error||`서버 ${r.status}`);return data}

  function injectStyles(){
    if(document.getElementById('productControlStyles'))return;
    const s=document.createElement('style');s.id='productControlStyles';s.textContent=`
      .engine-board,.lab-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:16px 0}.engine-card,.lab-stat{padding:15px;border:1px solid #e5e8e6;border-radius:16px;background:#fff}.engine-card span,.lab-stat span{display:block;font-size:9px;color:#949b9f;margin-bottom:5px}.engine-card b,.lab-stat b{font-size:16px;letter-spacing:-.035em}.engine-card small{display:block;margin-top:5px;color:#969da0;font-size:9px;line-height:1.45}.engine-note,.lab-note{padding:14px 16px;background:#f5f6f2;border-radius:14px;color:#66706b;font-size:11px;line-height:1.65}.lab-orders{display:grid;gap:9px;margin-top:14px}.lab-order{padding:14px;border:1px solid #e6e9e7;border-radius:15px;background:#fff}.lab-order-top{display:flex;justify-content:space-between;gap:10px}.lab-order-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin-top:10px}.lab-order-grid span{display:block;font-size:8px;color:#9ba1a4}.lab-order-grid b{font-size:10px}.manual-paper-control{display:flex;align-items:center;gap:7px}.manual-paper-control input{width:72px;padding:9px 10px;border:1px solid #dfe4e1;border-radius:11px;background:#fff;font:inherit;font-size:11px}.manual-paper-hint{font-size:9px;color:#92999d;max-width:180px;line-height:1.35}.paper-order-actions{display:flex;justify-content:flex-end;gap:7px;margin-top:11px}.paper-order-action{border:0;border-radius:10px;padding:8px 11px;background:#151714;color:#fff;font-size:10px;font-weight:850;cursor:pointer}.paper-order-action.cancel{background:#eef0ed;color:#515954}.scoreline .elite-miss{color:#8d9491;font-weight:700}
      @media(max-width:720px){.engine-board,.lab-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.lab-order-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.manual-paper-control{flex-wrap:wrap}.manual-paper-hint{max-width:100%;width:100%}}
    `;document.head.appendChild(s);
  }

  function syncScanTime(){
    const status=document.getElementById('status'),scanTime=document.getElementById('scanTime'),marketWrap=document.querySelector('.market-refresh-wrap');if(!status||!scanTime)return;
    let marketMsg=document.getElementById('marketRefreshStatus');if(!marketMsg&&marketWrap){marketMsg=document.createElement('span');marketMsg.id='marketRefreshStatus';marketMsg.className='market-refresh-status';marketWrap.prepend(marketMsg)}
    let timer=null;const flash=t=>{if(!marketMsg)return;marketMsg.textContent=t;marketMsg.classList.add('show');clearTimeout(timer);timer=setTimeout(()=>marketMsg.classList.remove('show'),2200)};
    const sync=()=>{const text=(status.textContent||'').trim(),parts=text.split('·').map(x=>x.trim()).filter(Boolean),stamp=parts.at(-1)||'';if(/\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\./.test(stamp))scanTime.textContent=stamp;else if(/시장 상태를 현재 데이터/.test(text))flash('시장만 다시 확인됨');else if(/최신 저장 결과를 불러오는 중/.test(text))scanTime.textContent='불러오는 중…'};
    new MutationObserver(sync).observe(status,{childList:true,subtree:true,characterData:true});sync();
  }

  function ensureLab(){
    const shell=document.querySelector('.shell'),detail=document.getElementById('detail');if(!shell||!detail)return null;
    let section=document.getElementById('lab');if(section)return section;
    section=document.createElement('section');section.id='lab';section.style.display='none';section.innerHTML=`<article class="panel"><div class="panel-head"><div><div class="eyebrow">SHADOW PORTFOLIO · 사람 개입 없음</div><h2>자동거래연구소</h2><p class="paper-head-note">미국장 마감 후 확정된 공식 추천만 300만원 연구계좌에 자동 입력합니다. 다음 거래일 시가·STOP·TARGET·기간종료를 동일 규칙으로 처리하고 사람이 중간에 손대지 않습니다.</p></div><button class="btn" id="labReload">연구장부 새로고침</button></div><div id="labBody"><div class="paper-empty">자동 연구계좌를 불러오는 중…</div></div></article>`;detail.parentNode.insertBefore(section,detail);section.querySelector('#labReload').onclick=()=>loadLab(true);return section;
  }

  function relabel(){
    const map={today:'실시간후보',search:'사라마라',state:'엔진',paper:'가상계좌',lab:'자동거래연구소'};document.querySelectorAll('.nav button').forEach(b=>{if(map[b.dataset.page])b.textContent=map[b.dataset.page]});
    const search=document.getElementById('search');if(search){const h=search.querySelector('h2'),e=search.querySelector('.eyebrow'),st=document.getElementById('searchStatus');if(e)e.textContent='사라마라 · 내가 찍은 종목 검증';if(h)h.textContent='이 종목, 우리 엔진엔 얼마나 맞을까?';if(st&&st.textContent.includes('티커를 입력'))st.textContent='내가 사고 싶은 티커를 넣으면 공개 3전략과 비교해 지금 자리가 우리 규칙에 얼마나 부합하는지 보여줍니다.'}
  }

  function activateLab(btn){
    document.querySelectorAll('.nav button').forEach(x=>x.classList.toggle('on',x===btn));['today','search','paper','state','lab'].forEach(id=>{const el=document.getElementById(id);if(el)el.style.display=id==='lab'?'block':'none'});loadLab(false);
  }

  function bindNav(){
    const nav=document.querySelector('.nav');if(!nav)return false;ensureLab();let lab=nav.querySelector('[data-page="lab"]');if(!lab){lab=document.createElement('button');lab.dataset.page='lab';lab.textContent='자동거래연구소';nav.appendChild(lab)}
    [...nav.querySelectorAll('button')].forEach(b=>{if(b.dataset.productBound)return;const old=b.onclick;b.dataset.productBound='1';b.onclick=ev=>{if(b.dataset.page==='lab'){ev?.preventDefault?.();activateLab(b);return}const labSection=document.getElementById('lab');if(labSection)labSection.style.display='none';if(typeof old==='function')old.call(b,ev);if(b.dataset.page==='state')loadEngine();setTimeout(relabel,0)}});relabel();return !!nav.querySelector('[data-page="paper"]');
  }

  async function loadEngine(){
    const host=document.getElementById('engineState');if(!host)return;host.innerHTML='<div class="paper-empty">엔진 상태를 읽는 중…</div>';
    try{const d=await api('/api/engine-status'),s=d.scan||{},r=d.rules||{},h=d.official_history||{},log=d.intraday_log||{},lab=d.shadow_lab||{};host.innerHTML=`<div class="engine-board"><div class="engine-card"><span>마지막 스캔</span><b>${esc(s.status||'—')}</b><small>${esc(s.scanned_at||'')}</small></div><div class="engine-card"><span>현재 후보</span><b>S ${s.raw_s_signals??0} · 엄선 ${s.elite_signals??0}</b><small>${Number(s.candidate_count||0).toLocaleString()} / universe ${Number(s.universe_count||0).toLocaleString()}</small></div><div class="engine-card"><span>시장 상태</span><b>${esc(s.market_state||'—')}</b><small>${esc(s.market_brief||'')}</small></div><div class="engine-card"><span>공식 추천 기록</span><b>${Number(h.total_signals||0).toLocaleString()}건</b><small>마감 확정만 집계</small></div><div class="engine-card"><span>전략 기준</span><b>S ≥ ${r.s_threshold??'—'}</b><small>공개전략 ${Array.isArray(r.public_strategies)?r.public_strategies.length:0}개</small></div><div class="engine-card"><span>가상계좌 규칙</span><b>최대 ${r.max_positions??'—'}종목</b><small>거래당 ${r.risk_per_trade_pct??'—'}% risk · 종목당 ${r.max_position_pct??'—'}%</small></div><div class="engine-card"><span>장중 로그</span><b>S ${log.active_s??0} · 엄선 ${log.active_elite??0}</b><small>누적 ${log.event_count??0} events</small></div><div class="engine-card"><span>자동거래연구소</span><b>${lab.total_orders??0} 주문</b><small>종료 ${lab.closed_orders??0} · 실제주문 OFF</small></div></div><div class="engine-note">엔진 탭은 매수추천 탭이 아니라 <b>시스템 상태판</b>입니다. 어떤 규칙이 켜져 있는지, 스캔이 정상인지, 현재 시장·신호·연구계좌가 제대로 갱신되는지 확인하는 용도로 사용합니다. v${esc(d.app_version)} · Core ${esc(d.core_version)} · ${esc(d.architecture)}</div>`}
    catch(e){host.innerHTML=`<div class="paper-empty">${esc(e.message)}</div>`}
  }

  function shadowStatusLabel(s){return({PENDING:'다음 시가 대기',FILLED:'자동 보유',CLOSED:'자동 종료',CANCELLED:'자동 취소',REJECTED:'거절'})[s]||s||'—'}
  function shadowOrder(o){const pnl=num(o.pnl_krw),ret=num(o.return_pct),entry=o.entry_fill_usd??o.planned_entry_usd;return `<div class="lab-order"><div class="lab-order-top"><div><b>${esc(o.name_ko||o.symbol)} · ${esc(o.symbol)}</b><div class="ticker">${esc(o.strategy_name||o.strategy_id)} · ${esc(o.signal_date||'')}</div></div><span class="paper-status ${String(o.status||'').toLowerCase()}">${esc(shadowStatusLabel(o.status))}</span></div><div class="lab-order-grid"><div><span>수량</span><b>${Number(o.qty||0).toLocaleString()}주</b></div><div><span>진입</span><b>${usd(entry)}</b></div><div><span>TARGET</span><b>${usd(o.target)}</b></div><div><span>STOP</span><b>${usd(o.stop)}</b></div><div><span>손익</span><b>${pnl==null?'—':`${pnl>=0?'+':''}${krw(pnl)}${ret!=null?` · ${ret>=0?'+':''}${ret.toFixed(2)}%`:''}`}</b></div></div></div>`}
  async function loadLab(force=false){
    const host=document.getElementById('labBody');if(!host||labLoading)return;labLoading=true;if(force)host.innerHTML='<div class="paper-empty">연구장부를 다시 읽는 중…</div>';
    try{const d=await api('/api/shadow'),s=d.summary||{},l=d.lab_summary||{},m=d.lab_meta||{},orders=[...(d.orders||[])].reverse();host.innerHTML=`<div class="lab-summary"><div class="lab-stat"><span>연구 총자산</span><b>${krw(s.equity_krw)}</b></div><div class="lab-stat"><span>실현손익</span><b>${num(s.realized_pnl_krw)>=0?'+':''}${krw(s.realized_pnl_krw)}</b></div><div class="lab-stat"><span>진행 포지션</span><b>${(s.pending_orders||0)+(s.open_positions||0)}개</b></div><div class="lab-stat"><span>종료 거래</span><b>${l.closed_orders||0}건</b></div></div><div class="lab-note"><b>자동연구 규칙</b> · ${esc(m.lab_start_date||'')}부터 마감 확정 공식추천만 사용 · 같은 날 후보가 많으면 손익비 우선 · 300만원 · 최대 3포지션 · 거래당 1% risk · STOP/TARGET/기간종료 자동 · 실적위험 스냅샷 저장 · <b>실제 증권 주문은 절대 전송하지 않음</b>.</div><div class="lab-orders">${orders.length?orders.map(shadowOrder).join(''):'<div class="paper-empty">아직 자동 연구주문이 없어요. 다음 미국장 마감 확정 추천부터 자동으로 쌓입니다.</div>'}</div>`}
    catch(e){host.innerHTML=`<div class="paper-empty">${esc(e.message)}</div>`}finally{labLoading=false}
  }

  function getDetail(){try{return typeof detailData!=='undefined'?detailData:null}catch{return null}}
  async function previewManual(){
    const d=getDetail(),hint=document.getElementById('manualQtyHint'),input=document.getElementById('manualQty');if(!d?.symbol||!d?.strategy_id||!hint||!input)return;const key=`${d.symbol}|${d.strategy_id}`;if(key===lastPreviewKey&&hint.dataset.ready==='1')return;lastPreviewKey=key;hint.dataset.ready='0';hint.textContent='자동 수량 계산 중…';
    try{const p=await api(`/api/paper/manual-preview?symbol=${encodeURIComponent(d.symbol)}&strategy=${encodeURIComponent(d.strategy_id)}`);hint.dataset.ready='1';hint.textContent=`비워두면 ${p.max_qty}주 자동 · 최대 ${p.max_qty}주 · 예상 ${krw(p.planned_notional_krw)}`;input.max=String(p.max_qty);input.placeholder='자동'}catch(e){hint.textContent=e.message}
  }

  function setupManualDetail(){
    const buy=document.getElementById('paperBuy'),actions=buy?.parentElement;if(!buy||!actions)return false;let control=document.getElementById('manualPaperControl');if(!control){control=document.createElement('div');control.id='manualPaperControl';control.className='manual-paper-control';control.innerHTML='<input id="manualQty" type="number" min="1" step="1" inputmode="numeric" aria-label="가상매수 수량"><span class="manual-paper-hint" id="manualQtyHint">수량을 비우면 엔진 자동</span>';actions.insertBefore(control,buy)}
    if(!buy.dataset.manualBound){buy.dataset.manualBound='1';buy.textContent='가상매수';buy.onclick=async()=>{const d=getDetail(),msg=document.getElementById('paperDetailMessage'),input=document.getElementById('manualQty');if(!d?.symbol||!d?.strategy_id)return;const raw=(input?.value||'').trim(),qty=raw?Number(raw):null;buy.disabled=true;if(msg){msg.className='paper-detail-message show';msg.textContent='내 가상계좌에 주문을 만드는 중…'}try{const data=await api('/api/paper/manual-submit',{method:'POST',body:JSON.stringify({symbol:d.symbol,strategy:d.strategy_id,qty})});if(msg){msg.className='paper-detail-message show';msg.textContent=`${data.submitted_qty||qty||'자동'}주 가상주문 생성 · 후보가 화면에서 이탈해도 가상계좌 장부에는 계속 남습니다.`}buy.textContent='가상주문 생성됨';setTimeout(()=>{buy.textContent='가상매수';buy.disabled=false},1600)}catch(e){if(msg){msg.className='paper-detail-message show err';msg.textContent=e.message}buy.textContent='가상매수';buy.disabled=false}}}
    const detail=document.getElementById('detail');if(detail&&!detail.dataset.manualWatch){detail.dataset.manualWatch='1';new MutationObserver(()=>{if(detail.classList.contains('show')||detail.style.display==='block'){lastPreviewKey='';setTimeout(()=>{buy.textContent='가상매수';buy.disabled=false;previewManual()},120)}}).observe(detail,{attributes:true,attributeFilter:['class','style']})}
    return true;
  }

  async function decoratePaperOrders(){
    const section=document.getElementById('paper'),host=document.getElementById('paperOrders');if(!section||!host||section.style.display==='none'||decoratingPaper)return;decoratingPaper=true;
    try{const data=await api('/api/paper'),rows=[...(data.orders||[])].reverse(),cards=[...host.querySelectorAll('.paper-order')];cards.forEach((card,i)=>{const o=rows[i];if(!o)return;const origin=card.querySelector('.paper-origin');if(origin){origin.textContent=o.order_origin==='MANUAL_PAPER'?'내 매매':o.order_origin==='LIVE_CANDIDATE'?'장중 실험':o.order_origin==='CONFIRMED_CLOSE'?'마감 확정':'기록';origin.classList.toggle('official',o.order_origin==='CONFIRMED_CLOSE')}card.dataset.orderId=o.id||'';let actions=card.querySelector('.paper-order-actions');if(!actions){actions=document.createElement('div');actions.className='paper-order-actions';card.appendChild(actions)}actions.innerHTML='';if(o.status==='PENDING'||o.status==='FILLED'){const b=document.createElement('button');b.className=`paper-order-action${o.status==='PENDING'?' cancel':''}`;b.textContent=o.status==='PENDING'?'주문취소':'지금 가상매도';b.onclick=async()=>{if(!confirm(o.status==='PENDING'?'이 가상주문을 취소할까요?':'현재 시장가 가정으로 전량 가상매도할까요?'))return;b.disabled=true;try{await api('/api/paper/close',{method:'POST',body:JSON.stringify({order_id:o.id})});document.getElementById('paperRefresh')?.click();setTimeout(decoratePaperOrders,700)}catch(e){alert(e.message);b.disabled=false}};actions.appendChild(b)}});const meta=document.getElementById('paperMeta');if(meta){const manual=(data.orders||[]).filter(o=>o.order_origin==='MANUAL_PAPER').length;meta.textContent=`대기 ${data.summary?.pending_orders||0} · 보유 ${data.summary?.open_positions||0} · 종료 ${data.summary?.closed_trades||0} · 내 매매 ${manual} · 실제주문 OFF`}}
    catch(e){console.warn('manual paper controls',e)}finally{decoratingPaper=false}
  }

  function clarifyStrategyCards(){
    let l=null,sid=null;try{l=typeof latest!=='undefined'?latest:null;sid=typeof currentStrategy!=='undefined'?currentStrategy:null}catch{}if(!l||!sid||sid==='all')return;document.querySelectorAll('#todayGrid .pick').forEach(card=>{const symbol=card.dataset.symbol,strategy=card.dataset.strategy,row=(l.results||[]).find(r=>r.symbol===symbol),sig=(row?.strategy_signals||[]).find(s=>s.strategy_id===strategy);if(!sig||sig.elite_pass)return;const line=card.querySelector('.scoreline'),raw=num(sig.strategy_score),elite=num(sig.elite_score);if(line&&raw!=null)line.innerHTML=`S ${Math.round(raw)}점 · 전략 신호${elite!=null?` <span class="elite-miss">· 엄선 ${Math.round(elite)}점 미통과</span>`:''}`})
  }

  function boot(){
    injectStyles();syncScanTime();let tries=0;const upgrade=()=>{const ready=bindNav();setupManualDetail();relabel();if(!ready&&++tries<30)setTimeout(upgrade,120);else{setTimeout(relabel,800);setTimeout(relabel,1600)}};setTimeout(upgrade,0);
    const grid=document.getElementById('todayGrid');if(grid)new MutationObserver(()=>setTimeout(clarifyStrategyCards,0)).observe(grid,{childList:true});
    setInterval(()=>{setupManualDetail();decoratePaperOrders()},2500);
  }
  if(document.readyState==='loading')window.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();