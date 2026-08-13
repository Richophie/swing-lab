(()=>{
  const CLIENT_KEY='swingLabPaperClientV1';
  let lastFetch=0, inFlight=false, lastSignature='';

  function num(v){const n=Number(v);return Number.isFinite(n)?n:null}
  function usd(v){const n=num(v);return n==null?'—':`$${n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}`}
  function krw(v){const n=num(v);return n==null?'—':`${Math.round(n).toLocaleString('ko-KR')}원`}
  function clientId(){return localStorage.getItem(CLIENT_KEY)||''}
  function timeText(v){
    if(!v)return'';
    try{return new Date(v).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}
    catch{return''}
  }
  function injectStyle(){
    if(document.getElementById('paperMarkStyle'))return;
    const s=document.createElement('style');s.id='paperMarkStyle';s.textContent=`
      .paper-live-summary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:0 0 10px}.paper-live-stat{padding:12px 14px;border:1px solid #e8ebee;border-radius:14px;background:#f8f9f7}.paper-live-stat span{display:block;color:#939a9f;font-size:9px;margin-bottom:4px}.paper-live-stat b{font-size:15px;letter-spacing:-.035em}.paper-live-stat small{display:block;margin-top:3px;color:#a0a6aa;font-size:8px;line-height:1.35}.paper-live-stat b.up{color:#ff7d88}.paper-live-stat b.down{color:#76a1ff}
      .paper-mark-price b{font-size:12px!important}.paper-mark-price small{display:block;margin-top:2px;color:#a0a6aa;font-size:8px;line-height:1.3}
      .paper-pnl.paper-live{font-size:12px!important}.paper-pnl.paper-live.up{color:#ff7d88!important}.paper-pnl.paper-live.down{color:#76a1ff!important}
    `;document.head.appendChild(s);
  }
  function cards(){return [...document.querySelectorAll('.paper-order')]}
  function symbolOf(card){return (card.querySelector('.paper-order-name .ticker')?.textContent||'').trim().toUpperCase()}
  function strategyOf(card){return (card.querySelector('.paper-order-sub')?.textContent||'').split(' · ')[0].trim()}
  function field(grid,label){return [...grid.children].find(x=>x.querySelector('span')?.textContent?.trim()===label)||null}
  function decorate(card,mark){
    const grid=card.querySelector('.paper-order-grid');if(!grid||!mark)return;
    let priceCell=grid.querySelector('.paper-mark-price');
    if(!priceCell){priceCell=document.createElement('div');priceCell.className='paper-mark-price';grid.insertBefore(priceCell,grid.firstChild)}
    const source=mark.price_source==='1m'?'최근 1분 데이터':mark.price_source==='daily'?'최근 일봉':'가격 확인 실패';
    priceCell.innerHTML=`<span>현재가</span><b>${usd(mark.current_price_usd)}</b><small>${source}${mark.price_at?` · ${timeText(mark.price_at)}`:''}</small>`;

    const pnlCell=field(grid,'손익');
    if(pnlCell&&mark.status==='FILLED'){
      const pnl=num(mark.unrealized_pnl_krw),ret=num(mark.unrealized_return_pct),b=pnlCell.querySelector('b');
      if(b){
        b.classList.add('paper-live');b.classList.toggle('up',pnl!=null&&pnl>=0);b.classList.toggle('down',pnl!=null&&pnl<0);
        b.textContent=pnl==null?'—':`${pnl>=0?'+':''}${krw(pnl)}${ret!=null?` · ${ret>=0?'+':''}${ret.toFixed(2)}%`:''}`;
        b.title='현재가에 설정된 스프레드·슬리피지·매도 수수료를 적용해 지금 청산한다고 가정한 평가손익';
      }
    }
  }
  function paintSummary(summary){
    const orders=document.querySelector('.paper-orders');if(!orders||!summary)return;
    let host=orders.parentElement?.querySelector('.paper-live-summary');
    if(!host){host=document.createElement('div');host.className='paper-live-summary';orders.parentElement?.insertBefore(host,orders)}
    const pnl=num(summary.unrealized_pnl_krw),equity=num(summary.equity_krw);const cls=pnl==null?'':pnl>=0?'up':'down';
    host.innerHTML=`<div class="paper-live-stat"><span>현재 평가자산</span><b>${krw(equity)}</b><small>보유종목을 지금 청산한다고 가정</small></div><div class="paper-live-stat"><span>미실현손익</span><b class="${cls}">${pnl==null?'—':`${pnl>=0?'+':''}${krw(pnl)}`}</b><small>스프레드·슬리피지·매도수수료 반영</small></div>`;
  }
  function paint(data){
    const rows=Array.isArray(data?.orders)?data.orders:[],queues=new Map();
    rows.forEach(r=>{const key=String(r.symbol||'').toUpperCase();if(!queues.has(key))queues.set(key,[]);queues.get(key).push(r)});
    cards().forEach(card=>{
      const symbol=symbolOf(card),q=queues.get(symbol)||[];if(!q.length)return;
      const strategy=strategyOf(card);
      let i=q.findIndex(r=>!strategy||strategy.includes(r.strategy_id)||strategy.includes(r.strategy_name||''));if(i<0)i=0;
      const mark=q.splice(i,1)[0];decorate(card,mark);
    });
    paintSummary(data?.summary);
  }
  async function refresh(force=false){
    const list=cards();if(!list.length||inFlight)return;
    const signature=list.map(c=>`${symbolOf(c)}|${c.querySelector('.paper-status')?.textContent||''}`).join(',');
    const now=Date.now();if(!force&&signature===lastSignature&&now-lastFetch<30000)return;
    inFlight=true;lastFetch=now;lastSignature=signature;
    try{
      const headers={};const id=clientId();if(id)headers['X-Paper-Client']=id;
      const r=await fetch('/api/paper/marks',{cache:'no-store',headers});const data=await r.json();
      if(!r.ok||data.error)throw new Error(data.error||`서버 ${r.status}`);paint(data);
    }catch(e){console.warn('paper mark-to-market',e)}finally{inFlight=false}
  }
  function boot(){injectStyle();setInterval(()=>refresh(false),5000);setTimeout(()=>refresh(true),500)}
  if(document.readyState==='loading')window.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
