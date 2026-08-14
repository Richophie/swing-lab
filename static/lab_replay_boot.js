(()=>{
  const PAGE='backtestlab';
  function ensureSection(){
    let s=document.getElementById(PAGE);if(s)return s;
    const shell=document.querySelector('main.shell'),detail=document.getElementById('detail');if(!shell||!detail)return null;
    s=document.createElement('section');s.id=PAGE;s.style.display='none';
    s.innerHTML='<article class="panel bt-lab-panel"><div class="panel-head bt-lab-page-head"><div><div class="eyebrow">REPLAY LAB · 과거 시뮬레이션</div><h2>백테스트 연구소</h2><p class="paper-head-note">전략 조합을 고르고, 계좌 수익·실제 MTM 낙폭·연도별 안정성까지 한 번에 뜯어봅니다.</p></div><div class="bt-page-badges"><span>US STOCKS</span><span>DAILY MTM</span></div></div><div id="btLabBody"><div class="paper-empty">백테스트 데이터를 불러오는 중…</div></div></article>';
    shell.insertBefore(s,detail);return s
  }
  function swapRender(){const bt=document.getElementById('btLabBody'),shadow=document.querySelector('#lab #labBody');if(!bt||typeof window.renderSwingReplayLab!=='function')return;if(shadow)shadow.id='shadowLabBody';bt.id='labBody';try{window.renderSwingReplayLab()}finally{bt.id='btLabBody';if(shadow)shadow.id='labBody'}setTimeout(enhance,80)}
  function dateMinus(v,y){const a=String(v||'').split('-').map(Number);if(a.length!==3)return'';const d=new Date(a[0],a[1]-1,a[2]);d.setFullYear(d.getFullYear()-y);return[d.getFullYear(),String(d.getMonth()+1).padStart(2,'0'),String(d.getDate()).padStart(2,'0')].join('-')}
  function wrapAdvanced(root){const extra=root.querySelector('.bt-extra-controls');if(!extra||extra.closest('.bt-advanced'))return;const d=document.createElement('details');d.className='bt-advanced';d.innerHTML='<summary>고급 민감도 실험 · 고정익절/강제 보유상한</summary>';extra.parentNode.insertBefore(d,extra);d.appendChild(extra)}
  function enhance(){
    const root=document.getElementById(PAGE);if(!root)return;
    const form=root.querySelector('.btlab-form');
    if(form&&!root.querySelector('#btLabCapacity')){const l=document.createElement('label');l.innerHTML='<span>최대 동시보유</span><select id="btLabCapacity"><option>1</option><option>3</option><option>5</option><option>7</option><option selected>10</option></select>';form.appendChild(l)}
    if(form&&!root.querySelector('.bt-fast-period')){const w=document.createElement('div');w.className='bt-fast-period';w.innerHTML='<b>빠른 기간</b><div><button data-y="10" class="on">10년</button><button data-y="5">5년</button><button data-y="3">3년</button><button data-y="1">1년</button></div>';form.before(w);w.querySelectorAll('button').forEach(b=>b.onclick=()=>{const s=root.querySelector('#btLabStart'),e=root.querySelector('#btLabEnd'),m=root.querySelector('#btLabMeta');if(!s||!e||!e.value)return;const oldest=(m?.textContent.match(/\d{4}-\d{2}-\d{2}/)||[])[0]||'',v=dateMinus(e.value,Number(b.dataset.y));s.value=oldest&&v<oldest?oldest:v;w.querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b))})}
    document.querySelectorAll('.bt-packs').forEach(x=>x.remove());const legacySma=document.querySelector('.bt-extra-box [data-bt-strategy="sma200_20_squeeze"]');legacySma?.closest('.bt-extra-box')?.remove();wrapAdvanced(root);
    if(window.SwingSequenceReplay&&!window.__capacityPatch){window.__capacityPatch=true;const base=window.SwingSequenceReplay.run;window.SwingSequenceReplay.run=(rows,capital,opt={})=>base(rows,capital,{capacity:Number(document.getElementById('btLabCapacity')?.value||10),...opt})}
  }
  function go(b){document.querySelectorAll('.nav button').forEach(x=>x.classList.toggle('on',x===b));['today','search','paper','state','lab',PAGE].forEach(id=>{const x=document.getElementById(id);if(x)x.style.display=id===PAGE?'block':'none'});swapRender()}
  function bind(){const nav=document.querySelector('.nav');if(!nav)return;ensureSection();let b=nav.querySelector(`[data-page="${PAGE}"]`);if(!b){b=document.createElement('button');b.dataset.page=PAGE;nav.appendChild(b)}b.textContent='백테스트연구소';b.onclick=e=>{e.preventDefault();go(b)}}
  const t=setInterval(bind,700);bind();setTimeout(()=>clearInterval(t),20000)
})();