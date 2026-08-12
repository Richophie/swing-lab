(()=>{
  function polishCard(card){
    if(!card || card.dataset.polished==='1') return;
    const hero=card.querySelector('.status-hero');
    const top=card.querySelector('.picktop');
    if(hero&&top){
      card.insertBefore(hero,top);
      hero.insertAdjacentHTML('afterend','<div class="card-divider"></div>');
    }
    const title=card.querySelector('.status-title');
    if(title){
      const nodes=[...title.childNodes];
      const textNode=nodes.find(n=>n.nodeType===Node.TEXT_NODE&&n.textContent.trim());
      if(textNode){
        const label=textNode.textContent.trim();
        const chip=document.createElement('span');
        chip.className='status-solid';chip.textContent=label;
        title.replaceChild(chip,textNode);
      }
    }
    const sub=card.querySelector('.status-sub');
    if(sub){
      const m=sub.textContent.match(/^(\d{4}-\d{2}-\d{2})/);
      sub.textContent=m?`${m[1]} 최초 추천`:'';
    }
    card.querySelectorAll('.level').forEach(level=>{
      const s=level.querySelector('span'); if(!s)return;
      if(/^TARGET\b/.test(s.textContent)) s.innerHTML=s.textContent.replace(/^TARGET/,'목표가').replace(/([+-]\d+(?:\.\d+)?%)/,'<em class="level-pct up">$1</em>');
      if(/^STOP\b/.test(s.textContent)) s.innerHTML=s.textContent.replace(/^STOP/,'손절가').replace(/([+-]\d+(?:\.\d+)?%)/,'<em class="level-pct down">$1</em>');
    });
    card.dataset.polished='1';
  }
  function polishAll(){document.querySelectorAll('#todayGrid .pick').forEach(polishCard)}
  const grid=document.getElementById('todayGrid');
  if(grid){new MutationObserver(polishAll).observe(grid,{childList:true,subtree:true});polishAll()}
})();