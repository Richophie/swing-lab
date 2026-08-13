(()=>{
  const PAGE='backtestlab';
  function ensureSection(){
    let section=document.getElementById(PAGE);if(section)return section;
    const detail=document.getElementById('detail');if(!detail)return null;
    section=document.createElement('section');section.id=PAGE;section.style.display='none';
    section.innerHTML='<article class="panel"><div class="panel-head"><div><div class="eyebrow">REPLAY LAB · 과거 데이터 시뮬레이션</div><h2>백테스트연구소</h2><p class="paper-head-note">기간·전략·자금·동시보유 수를 바꿔 같은 후보를 한 계좌에서 다시 재생합니다. 자동거래연구소의 forward 연구장부와는 완전히 별개입니다.</p></div></div><div id="btLabBody"><div class="paper-empty">백테스트 데이터를 불러오는 중…</div></div></article>';
    detail.parentNode.insertBefore(section,detail);return section;
  }
  function go(button){
    document.querySelectorAll('.nav button').forEach(x=>x.classList.toggle('on',x===button));
    ['today','search','paper','state','lab',PAGE].forEach(id=>{const x=document.getElementById(id);if(x)x.style.display=id===PAGE?'block':'none'});
    window.renderSwingReplayLab?.();
  }
  function bind(){
    const nav=document.querySelector('.nav');if(!nav)return;
    ensureSection();let button=nav.querySelector(`[data-page="${PAGE}"]`);
    if(!button){button=document.createElement('button');button.dataset.page=PAGE;button.textContent='백테스트연구소';nav.appendChild(button)}
    button.textContent='백테스트연구소';button.onclick=e=>{e.preventDefault();go(button)};
    const h=document.querySelector(`#${PAGE} h2`);if(h)h.textContent='백테스트연구소';
  }
  const timer=setInterval(bind,500);bind();setTimeout(()=>clearInterval(timer),20000);
})();
