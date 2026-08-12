(()=>{
  const status=document.getElementById('status');
  const scanTime=document.getElementById('scanTime');
  const marketWrap=document.querySelector('.market-refresh-wrap');
  if(!status||!scanTime)return;
  let marketMsg=document.getElementById('marketRefreshStatus');
  if(!marketMsg&&marketWrap){marketMsg=document.createElement('span');marketMsg.id='marketRefreshStatus';marketMsg.className='market-refresh-status';marketWrap.prepend(marketMsg)}
  let timer=null;
  const flashMarket=(text)=>{if(!marketMsg)return;marketMsg.textContent=text;marketMsg.classList.add('show');clearTimeout(timer);timer=setTimeout(()=>marketMsg.classList.remove('show'),2200)};
  const sync=()=>{
    const text=(status.textContent||'').trim();
    const parts=text.split('·').map(x=>x.trim()).filter(Boolean);
    const stamp=parts.length?parts[parts.length-1]:'';
    if(/\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\./.test(stamp)) scanTime.textContent=stamp;
    else if(/시장 상태를 현재 데이터/.test(text)) flashMarket('시장만 다시 확인됨');
    else if(/최신 저장 결과를 불러오는 중/.test(text)) scanTime.textContent='불러오는 중…';
  };
  new MutationObserver(sync).observe(status,{childList:true,subtree:true,characterData:true});
  sync();
})();