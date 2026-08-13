(()=>{
  let cached=null,rendering=false;
  const esc=v=>String(v??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  function eventTime(at){try{return new Date(at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}catch{return at||'—'}}
  function render(data){
    const host=document.getElementById('signalEventList'),meta=document.getElementById('signalEventMeta');
    if(!host||!data)return false;
    if(meta)meta.textContent=`현재 엄선 ${data.active_count||0}개 · 이탈 이유까지 기록`;
    const events=data.events||[];
    rendering=true;
    host.innerHTML=events.length?events.slice(0,24).map(e=>{
      const exit=e.event==='EXIT';
      const reason=exit&&e.exit_reason?`<small class="exit-reason"><b>이탈 이유</b>${esc(e.exit_reason)}</small>`:'';
      return `<div class="signal-event ${exit?'exit':''}"><span class="event-badge">${exit?'이탈':'포착'}</span><div><b>${esc(e.name_ko||e.security_name||e.symbol)} · ${esc(e.symbol)}</b><small>${esc(e.strategy_name||e.strategy_id)}${e.score!=null?` · 당시 엄선 ${Math.round(Number(e.score))}점`:''}</small>${reason}</div><time>${esc(eventTime(e.at))}</time></div>`;
    }).join(''):'<div class="paper-empty">아직 저장된 장중 변동 로그가 없어요. 다음 자동 스캔부터 포착/이탈과 이탈 이유가 기록됩니다.</div>';
    host.dataset.exitReasons='1';
    rendering=false;
    return true;
  }
  async function load(){
    try{
      const r=await fetch('/api/signal-events?limit=40',{cache:'no-store'}),data=await r.json();
      if(!r.ok||data.error)throw new Error(data.error||`서버 ${r.status}`);
      cached=data;
      let tries=0;
      const paint=()=>{if(render(cached))return;if(++tries<20)setTimeout(paint,150)};
      paint();
    }catch(e){console.warn('signal exit reason UI',e)}
  }
  window.addEventListener('DOMContentLoaded',()=>{
    setTimeout(load,250);
    const observer=new MutationObserver(()=>{
      if(rendering||!cached)return;
      const host=document.getElementById('signalEventList');
      if(!host)return;
      const hasDetailedExit=(cached.events||[]).slice(0,24).some(e=>e.event==='EXIT'&&e.exit_reason);
      if(hasDetailedExit&&!host.querySelector('.exit-reason'))render(cached);
    });
    observer.observe(document.body,{childList:true,subtree:true});
  });
})();
