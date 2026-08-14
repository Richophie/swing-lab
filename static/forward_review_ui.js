(()=>{
const PAGE='forwardreview';
const $=s=>document.querySelector(s);
const N=v=>Number(v)||0;
const krw=v=>`${Math.round(N(v)).toLocaleString('ko-KR')}원`;
const pct=v=>`${N(v)>=0?'+':''}${N(v).toFixed(2)}%`;
const gateLabel=g=>({WAIT_FORWARD_SAMPLE:'FORWARD 표본 대기',HUMAN_REVIEW_READY:'사람 심사 가능',BLOCKED_SAFETY:'안전 점검 필요',BLOCKED_PAPER_INFRA:'PaperBroker 점검 필요'}[g]||g||'확인 중');
const gateClass=g=>g==='HUMAN_REVIEW_READY'?'is-ready':String(g||'').startsWith('BLOCKED')?'is-blocked':'is-wait';
const safeText=v=>v?'<b class="ok">PASS</b>':'<b class="no">CHECK</b>';

function ensureCss(){if(document.getElementById('forwardReviewCss'))return;const l=document.createElement('link');l.id='forwardReviewCss';l.rel='stylesheet';l.href='/static/forward_review.css?v=20260814-1';document.head.appendChild(l)}
function ensurePage(){
  ensureCss();
  const shell=$('main.shell');if(!shell)return null;
  let page=document.getElementById(PAGE);
  if(!page){page=document.createElement('section');page.id=PAGE;page.className='fr-page';page.innerHTML='<article class="panel fr-panel"><div id="forwardReviewBody"><div class="status">Forward 심사 데이터를 불러오는 중…</div></div></article>';const detail=document.getElementById('detail');detail?shell.insertBefore(page,detail):shell.appendChild(page)}
  const nav=$('.nav');if(nav){let b=nav.querySelector(`[data-page="${PAGE}"]`);if(!b){b=document.createElement('button');b.dataset.page=PAGE;b.textContent='Forward 심사';nav.appendChild(b)}b.onclick=e=>{e.preventDefault();show(page,b);load()}}
  return page
}
function show(page,button){
  document.querySelectorAll('.nav button').forEach(x=>x.classList.toggle('on',x===button));
  ['today','search','paper','state','lab','backtestlab','forwardreview','detail'].forEach(id=>{const x=document.getElementById(id);if(x)x.style.display=id===PAGE?'block':'none'});
}
function paperButton(){const b=document.querySelector('[data-page="paper"]');return b?'<button class="fr-paper-link" id="frOpenPaper">연구용 PaperBroker 열기</button>':'<button class="fr-paper-link" disabled>가상계좌 메뉴 로드 대기</button>'}
function card(r){const cls=r.key==='v2'?'is-v2':r.key==='v3'?'is-v3':r.key==='v4'?'is-v4':'';const ret=N(r.return_pct);return `<article class="fr-card ${cls}"><small>${r.label}</small><h3>${r.thesis}</h3><p>${r.sample_ready?'1차 표본 기준 도달':'종료 30건 전까지 순위 판정 보류'}</p><div class="fr-main-number ${ret>=0?'up':'down'}">${pct(ret)}</div><div class="fr-kpis"><div><span>MTM 자산</span><b>${krw(r.equity_krw)}</b></div><div><span>종료</span><b>${r.closed_trades} / 30건</b></div><div><span>보유</span><b>${r.open_positions}개</b></div><div><span>현금부족</span><b>${r.reject_cash}건</b></div></div><div class="fr-card-progress"><i style="width:${Math.max(0,Math.min(100,N(r.sample_progress_pct)))}%"></i></div></article>`}
function comparison(c){return `<div class="fr-comparison"><span>${c.label}</span><b>${c.judgement_allowed?pct(c.return_delta_pct):'판정 보류'}</b><b>${c.judgement_allowed?krw(c.equity_delta_krw):'표본 대기'}</b><b class="fr-muted">현금탈락 ${c.cash_reject_delta>=0?'+':''}${c.cash_reject_delta}</b></div>`}
function render(d){
  const body=document.getElementById('forwardReviewBody');if(!body)return;
  const progress=Math.max(0,Math.min(100,N(d.sample_progress_pct)));
  const p=d.paper_infrastructure||{};
  body.innerHTML=`
    <div class="fr-hero"><div><div class="eyebrow">FROZEN FORWARD · PROMOTION GATE</div><h2>${d.headline||'Forward 심사'}</h2><p>${d.recommended_next_action||''}</p><div class="fr-progress"><div class="fr-progress-top"><span>가장 느린 Challenger 표본</span><b>${d.minimum_closed_trades_observed||0} / ${d.minimum_closed_trades_required||30} 종료</b></div><div class="fr-track"><i style="width:${progress}%"></i></div></div></div><div class="fr-gate ${gateClass(d.gate)}"><small>CURRENT GATE</small><b>${gateLabel(d.gate)}</b></div></div>
    <div class="fr-cards">${(d.challengers||[]).map(card).join('')}</div>
    <div class="fr-review-grid"><div class="fr-box"><h3>같은 미래에서 비교</h3><p>표본이 차기 전에는 숫자를 보여주되 우승자 판정은 하지 않습니다.</p>${(d.comparisons||[]).map(comparison).join('')||'<div class="fr-muted">비교 데이터가 아직 없습니다.</div>'}</div>
    <div class="fr-box"><h3>PaperBroker 준비 상태</h3><p>기반시설이 준비됐다는 뜻과 전략이 승격될 준비가 됐다는 뜻은 분리합니다.</p><div class="fr-checks"><div class="fr-check"><span>가상체결 기반시설</span>${safeText(p.ready)}</div><div class="fr-check"><span>실제 브로커 연결</span><b class="wait">OFF</b></div><div class="fr-check"><span>자동 승격</span><b class="wait">OFF</b></div><div class="fr-check"><span>공식 Paper 전략</span><b class="${d.official_paper_strategy_ready?'ok':'wait'}">${d.official_paper_strategy_ready?'사람 심사 가능':'WAIT'}</b></div><div class="fr-check"><span>V1~V4 안전조건</span>${safeText(d.all_forward_safety_pass)}</div></div>${paperButton()}<div class="fr-next"><small>다음 행동</small><b>${d.recommended_next_action||'Forward 표본을 계속 관찰'}</b></div></div></div>
    <div class="fr-foot">이 화면은 Forward 상태를 읽어 심사만 합니다. 전략 규칙을 바꾸지 않고, 자동 승격·실브로커 주문을 실행하지 않습니다.</div>`;
  const pb=document.getElementById('frOpenPaper');if(pb)pb.onclick=()=>{const nav=document.querySelector('[data-page="paper"]');if(nav)nav.click()}
}
async function load(){const body=document.getElementById('forwardReviewBody');if(!body)return;try{const r=await fetch(`/static/forward_review.json?ts=${Date.now()}`,{cache:'no-store'});if(!r.ok)throw new Error(String(r.status));render(await r.json())}catch(e){body.innerHTML='<div class="status">Forward 심사 데이터를 불러오지 못했습니다. 다음 Market Scan 후 다시 확인해주세요.</div>'}}
function bind(){const page=ensurePage();if(!page)return;}
new MutationObserver(bind).observe(document.documentElement,{childList:true,subtree:true});bind();const t=setInterval(bind,800);setTimeout(()=>clearInterval(t),20000);
})();