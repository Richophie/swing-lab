(()=>{
const PAGE='forwarddiag';
const $=s=>document.querySelector(s);
const N=v=>Number(v)||0;
const has=v=>v!==null&&v!==undefined;
const pct=v=>has(v)?`${N(v)>=0?'+':''}${N(v).toFixed(2)}%`:'—';
const share=v=>has(v)?`${N(v).toFixed(0)}%`:'—';
const tone=v=>N(v)>=0?'up':'down';
const SEVERITY={high:'먼저 볼 것',medium:'확인 필요',low:'참고'};
const OUTCOME={SUCCESS:'목표가 도달',STOP:'손절',EXPIRED_GAIN:'기간 만료 · 이익',EXPIRED_LOSS:'기간 만료 · 손실',EXPIRED_FLAT:'기간 만료 · 본전'};

function ensurePage(){
  const shell=$('main.shell');if(!shell)return null;
  let page=document.getElementById(PAGE);
  if(!page){page=document.createElement('section');page.id=PAGE;page.className='fd-page';page.innerHTML='<article class="panel fd-panel"><div id="forwardDiagBody"><div class="status">실전 성적표를 불러오는 중…</div></div></article>';const detail=document.getElementById('detail');detail?shell.insertBefore(page,detail):shell.appendChild(page)}
  const nav=$('.nav');if(!nav)return page;
  let b=nav.querySelector(`[data-page="${PAGE}"]`);
  if(!b){b=document.createElement('button');b.dataset.page=PAGE;b.textContent='실전 성적표';nav.appendChild(b)}
  b.onclick=e=>{e.preventDefault();show(page,b);load()};
  // Other tabs keep their own show/hide lists, so this page hides itself when they are clicked.
  if(!nav.dataset.fdBound){nav.dataset.fdBound='1';nav.addEventListener('click',e=>{const x=e.target.closest('button');if(x&&x.dataset.page!==PAGE)page.style.display='none'},true)}
  return page
}
function show(page,button){
  document.querySelectorAll('.nav button').forEach(x=>x.classList.toggle('on',x===button));
  document.querySelectorAll('main.shell > section').forEach(x=>{x.style.display=x===page?'block':'none'});
}
function kpi(label,value,cls,hint){return `<div class="fd-kpi"><span>${label}</span><b class="${cls||''}">${value}</b><small>${hint||''}</small></div>`}
function finding(f){return `<li class="fd-finding is-${f.severity}"><em>${SEVERITY[f.severity]||''}</em><div><b>${f.title}</b><p>${f.evidence}</p><small>다음 단계 · ${f.next_step}</small></div></li>`}
function row(name,m){return `<tr><th>${name}</th><td>${m.closed}</td><td class="${tone(m.avg_return_pct)}">${pct(m.avg_return_pct)}</td><td>${share(m.win_rate_pct)}</td><td>${share(m.target_hit_pct)}</td><td>${share(m.stop_pct)}</td><td>${has(m.profit_factor)?N(m.profit_factor).toFixed(2):'—'}</td></tr>`}
function table(title,note,rows){return `<div class="fd-box"><h3>${title}</h3><p>${note}</p><div class="fd-scroll"><table class="fd-table"><thead><tr><th></th><th>종료</th><th>평균 수익률</th><th>이익 비율</th><th>목표가 도달</th><th>손절</th><th>PF</th></tr></thead><tbody>${rows.join('')}</tbody></table></div></div>`}
function reachBars(t){return (t.mfe_reach_by_level||[]).map(x=>`<div class="fd-bar"><span>+${x.level_pct}% 이상</span><div><i style="width:${Math.max(0,Math.min(100,N(x.reached_pct)))}%"></i></div><b>${share(x.reached_pct)}</b></div>`).join('')}
function render(d){
  const body=document.getElementById('forwardDiagBody');if(!body)return;
  const o=d.overall||{},t=d.target_reachability||{},s=d.stop_recovery||{},names=d.strategy_names||{};
  if(!o.closed){body.innerHTML='<div class="status">아직 결과가 확정된 추천이 없습니다.</div>';return}
  const list=(d.findings||[]).map(finding).join('');
  body.innerHTML=`
    <div class="fd-hero"><div class="eyebrow">마감 확정 추천 · 실제 결과</div><h2>추천 ${o.closed}건은 실제로 어떻게 됐을까</h2><p>${d.first_market_date||''} ~ ${d.last_market_date||''} 사이에 마감 후 확정된 추천만 셉니다. 백테스트가 아니라 추천 다음 날부터 실제 주가로 판정한 결과입니다.</p></div>
    <div class="fd-kpis">${kpi('한 건당 평균 수익률',pct(o.avg_return_pct),tone(o.avg_return_pct),'수수료 전 · 진입구간 중앙 기준')}${kpi('이익으로 끝난 비율',share(o.win_rate_pct),'',`${o.closed}건 중`)}${kpi('목표가 도달',share(o.target_hit_pct),'','목표가를 실제로 찍은 비율')}${kpi('손절',share(o.stop_pct),'','손절가에 걸린 비율')}${kpi('실제 손익비',has(o.realized_reward_risk)?`${N(o.realized_reward_risk).toFixed(2)} : 1`:'—','',`표시 손익비 중앙값 ${has(t.median_planned_reward_risk)?t.median_planned_reward_risk:'—'} : 1`)}</div>
    <div class="fd-box"><h3>지금 보이는 문제</h3><p>${d.review_ready?'숫자로 확인된 것만 적습니다. 운영 규칙은 여기서 바뀌지 않고, 고칠 안은 따로 검증합니다.':`종료 ${d.minimum_closed_for_review}건이 쌓이면 진단을 표시합니다.`}</p><ul class="fd-findings">${list||'<li class="fd-none">표시할 문제가 없습니다.</li>'}</ul></div>
    <div class="fd-grid"><div class="fd-box"><h3>보유기간 안에 얼마나 올랐나</h3><p>추천 후 관찰기간(중앙값 ${has(t.median_bars_observed)?t.median_bars_observed:'—'}거래일) 동안 한 번이라도 찍은 최고 상승폭입니다. 목표가 중앙값은 +${has(t.median_target_pct)?t.median_target_pct:'—'}%입니다.</p>${reachBars(t)}</div>
    <div class="fd-box"><h3>손절된 종목은 그 뒤 어떻게 됐나</h3><p>${s.mark_date||''} 종가 한 시점 기준이며, 검증된 매매 규칙이 아닙니다.</p><div class="fd-kpis is-two">${kpi('지금 진입가 위에 있는 비율',share(s.stopped_now_above_entry_pct),'',`손절 ${s.stopped||0}건 중`)}${kpi('지금까지 들고 있었다면',pct(s.stopped_avg_mark_return_pct),tone(s.stopped_avg_mark_return_pct),'손절 종목 평균')}</div></div></div>
    ${table('전략별','같은 기간, 전략마다 따로 센 결과입니다.',Object.entries(d.by_strategy||{}).map(([k,m])=>row(names[k]||k,m)))}
    ${table('월별','시장 흐름에 따라 달라지는지 봅니다.',Object.entries(d.by_month||{}).map(([k,m])=>row(k,m)))}
    ${table('엄선점수별','점수가 높을수록 결과가 좋아야 정상입니다.',((d.score_calibration||{}).buckets||[]).map(m=>row(`${m.score_from}~${m.score_to}점`,m)))}
    ${table('끝난 방식별','추천이 어떤 식으로 끝났는지입니다.',Object.entries(d.by_outcome||{}).map(([k,m])=>row(OUTCOME[k]||k,m)))}
    <div class="fd-foot">PF는 번 돈 합계 ÷ 잃은 돈 합계로, 1보다 크면 이익입니다. 이 화면은 기록을 읽기만 하며 추천 규칙·주문에 영향을 주지 않습니다.</div>`;
}
async function load(){const body=document.getElementById('forwardDiagBody');if(!body)return;try{const r=await fetch(`/static/forward_diagnostics.json?ts=${Date.now()}`,{cache:'no-store'});if(!r.ok)throw new Error(String(r.status));render(await r.json())}catch(e){body.innerHTML='<div class="status">실전 성적표를 불러오지 못했습니다. 다음 자동 스캔 후 다시 확인해주세요.</div>'}}
function bind(){ensurePage()}
new MutationObserver(bind).observe(document.documentElement,{childList:true,subtree:true});bind();const timer=setInterval(bind,800);setTimeout(()=>clearInterval(timer),20000);
})();
