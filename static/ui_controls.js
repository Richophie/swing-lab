(()=>{
  const status=document.getElementById('status');
  const scanTime=document.getElementById('scanTime');
  if(!status||!scanTime)return;

  const sync=()=>{
    const text=(status.textContent||'').trim();
    const parts=text.split('·').map(x=>x.trim()).filter(Boolean);
    const stamp=parts.length?parts[parts.length-1]:'';
    if(/\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\./.test(stamp)) scanTime.textContent=stamp;
    else if(/시장 상태를 현재 데이터/.test(text)) scanTime.textContent='시장만 다시 확인됨';
    else if(/불러오는 중|확인 중/.test(text)) scanTime.textContent='불러오는 중…';
  };

  new MutationObserver(sync).observe(status,{childList:true,subtree:true,characterData:true});
  sync();
})();
