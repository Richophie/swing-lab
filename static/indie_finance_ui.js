(()=>{
  function text(el,value){if(el&&el.textContent!==value)el.textContent=value}
  function apply(){
    const brand=document.querySelector('.brand');
    if(brand){text(brand.querySelector('small'),'SWING LAB · PAPER MODE');text(brand.querySelector('h1'),'오늘, 들어갈 만한 자리');text(brand.querySelector('p'),'과열은 거르고, 눌림은 선명하게. 차트·수급·시장환경·손익비를 한 화면에서 빠르게 봅니다.')}

    const navToday=document.querySelector('.nav button[data-page="today"]');
    const navSearch=document.querySelector('.nav button[data-page="search"]');
    const navState=document.querySelector('.nav button[data-page="state"]');
    const navPaper=document.querySelector('.nav button[data-page="paper"]');
    text(navToday,'⚡ 실시간 후보');text(navSearch,'종목 찾기');text(navState,'엔진');text(navPaper,'🧪 가상계좌');

    const todayGrid=document.getElementById('todayGrid'),todayPanel=todayGrid?.closest('.panel');
    if(todayPanel){text(todayPanel.querySelector('.eyebrow'),'LIVE PICKS · 지금 조건 통과');text(todayPanel.querySelector('.panel-head h2'),'👌 지금 볼 만한 자리')}

    const market=document.querySelector('.market-panel');
    if(market)text(market.querySelector('.market-copy-zone .eyebrow'),'MARKET VIBE · SPY / QQQ');

    const history=document.getElementById('historyDays')?.closest('.panel');
    if(history){text(history.querySelector('.eyebrow'),'OFFICIAL PICKS · 마감 확정');text(history.querySelector('.panel-head h2'),'추천 아카이브')}

    const signal=document.getElementById('signalEventPanel');
    if(signal){text(signal.querySelector('.eyebrow'),'INTRADAY LOG');text(signal.querySelector('h2'),'⚡ 장중 포착 · 이탈')}

    const paper=document.getElementById('paper');
    if(paper){text(paper.querySelector('.eyebrow'),'PAPER MODE · 실제주문 없음');text(paper.querySelector('h2'),'🧪 300만원 가상계좌')}

    const detailExplain=document.getElementById('detailExplain');
    if(detailExplain)text(detailExplain.querySelector('h3'),'🧭 이 자리를 어떻게 읽었는지');

    const btBtn=document.getElementById('btBtn'),btHead=btBtn?.closest('.panel-head');
    if(btHead){text(btHead.querySelector('.eyebrow'),'🧪 BACKTEST · 참고자료');text(btHead.querySelector('h2'),'과거에선 어땠을까?')}

    const capital=document.getElementById('capital'),calcHead=capital?.closest('.detail')?.querySelectorAll('.panel-head');
    if(calcHead?.length){const head=[...calcHead].find(h=>h.querySelector('h2')?.textContent.includes('필요 투자금')||h.querySelector('.eyebrow')?.textContent.includes('내 돈'));if(head){text(head.querySelector('.eyebrow'),'💸 내 돈으로 계산');text(head.querySelector('h2'),'이 자리면 얼마가 필요할까?')}}

    const live=document.querySelector('.live-mode-banner');
    if(live){const b=live.querySelector('b');text(b,'장중엔 후보가 움직여요')}
  }
  window.addEventListener('DOMContentLoaded',()=>{
    // One-shot polish only. A previous body-wide MutationObserver competed with
    // pop_indie_polish.js over the same heading and could starve the main thread.
    apply();
    setTimeout(apply,250);
    setTimeout(apply,900);
  });
})();