(()=>{
  const PLOT_LEFT='48',PLOT_RIGHT='900';

  function tune(){
    const host=document.getElementById('bigChart');
    const svg=host?.querySelector('svg');
    if(!svg||svg.dataset.guidePolished==='1')return;

    // TARGET and STOP are rendered as short dashed rail ticks by dashboard.js.
    // Extend only those two guides across the entire price plot.
    const target=svg.querySelector('line[stroke="#d94b4b"][stroke-dasharray]');
    const stop=svg.querySelector('line[stroke="#3777d0"][stroke-dasharray]');
    [target,stop].forEach(line=>{
      if(!line)return;
      line.setAttribute('x1',PLOT_LEFT);
      line.setAttribute('x2',PLOT_RIGHT);
      line.setAttribute('stroke-dasharray','6 6');
      line.setAttribute('stroke-width','1.4');
    });

    // Keep the NOW price label in the right rail, but remove its dashed guide.
    const now=svg.querySelector('line[stroke="#17191c"][stroke-dasharray]');
    if(now)now.remove();

    svg.dataset.guidePolished='1';
  }

  window.addEventListener('DOMContentLoaded',()=>{
    const host=document.getElementById('bigChart');
    if(!host)return;
    tune();
    new MutationObserver(tune).observe(host,{childList:true,subtree:true});
  });
})();
