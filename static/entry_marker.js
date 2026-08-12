(()=>{
  const NS='http://www.w3.org/2000/svg';
  function n(v){const x=Number(v);return Number.isFinite(x)?x:null}
  function firstPrice(card){
    const level=[...card.querySelectorAll('.level')].find(x=>/최초 추천 BUY|BUY/.test(x.textContent));
    if(!level)return null;
    const txt=level.textContent.replaceAll(',','');
    const m=txt.match(/\$([0-9.]+)\s*~\s*([0-9.]+)/);
    if(!m)return null;return (Number(m[1])+Number(m[2]))/2;
  }
  function add(card){
    if(!card||card.dataset.entryMarker==='1')return;
    const dateText=card.querySelector('.status-sub')?.textContent||'';
    const dm=dateText.match(/(\d{4}-\d{2}-\d{2})/);
    if(!dm)return; // 신규 추천에는 표시하지 않음
    const svg=card.querySelector('.mini svg'); if(!svg)return;
    const entry=firstPrice(card); if(!entry)return;
    const rect=svg.querySelector('rect[fill="#f2f4f6"],rect[fill="#e8f6ed"]');
    let y=58;
    if(rect){const ry=n(rect.getAttribute('y')),rh=n(rect.getAttribute('height'));if(ry!=null)y=ry+(rh||0)/2}
    const vb=(svg.getAttribute('viewBox')||'0 0 300 126').split(/\s+/).map(Number),w=vb[2]||300;
    const date=new Date(dm[1]+'T12:00:00');const age=Math.max(0,Math.round((Date.now()-date.getTime())/86400000));
    const x=Math.max(22,w-16-Math.min(age,16)*12);
    const g=document.createElementNS(NS,'g');g.setAttribute('class','entry-marker-label');
    const line=document.createElementNS(NS,'line');line.setAttribute('x1',x);line.setAttribute('x2',x);line.setAttribute('y1',Math.max(8,y-25));line.setAttribute('y2',y);line.setAttribute('stroke','#16865f');line.setAttribute('stroke-width','1');line.setAttribute('stroke-dasharray','2 3');g.appendChild(line);
    const dot=document.createElementNS(NS,'circle');dot.setAttribute('cx',x);dot.setAttribute('cy',y);dot.setAttribute('r','4');dot.setAttribute('fill','#16865f');dot.setAttribute('stroke','#fff');dot.setAttribute('stroke-width','2');g.appendChild(dot);
    const label=document.createElementNS(NS,'text');label.setAttribute('x',Math.min(x+7,w-104));label.setAttribute('y',Math.max(12,y-9));label.setAttribute('font-size','9');label.setAttribute('font-weight','700');label.setAttribute('fill','#66706b');label.textContent=`최초진입 ${dm[1].slice(5).replace('-','/')} · $${entry.toFixed(2)}`;g.appendChild(label);
    svg.appendChild(g);card.dataset.entryMarker='1';
  }
  function all(){document.querySelectorAll('#todayGrid .pick').forEach(add)}
  const grid=document.getElementById('todayGrid');if(grid){new MutationObserver(all).observe(grid,{childList:true,subtree:true});all()}
})();