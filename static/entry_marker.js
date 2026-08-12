(()=>{
  const NS='http://www.w3.org/2000/svg';
  function n(v){const x=Number(v);return Number.isFinite(x)?x:null}
  function firstPrice(card){
    const level=[...card.querySelectorAll('.level')].find(x=>/최초 추천 BUY|BUY/.test(x.textContent));
    if(!level)return null;
    const txt=level.textContent.replaceAll(',','');
    const m=txt.match(/\$([0-9.]+)\s*~\s*([0-9.]+)/);
    if(!m)return null;
    return (Number(m[1])+Number(m[2]))/2;
  }
  function add(card){
    if(!card||card.dataset.entryMarker==='1')return;
    const dateText=card.querySelector('.status-sub')?.textContent||'';
    if(!/\d{4}-\d{2}-\d{2}/.test(dateText))return;
    const svg=card.querySelector('.mini svg');if(!svg)return;
    const entry=firstPrice(card);if(!entry)return;
    const rect=svg.querySelector('rect[fill="#f2f4f6"],rect[fill="#e8f6ed"]');
    let y=58;
    if(rect){const ry=n(rect.getAttribute('y')),rh=n(rect.getAttribute('height'));if(ry!=null)y=ry+(rh||0)/2}
    const vb=(svg.getAttribute('viewBox')||'0 0 300 126').split(/\s+/).map(Number),w=vb[2]||300;
    const x=Math.max(28,w-82);
    const g=document.createElementNS(NS,'g');g.setAttribute('class','entry-marker-label');
    const dot=document.createElementNS(NS,'circle');dot.setAttribute('cx',x);dot.setAttribute('cy',y);dot.setAttribute('r','4');dot.setAttribute('fill','#16865f');dot.setAttribute('stroke','#fff');dot.setAttribute('stroke-width','2');g.appendChild(dot);
    const label=document.createElementNS(NS,'text');label.setAttribute('x',Math.min(x+7,w-58));label.setAttribute('y',y+3);label.setAttribute('font-size','9');label.setAttribute('font-weight','700');label.setAttribute('fill','#66706b');label.textContent=`$${entry.toFixed(2)}`;g.appendChild(label);
    svg.appendChild(g);card.dataset.entryMarker='1';
  }
  function all(){document.querySelectorAll('#todayGrid .pick').forEach(add)}
  const grid=document.getElementById('todayGrid');if(grid){new MutationObserver(all).observe(grid,{childList:true,subtree:true});all()}
})();