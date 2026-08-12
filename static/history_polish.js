(()=>{
  function pctColorize(card){
    card.querySelectorAll('.level').forEach(level=>{
      const s=level.querySelector('span');if(!s)return;
      if(/^TARGET\b/.test(s.textContent))s.innerHTML=s.textContent.replace(/^TARGET/,'목표가').replace(/([+-]\d+(?:\.\d+)?%)/,'<em class="level-pct up">$1</em>');
      if(/^STOP\b/.test(s.textContent))s.innerHTML=s.textContent.replace(/^STOP/,'손절가').replace(/([+-]\d+(?:\.\d+)?%)/,'<em class="level-pct down">$1</em>');
    });
  }
  function polish(card){
    if(!card||card.dataset.historyPolished==='1')return;
    const top=card.querySelector('.picktop');if(!top)return;
    const outcome=top.querySelector('.outcome');
    const status=outcome?.textContent?.trim()||'진행중';
    const cls=outcome?.className||'';
    const hero=document.createElement('div');hero.className='history-status-hero';
    const stateClass=/success/.test(cls)?'success':/stop|loss/.test(cls)?'down':/miss/.test(cls)?'miss':'open';
    hero.innerHTML=`<div class="grade-orb">S</div><div class="history-status-copy"><span class="history-status-solid ${stateClass}">${status}</span></div>`;
    card.insertBefore(hero,top);hero.insertAdjacentHTML('afterend','<div class="card-divider"></div>');
    if(outcome)outcome.remove();
    pctColorize(card);
    card.dataset.historyPolished='1';
  }
  function all(){document.querySelectorAll('.hist-grid .pick').forEach(polish)}
  const root=document.getElementById('historyDays');if(root){new MutationObserver(all).observe(root,{childList:true,subtree:true});all()}
})();