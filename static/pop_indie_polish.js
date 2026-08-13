(()=>{
  const LIVE_TEXT='RSI·볼린저·현재가가 일봉 형성 중 바뀌면 목록에 들어왔다 빠질 수 있습니다. 포착/이탈은 아래 로그에 남기고, 공식 추천은 미국장 마감 후 한 번만 확정합니다.';

  function polishHeading(){
    const grid=document.getElementById('todayGrid');
    const h2=grid?.closest('.panel')?.querySelector('.panel-head h2');
    if(h2&&h2.textContent!=='👌 지금 볼 만한 자리')h2.textContent='👌 지금 볼 만한 자리';
  }

  function polishLiveNote(){
    const live=document.querySelector('.live-mode-banner');
    if(!live||live.dataset.staticNote==='1')return;
    live.innerHTML=`<span class="live-mode-badge">LIVE</span><div class="live-static-copy"><strong>장중엔 후보가 움직여요</strong><span>${LIVE_TEXT}</span></div>`;
    live.dataset.staticNote='1';
  }

  function markEntryCards(){
    document.querySelectorAll('#todayGrid .pick').forEach(card=>{
      const label=card.querySelector('.status-solid')?.textContent?.trim()||'';
      card.classList.toggle('entry-sticker-card',/진입/.test(label));
    });
  }

  function apply(){polishHeading();polishLiveNote();markEntryCards()}
  window.addEventListener('DOMContentLoaded',()=>{
    apply();
    const grid=document.getElementById('todayGrid');
    if(grid){
      const observer=new MutationObserver(()=>markEntryCards());
      observer.observe(grid,{childList:true,subtree:true});
    }
  });
})();
