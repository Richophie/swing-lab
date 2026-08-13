(()=>{
  let inFlight=false,lastSignature='';
  const A='A_NEXT_OPEN',B='B_BUY_TOUCH';
  const esc=v=>String(v??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const n=v=>{const x=Number(v);return Number.isFinite(x)?x:null};
  const krw=v=>{const x=n(v);return x==null?'—':`${Math.round(x).toLocaleString('ko-KR')}원`};
  const pct=v=>{const x=n(v);return x==null?'—':`${x>=0?'+':''}${x.toFixed(2)}%`};
  const pnlClass=v=>{const x=n(v);return x==null?'':x>=0?'up':'down'};
  function trackCard(t,id){
    const s=t?.summary||{},l=t?.lab_summary||{},g=l.sample_gate||{};
    const pnl=s.realized_pnl_krw;
    return `<div class="lab-track-card"><div class="lab-track-head"><h3>${esc(l.track_label||id)}</h3><span>${id===A?'마감추천 → 다음 시가':'마감추천 → BUY 상단 이하'}</span></div><div class="lab-track-stats"><div class="lab-track-stat"><span>총자산</span><b>${krw(s.equity_krw)}</b></div><div class="lab-track-stat"><span>실현손익</span><b class="${pnlClass(pnl)}">${n(pnl)!=null&&n(pnl)>=0?'+':''}${krw(pnl)}</b></div><div class="lab-track-stat"><span>승률</span><b>${n(s.win_rate_pct)==null?'—':`${Number(s.win_rate_pct).toFixed(1)}%`}</b></div><div class="lab-track-stat"><span>종료 거래</span><b>${l.closed_orders||0}건</b></div><div class="lab-track-stat"><span>진행</span><b>${(s.pending_orders||0)+(s.open_positions||0)}건</b></div><div class="lab-track-stat"><span>실현 MDD</span><b class="${n(l.realized_curve_max_drawdown_pct)<0?'down':''}">${pct(l.realized_curve_max_drawdown_pct)}</b></div></div><div class="lab-gate"><b>${esc(g.stage||'표본 축적중')}</b> · ${esc(g.message||'종료거래가 쌓이면 정식 비교합니다.')}${g.remaining>0?` · 다음 기준까지 ${g.remaining}건`:''}</div></div>`;
  }
  function curvePoints(curve,w=720,h=190,p=24){
    const vals=(curve||[]).map(x=>n(x.equity_krw)).filter(x=>x!=null);if(!vals.length)return'';
    let lo=Math.min(...vals),hi=Math.max(...vals);if(lo===hi){lo-=1;hi+=1}const pad=(hi-lo)*.08;lo-=pad;hi+=pad;
    return (curve||[]).map((x,i)=>{const v=n(x.equity_krw);if(v==null)return null;const px=p+i/Math.max(1,curve.length-1)*(w-p*2),py=h-p-(v-lo)/(hi-lo)*(h-p*2);return{x:px,y:py,v,label:x.label}}).filter(Boolean);
  }
  function equityChart(a,b){
    const ca=a?.lab_summary?.equity_curve||[],cb=b?.lab_summary?.equity_curve||[];
    if(ca.length<2&&cb.length<2)return '<div class="lab-break-empty">종료 거래가 생기면 A/B 자산곡선이 여기 그려집니다.</div>';
    const all=[...ca,...cb].map(x=>n(x.equity_krw)).filter(x=>x!=null);let lo=Math.min(...all),hi=Math.max(...all);if(lo===hi){lo-=1;hi+=1}const pad=(hi-lo)*.08;lo-=pad;hi+=pad;const w=720,h=190,p=24;
    const points=curve=>curve.map((x,i)=>{const v=n(x.equity_krw);if(v==null)return null;return{x:p+i/Math.max(1,curve.length-1)*(w-p*2),y:h-p-(v-lo)/(hi-lo)*(h-p*2)} }).filter(Boolean);
    const pa=points(ca),pb=points(cb),path=pts=>pts.map((q,i)=>`${i?'L':'M'}${q.x.toFixed(1)} ${q.y.toFixed(1)}`).join(' ');
    return `<svg class="lab-equity-chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="A B 연구계좌 자산곡선"><line class="lab-chart-axis" x1="24" y1="24" x2="24" y2="166"/><line class="lab-chart-axis" x1="24" y1="166" x2="696" y2="166"/>${pa.length?`<path class="lab-chart-line-a" d="${path(pa)}"/>`:''}${pb.length?`<path class="lab-chart-line-b" d="${path(pb)}"/>`:''}${pa.length?`<circle class="lab-chart-dot-a" cx="${pa.at(-1).x}" cy="${pa.at(-1).y}" r="3"/>`:''}${pb.length?`<circle class="lab-chart-dot-b" cx="${pb.at(-1).x}" cy="${pb.at(-1).y}" r="3"/>`:''}</svg><div class="lab-chart-legend"><span><i></i>A · 다음 시가형</span><span class="b"><i></i>B · BUY 상단 이하</span></div>`;
  }
  function bucketRows(bucket){
    const rows=Object.entries(bucket||{}).sort((a,b)=>(b[1]?.closed||0)-(a[1]?.closed||0));if(!rows.length)return '<div class="lab-break-empty">아직 종료 표본이 없습니다.</div>';
    return `<div class="lab-break-list">${rows.map(([k,v])=>`<div class="lab-break-row"><b title="${esc(k)}">${esc(k)}</b><span>${v.closed||0}건</span><span>${n(v.win_rate_pct)==null?'—':`${Number(v.win_rate_pct).toFixed(1)}%`}</span><span class="lab-pnl">${n(v.avg_return_pct)==null?'—':pct(v.avg_return_pct)}</span></div>`).join('')}</div>`;
  }
  function breakCard(title,a,b,key){return `<div class="lab-break-card"><div class="lab-section-title"><h3>${esc(title)}</h3><small>건수 · 승률 · 평균수익률</small></div><div class="lab-break-grid"><div><div class="lab-section-title"><h3>A</h3><small>다음 시가형</small></div>${bucketRows(a?.lab_summary?.[key])}</div><div><div class="lab-section-title"><h3>B</h3><small>BUY 상단 이하</small></div>${bucketRows(b?.lab_summary?.[key])}</div></div></div>`}
  function orderRow(o){const status=({PENDING:'대기',FILLED:'보유',CLOSED:'종료',CANCELLED:'취소',REJECTED:'거절'})[o.status]||o.status||'—';const entry=o.entry_fill_usd??o.planned_entry_usd;return `<div class="lab-v2-order"><div class="lab-v2-order-top"><b>${esc(o.symbol)} · ${esc(o.strategy_name||o.strategy_id)}</b><span>${esc(status)}</span></div><small>진입 ${entry!=null?`$${Number(entry).toFixed(2)}`:'—'} · TARGET ${o.target!=null?`$${Number(o.target).toFixed(2)}`:'—'} · STOP ${o.stop!=null?`$${Number(o.stop).toFixed(2)}`:'—'}${o.exit_reason?` · 종료 ${esc(o.exit_reason)}`:''}${o.exit_resolution_quality?` · 판정 ${esc(o.exit_resolution_quality)}`:''}</small></div>`}
  function ordersCard(a,b){const rows=t=>[...(t?.orders||[])].reverse().slice(0,8);return `<div class="lab-orders-card"><div class="lab-section-title"><h3>최근 자동연구 거래</h3><small>사람이 취소/매도할 수 없음</small></div><div class="lab-order-columns"><div class="lab-order-col"><h4>A · 다음 시가형</h4>${rows(a).length?rows(a).map(orderRow).join(''):'<div class="lab-break-empty">아직 거래 없음</div>'}</div><div class="lab-order-col"><h4>B · BUY 상단 이하</h4>${rows(b).length?rows(b).map(orderRow).join(''):'<div class="lab-break-empty">아직 거래 없음</div>'}</div></div></div>`}
  function render(d){
    const host=document.getElementById('labBody');if(!host)return;const tracks=d.tracks||{},a=tracks[A]||{},b=tracks[B]||{},base=d.baseline||{},cmp=d.comparison||{};const locked=cmp.production_tuning_locked!==false;
    host.innerHTML=`<div class="lab-v2"><div class="lab-baseline-strip"><div><b>고정 기준 · ${esc(base.baseline_version||'baseline')}</b><small>공개 ${Array.isArray(base.public_strategies)?base.public_strategies.length:0}전략 · S ≥ ${base.s_threshold??'—'} · 300만원 · 최대 ${base.portfolio?.max_positions??3}종목 · 거래당 ${base.portfolio?.risk_per_trade_pct??1}% risk. 주문 생성 당시 버전/시장상태를 고정해 이후 엔진 변경이 과거 거래를 덮어쓰지 않습니다.</small></div><span class="lab-lock ${locked?'':'open'}">${locked?'전략 튜닝 잠금':'정식 리뷰 가능'}</span></div><div class="lab-ab-grid">${trackCard(a,A)}${trackCard(b,B)}</div><div class="lab-chart-card"><div class="lab-section-title"><h3>A/B 자산곡선</h3><small>종료 거래 기준 실현자산</small></div>${equityChart(a,b)}</div>${breakCard('전략별',a,b,'by_strategy')}${breakCard('시장상태별',a,b,'by_market_state')}${breakCard('손익비 구간별',a,b,'by_rr')}${breakCard('종료 사유별',a,b,'by_exit_reason')}${breakCard('보유기간별',a,b,'by_hold')}${ordersCard(a,b)}<div class="lab-v2-note"><b>B 체결 규칙</b> · BUY 상단은 ‘최대 허용 매수가’입니다. 다음 거래일이 더 낮게 시작해도 STOP 위라면 더 좋은 가격으로 체결합니다. 위에서 시작하면 BUY 상단까지 내려올 때 기다립니다. STOP 아래에서 시작하면 전략이 깨진 것으로 보고 새 매수를 하지 않습니다.<br><b>STOP/TARGET 동시 일봉</b> · 1분봉으로 먼저 닿은 쪽을 판정하고, 같은 1분봉 안에서도 순서를 알 수 없거나 분봉이 없을 때만 STOP 우선으로 보수 처리합니다.</div></div>`;
  }
  function activate(nav){
    document.querySelectorAll('.nav button').forEach(x=>x.classList.toggle('on',x===nav));
    ['today','search','paper','state','lab'].forEach(id=>{const el=document.getElementById(id);if(el)el.style.display=id==='lab'?'block':'none'});
  }
  async function load(force=false){
    const section=document.getElementById('lab'),host=document.getElementById('labBody');if(!section||!host||inFlight)return;if(section.style.display==='none'&&!force)return;inFlight=true;
    try{const r=await fetch('/api/shadow',{cache:'no-store'}),d=await r.json();if(!r.ok||d.error)throw new Error(d.error||`서버 ${r.status}`);const sig=JSON.stringify({c:d.comparison,t:Object.fromEntries(Object.entries(d.tracks||{}).map(([k,v])=>[k,{u:v.updated_at,s:v.summary,l:v.lab_summary}]))});const missingNewView=!host.querySelector('.lab-v2');if(force||sig!==lastSignature||missingNewView){lastSignature=sig;render(d)}}catch(e){host.innerHTML=`<div class="paper-empty">자동연구 성적표를 불러오지 못했습니다 · ${esc(e.message)}</div>`}finally{inFlight=false}
  }
  function bind(){
    const nav=document.querySelector('.nav [data-page="lab"]');
    if(nav&&!nav.dataset.labV2){
      nav.dataset.labV2='1';
      nav.onclick=ev=>{ev?.preventDefault?.();activate(nav);setTimeout(()=>load(true),120)};
    }
    const reload=document.getElementById('labReload');
    if(reload&&!reload.dataset.labV2){reload.dataset.labV2='1';reload.onclick=()=>setTimeout(()=>load(true),80)}
  }
  function boot(){setInterval(()=>{bind();load(false)},2500);setTimeout(()=>{bind();load(false)},700)}
  if(document.readyState==='loading')window.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
