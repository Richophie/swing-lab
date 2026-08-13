(()=>{
  const LIVE_TEXT='RSI·볼린저·현재가가 일봉 형성 중 바뀌면 목록에 들어왔다 빠질 수 있습니다. 포착/이탈은 아래 로그에 남기고, 공식 추천은 미국장 마감 후 한 번만 확정합니다.';

  function polishHeading(){
    const grid=document.getElementById('todayGrid');
    const h2=grid?.closest('.panel')?.querySelector('.panel-head h2');
    if(h2&&h2.textContent!=='👌 지금 볼 만한 자리')h2.textContent='👌 지금 볼 만한 자리';
  }

  function polishLiveTicker(){
    const live=document.querySelector('.live-mode-banner');
    if(!live||live.dataset.popTicker==='1')return;
    const badge=live.querySelector('.live-mode-badge');
    if(!badge)return;
    [...live.children].forEach(el=>{if(el!==badge)el.remove()});
    const marquee=document.createElement('div');
    marquee.className='live-marquee';
    const track=document.createElement('div');
    track.className='live-marquee-track';
    const copy=`<strong>장중엔 후보가 움직여요</strong>${LIVE_TEXT}`;
    track.innerHTML=`<span>${copy}</span><span aria-hidden="true">${copy}</span>`;
    marquee.appendChild(track);live.appendChild(marquee);live.dataset.popTicker='1';
  }

  function markEntryStickers(){
    document.querySelectorAll('#todayGrid .pick').forEach(card=>{
      const label=card.querySelector('.status-solid')?.textContent?.trim()||'';
      card.classList.toggle('entry-sticker-card',/진입/.test(label));
    });
  }

  function apply(){polishHeading();polishLiveTicker();markEntryStickers()}
  window.addEventListener('DOMContentLoaded',()=>{
    apply();
    const observer=new MutationObserver(apply);
    observer.observe(document.body,{childList:true,subtree:true});
  });
})();
