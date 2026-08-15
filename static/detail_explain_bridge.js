(()=>{
  function ensureDetailExplain(){
    const reason=document.getElementById('detailReason');
    if(!reason||document.getElementById('detailExplain'))return;
    const explain=document.createElement('div');
    explain.id='detailExplain';
    explain.className='detail-insight';
    reason.insertAdjacentElement('afterend',explain);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ensureDetailExplain);
  else ensureDetailExplain();
  new MutationObserver(ensureDetailExplain).observe(document.documentElement,{childList:true,subtree:true});
})();
