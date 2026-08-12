(()=>{
  function closeDetail(){
    const overlay=document.getElementById('detailOverlay');
    const detail=document.getElementById('detail');
    if(detail)detail.classList.remove('show');
    if(overlay)overlay.classList.remove('open');
    document.body.classList.remove('detail-open');
  }
  function openShell(){
    const overlay=document.getElementById('detailOverlay');
    const detail=document.getElementById('detail');
    if(!overlay||!detail||!detail.classList.contains('show'))return;
    overlay.classList.add('open');
    document.body.classList.add('detail-open');
    overlay.scrollTop=0;
  }
  window.addEventListener('DOMContentLoaded',()=>{
    const detail=document.getElementById('detail');
    if(!detail)return;
    const overlay=document.createElement('div');
    overlay.id='detailOverlay';
    overlay.className='detail-overlay';
    overlay.setAttribute('aria-hidden','true');
    const shell=document.createElement('div');
    shell.className='detail-overlay-shell';
    const close=document.createElement('button');
    close.className='detail-close';
    close.type='button';
    close.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg> 상세 닫기';
    close.onclick=closeDetail;
    shell.appendChild(close);
    detail.parentNode.insertBefore(overlay,detail.nextSibling);
    shell.appendChild(detail);
    overlay.appendChild(shell);
    document.body.appendChild(overlay);
    const observer=new MutationObserver(()=>{
      if(detail.classList.contains('show')){
        overlay.setAttribute('aria-hidden','false');
        openShell();
      }else{
        overlay.setAttribute('aria-hidden','true');
        overlay.classList.remove('open');
        document.body.classList.remove('detail-open');
      }
    });
    observer.observe(detail,{attributes:true,attributeFilter:['class']});
    overlay.addEventListener('click',e=>{if(e.target===overlay)closeDetail()});
    document.addEventListener('keydown',e=>{if(e.key==='Escape'&&overlay.classList.contains('open'))closeDetail()});
  });
})();
