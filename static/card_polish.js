(()=>{
  function polishLevels(card){
    card.querySelectorAll('.level').forEach(level=>{
      const s=level.querySelector('span'); if(!s)return;
      if(/^TARGET\b/.test(s.textContent)) s.innerHTML=s.textContent.replace(/^TARGET/,'목표가').replace(/([+-]\d+(?:\.\d+)?%)/,'<em class="level-pct up">$1</em>');
      if(/^STOP\b/.test(s.textContent)) s.innerHTML=s.textContent.replace(/^STOP/,'손절가').replace(/([+-]\d+(?:\.\d+)?%)/,'<em class="level-pct down">$1</em>');
    });
  }
  function polishToday(card){
    if(card.dataset.polished==='1')return;
    const hero=card.querySelector('.status-hero');const top=card.querySelector('.picktop');
    if(hero&&top){card.insertBefore(hero,top);hero.insertAdjacentHTML('afterend','<div class="card-divider"></div>')}
    const title=card.querySelector('.status-title');
    if(title){const node=[...title.childNodes].find(n=>n.nodeType===Node.TEXT_NODE&&n.textContent.trim());if(node){const chip=document.createElement('span');chip.className='status-solid';chip.textContent=node.textContent.trim();title.replaceChild(chip,node)}}
    const sub=card.querySelector('.status-sub');if(sub){const m=sub.textContent.match(/^(\d{4}-\d{2}-\d{2})/);sub.textContent=m?`${m[1]} 최초 추천`:''}
    polishLevels(card);card.dataset.polished='1';
  }
  function polishHistory(card){
    if(card.dataset.historyPolished==='1')return;
    const top=card.querySelector('.picktop');const outcome=card.querySelector('.outcome');
    if(top&&outcome){
      const day=card.closest('.history-day')?.querySelector('.history-title h3')?.textContent?.trim()||'';
      const hero=document.createElement('div');hero.className='status-hero history-status';
      hero.innerHTML=`<div class="grade-orb">S</div><div class="status-copy"><div class="status-title"><span class="status-solid history-outcome">${outcome.textContent}</span></div>${day?`<div class="status-sub">${day} 최초 추천</div>`:''}</div>`;
      outcome.remove();card.insertBefore(hero,top);hero.insertAdjacentHTML('afterend','<div class="card-divider"></div>');
    }
    polishLevels(card);card.dataset.historyPolished='1';
  }
  function all(){document.querySelectorAll('#todayGrid .pick').forEach(polishToday);document.querySelectorAll('#historyDays .pick').forEach(polishHistory)}
  ['todayGrid','historyDays'].forEach(id=>{const el=document.getElementById(id);if(el)new MutationObserver(all).observe(el,{childList:true,subtree:true})});
  all();
})();