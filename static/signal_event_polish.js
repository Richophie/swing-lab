(()=>{
  let cached=null;
  const esc=v=>String(v??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  function eventTime(at){try{return new Date(at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}catch{return at||'—'}}
  function badge(e){if(e.event==='EXIT')return'이탈';if(e.event==='REENTER')return'↩ 재포착';if(e.event==='ELITE_ENTER')return'⭐ 엄선 승격';if(e.event==='ELITE_EXIT')return'엄선 해제';return e.elite_pass?'👀 엄선 포착':'👀 S 포착'}
  function rowClass(e){if(e.event==='EXIT')return'exit';if(e.event==='ELITE_EXIT')return'elite-exit';if(e.event==='ELITE_ENTER')return'elite-enter';return'capture'}
  function reasonText(e){
    if(!e||!['EXIT','ELITE_EXIT'].includes(e.event))return'';
    if(e.exit_reason_code&&e.exit_reason)return e.exit_reason;
    if(e.exit_reason==='현재 엄선 조건에서 이탈')return '현재 엄선 조건에서 이탈 · 세부 이유는 구버전 로그라 미저장';
    return e.exit_reason||'세부 이유는 구버전 로그라 미저장';
  }
  function scoreText(e){
    const s=Number(e.strategy_score),elite=Number(e.elite_score),parts=[];
    if(Number.isFinite(s))parts.push(`전략 S ${Math.round(s)}점`);
    if(e.elite_pass&&Number.isFinite(elite))parts.push(`엄선 ${Math.round(elite)}점`);
    else if(Number.isFinite(elite))parts.push(`엄선 ${Math.round(elite)}점 미통과`);
    if(e.event==='ELITE_EXIT')parts.push('전략 S는 유지');
    return parts.join(' · ');
  }
  function render(data){
    const host=document.getElementById('signalEventList'),meta=document.getElementById('signalEventMeta');
    if(!host||!data)return false;
    if(meta)meta.textContent=`현재 전략 S ${data.active_count||0}개 · S 포착/이탈과 엄선 승격/해제를 따로 기록`;
    const events=data.events||[];
    host.innerHTML=events.length?events.slice(0,28).map(e=>{
      const reasonValue=reasonText(e),isEliteExit=e.event==='ELITE_EXIT';
      const reason=reasonValue?`<small class="exit-reason"><b>${isEliteExit?'엄선 해제 이유':'이탈 이유'}</b>${esc(reasonValue)}</small>`:'';
      return `<div class="signal-event ${rowClass(e)}"><span class="event-badge">${esc(badge(e))}</span><div><b>${esc(e.name_ko||e.security_name||e.symbol)} · ${esc(e.symbol)}</b><small>${esc(e.strategy_name||e.strategy_id)}${scoreText(e)?` · ${esc(scoreText(e))}`:''}</small>${reason}</div><time>${esc(eventTime(e.at))}</time></div>`;
    }).join(''):'<div class="paper-empty">아직 저장된 장중 변동 로그가 없어요. 다음 자동 스캔부터 S 포착/이탈과 엄선 승격/해제를 나눠 기록합니다.</div>';
    host.dataset.exitReasons='1';
    return true;
  }
  async function load(){
    try{
      const r=await fetch('/api/signal-events?limit=50',{cache:'no-store'}),data=await r.json();
      if(!r.ok||data.error)throw new Error(data.error||`서버 ${r.status}`);
      cached=data;let tries=0;
      const paint=()=>{if(render(cached))return;if(++tries<30)setTimeout(paint,150)};
      paint();
    }catch(e){console.warn('signal event UI',e)}
  }
  window.addEventListener('DOMContentLoaded',()=>{setTimeout(load,350);setTimeout(()=>cached&&render(cached),1200)});
})();