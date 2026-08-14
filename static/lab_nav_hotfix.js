(()=>{
  const LAB_IDS=['lab','backtestlab'];
  const mainShell=()=>document.querySelector('main.shell')||document.querySelector('.shell');

  function hoist(id){
    const shell=mainShell(),section=document.getElementById(id);
    if(!shell||!section||section.parentElement===shell)return;
    shell.appendChild(section);
    section.dataset.labHoisted='1';
  }

  function syncSections(){LAB_IDS.forEach(hoist)}

  function reconcile(page){
    syncSections();
    const auto=document.getElementById('lab'),backtest=document.getElementById('backtestlab');
    if(page==='lab'){
      if(auto)auto.style.display='block';
      if(backtest)backtest.style.display='none';
      return;
    }
    if(page==='backtestlab'){
      if(backtest)backtest.style.display='block';
      if(auto)auto.style.display='none';
      return;
    }
    if(auto)auto.style.display='none';
    if(backtest)backtest.style.display='none';
  }

  function bindNav(){
    const nav=document.querySelector('.nav');
    if(!nav||nav.dataset.labVisibilityFix==='1')return;
    nav.dataset.labVisibilityFix='1';
    nav.addEventListener('click',event=>{
      const button=event.target.closest('button[data-page]');
      if(!button||!nav.contains(button))return;
      setTimeout(()=>reconcile(button.dataset.page),0);
    });
  }

  function boot(){
    syncSections();bindNav();
    const observer=new MutationObserver(()=>{syncSections();bindNav()});
    observer.observe(document.body,{childList:true,subtree:true});
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
