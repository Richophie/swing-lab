(()=>{
  const cls=code=>String(code||'UNKNOWN').toLowerCase().replaceAll('_','-');
  const rows=()=>Array.isArray(globalThis.latest?.results)?globalThis.latest.results:(typeof latest!=='undefined'&&Array.isArray(latest?.results)?latest.results:[]);
  const rowFor=symbol=>rows().find(r=>String(r.symbol||'').toUpperCase()===String(symbol||'').toUpperCase());
  const shortLabel=er=>{
    if(!er)return'';
    if(er.risk_code==='IMMINENT')return`실적 ${er.days_until}일 전`;
    if(er.risk_code==='WITHIN_HOLD')return'보유기간 중 실적';
    if(er.risk_code==='UPCOMING')return`실적 ${er.days_until}일 전`;
    if(er.risk_code==='UNKNOWN')return'실적일 확인 필요';
    return'';
  };
  const confidenceText=er=>er?.confidence==='confirmed'?'2개 소스 일치':er?.confidence==='single_source'?'단일 소스':er?.confidence==='conflicting'?'소스 날짜 불일치':'확인 불가';
  function decorateCards(){
    document.querySelectorAll('.pick[data-symbol]').forEach(card=>{
      if(card.querySelector('.event-risk-badge'))return;
      const er=rowFor(card.dataset.symbol)?.event_risk;
      const label=shortLabel(er);
      if(!er||!label)return;
      const top=card.querySelector('.picktop');if(!top)return;
      const badge=document.createElement('span');
      badge.className=`event-risk-badge ${cls(er.risk_code)}${er.stale?' stale':''}`;
      badge.textContent=label;
      badge.title=`예정일 ${er.earnings_date||'확인 필요'} · ${confidenceText(er)}${er.stale?' · 캐시 갱신 지연':''}`;
      top.appendChild(badge);
    });
  }
  function detailSymbol(){
    const text=document.getElementById('detailTicker')?.textContent||'';
    const m=text.toUpperCase().match(/[A-Z][A-Z0-9.-]{0,9}/);
    return m?.[0]||null;
  }
  function decorateDetail(){
    const reason=document.getElementById('detailReason');if(!reason)return;
    const old=document.getElementById('detailEventRisk');if(old)old.remove();
    const symbol=detailSymbol();if(!symbol)return;
    const er=rowFor(symbol)?.event_risk;if(!er)return;
    const box=document.createElement('div');box.id='detailEventRisk';box.className=`detail-event-risk ${cls(er.risk_code)}`;
    const date=er.earnings_date||'확인 필요';
    const days=Number.isFinite(Number(er.days_until))?`${er.days_until}일 남음`:'남은 일수 확인 필요';
    const hold=Number.isFinite(Number(er.hold_calendar_days))?`예상 보유창 약 ${er.hold_calendar_days}일`:'';
    const warning=er.risk_code==='IMMINENT'||er.risk_code==='WITHIN_HOLD'?'실적 발표는 overnight gap으로 STOP 가격을 건너뛸 수 있어 주문 전 별도 확인이 필요합니다.':'이 정보는 추천 점수나 BUY/TARGET/STOP에 영향을 주지 않는 참고 경고입니다.';
    box.innerHTML=`<div><strong>EVENT RISK · ${er.risk_label||'실적 일정'}</strong><p>실적 예정 ${date} · ${days}${hold?` · ${hold}`:''} · ${confidenceText(er)}${er.stale?' · 캐시 갱신 지연':''}<br>${warning}</p></div>`;
    reason.insertAdjacentElement('afterend',box);
  }
  let scheduled=false;
  function render(){scheduled=false;decorateCards();decorateDetail()}
  function schedule(){if(scheduled)return;scheduled=true;requestAnimationFrame(render)}
  const observer=new MutationObserver(schedule);
  observer.observe(document.body,{subtree:true,childList:true,characterData:true});
  document.addEventListener('DOMContentLoaded',schedule);
  window.addEventListener('load',schedule);
})();
