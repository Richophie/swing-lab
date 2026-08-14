(()=>{const N=(v,d=0)=>{v=Number(v);return Number.isFinite(v)?v:d},baseLoad=window.loadSwingLabPool,baseRows=window.makeSwingReplayRows;
window.loadSwingLabPool=async()=>{try{const r=await fetch('/static/replay_backtest_pool_v2.json',{cache:'no-store'});if(r.ok){const d=await r.json();if(d?.ready&&+d.version>=2)return d}}catch{}return baseLoad()};
function exec(c,p,f){
  const q=c.path||[];if(!q.length)return null;
  const k=p.costs||{},comm=N(k.commission_pct_per_side,.1)/100,fr=(N(k.slippage_bps,5)+N(k.half_spread_bps,2.5))/1e4;
  const atr=N(c.atr),close=N(c.signal_close),mode=c.entry_mode||'next_open';
  let raw;
  if(mode==='intraday_trigger'){
    const first=q[0]||[],trigger=N(c.trigger,NaN),high=N(first[2],NaN);
    if(!Number.isFinite(trigger)||!Number.isFinite(high)||high<trigger)return null;
    raw=trigger;
  }else{
    raw=N(q[0]?.[1]);const gap=Math.max(.75*atr,.01*close),lo=N(c.buy_low),hi=N(c.buy_high);
    if(raw<=0||raw<lo-gap||raw>hi+gap)return null;
  }
  const entry=raw*(1+fr),stop=N(c.stop),exitMode=c.exit_mode||'price_plan',hard=exitMode==='sma20_close'?0:stop,orig=N(c.target,NaN),target=f>0?entry*(1+f/100):orig;
  const noTargetOK=['sma20_close','donchian20_close','day_close'].includes(exitMode);
  if(hard>0&&entry<=hard||f<=0&&!noTargetOK&&(!Number.isFinite(orig)||orig<=entry))return null;
  let out=N(q.at(-1)?.[4]),date=String(q.at(-1)?.[0]||c.entry_date),why='기간종료',hold=Math.max(1,Math.min(q.length,N(c.max_hold,q.length)));
  for(let i=0;i<hold;i++){
    const b=q[i]||[],d=String(b[0]||''),o=N(b[1]),h=N(b[2]),l=N(b[3]),cl=N(b[4]),s20=N(b[5],NaN),dc20=N(b[7],NaN),has=Number.isFinite(target)&&target>entry;
    if(hard>0&&o<=hard){out=o;date=d;why='손절 · 갭';break}
    if(hard>0&&l<=hard&&has&&h>=target){out=hard;date=d;why='손절 · 동시터치';break}
    if(hard>0&&l<=hard){out=hard;date=d;why=mode==='intraday_trigger'&&i===0?'손절 · 장중순서 보수판정':'손절';break}
    if(has&&(o>=target||h>=target)){out=target;date=d;why=f>0?`+${f.toFixed(2)}% 강제익절`:'목표가';break}
    if(exitMode==='day_close'){out=cl;date=d;why='당일 종가 청산';break}
    if(exitMode==='sma20_close'&&Number.isFinite(s20)&&cl<s20){out=cl;date=d;why='20일선 종가 이탈';break}
    if(exitMode==='donchian20_close'&&Number.isFinite(dc20)&&cl<dc20){out=cl;date=d;why='Donchian 20일 하단 이탈';break}
    if(i===hold-1){out=cl;date=d;why=exitMode==='sma20_close'?'최대보유 종료':exitMode==='donchian20_close'?'최대보유 종료':'기간종료'}
  }
  const paid=entry*(1+comm),recv=out*(1-fr)*(1-comm);
  return{start_date:c.entry_date,end_date:date,change:recv/paid-1,risk_fraction:Math.max(.001,(entry-stop)/entry),priority:N(c.net_risk_reward,N(c.elite_score)/100),key:`${c.symbol}|${c.strategy_id}|${c.signal_date}`,symbol:c.symbol,strategy_id:c.strategy_id,strategy_name:c.strategy_name||c.strategy_id,reason:why,market_state:c.market_state||'unknown'};
}
window.makeSwingReplayRows=(p,a,b,s)=>{if(+p?.version<2)return baseRows(p,a,b,s);const on=document.getElementById('btForceProfit')?.checked,f=on?Math.max(.1,Math.min(50,N(document.getElementById('btForceProfitPct')?.value,3))):0,o=[];for(const c of p.trades||[]){if(!s.includes(c.strategy_id)||String(c.entry_date||'')<a||String(c.entry_date||'')>b)continue;const r=exec(c,p,f);if(r)o.push(r)}return o};
})();