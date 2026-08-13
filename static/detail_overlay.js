(()=>{
  function isDetailOpen(detail){
    return !!detail&&(detail.classList.contains('show')||detail.style.display==='block');
  }
  function closeDetail(){
    const overlay=document.getElementById('detailOverlay');
    const detail=document.getElementById('detail');
    if(detail){
      detail.classList.remove('show');
      detail.style.display='none';
    }
    if(overlay){
      overlay.classList.remove('open');
      overlay.setAttribute('aria-hidden','true');
    }
    document.body.classList.remove('detail-open');
  }
  function openShell(){
    const overlay=document.getElementById('detailOverlay');
    const detail=document.getElementById('detail');
    if(!overlay||!isDetailOpen(detail))return;
    overlay.classList.add('open');
    overlay.setAttribute('aria-hidden','false');
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
    detail.parentNode.insertBefore(overlay,detail.nextSibling);
    shell.appendChild(close);
    shell.appendChild(detail);
    overlay.appendChild(shell);
    document.body.appendChild(overlay);
    const observer=new MutationObserver(()=>{
      if(isDetailOpen(detail)){
        openShell();
      }else{
        overlay.setAttribute('aria-hidden','true');
        overlay.classList.remove('open');
        document.body.classList.remove('detail-open');
      }
    });
    // dashboard.js historically opens the detail with inline display:block,
    // while newer UI code may use the .show class. Observe both so card clicks
    // and future callers share one overlay contract.
    observer.observe(detail,{attributes:true,attributeFilter:['class','style']});
    overlay.addEventListener('click',e=>{if(e.target===overlay)closeDetail()});
    document.addEventListener('keydown',e=>{if(e.key==='Escape'&&overlay.classList.contains('open'))closeDetail()});
    if(isDetailOpen(detail))openShell();
  });
})();