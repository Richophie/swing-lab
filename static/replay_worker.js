importScripts('/static/replay_math.js?v=20260816-2');

let poolPromise=null;
const N=(v,d=0)=>{v=Number(v);return Number.isFinite(v)?v:d};
const progress=(id,phase,message)=>postMessage({type:'progress',id,phase,message});

async function loadPool(id){
  if(!poolPromise){
    poolPromise=(async()=>{
      progress(id,'loading','V2 후보풀을 별도 계산 스레드에서 읽는 중…');
      const r=await fetch('/static/replay_backtest_pool_v2.json',{cache:'no-store'});
      if(!r.ok)throw new Error(`V2 후보풀 ${r.status}`);
      const d=await r.json();
      if(!d?.ready||Number(d.version)<2)throw new Error('V2 후보풀이 아직 준비되지 않았습니다.');
      return d;
    })();
  }
  return poolPromise;
}

function meta(p){
  return {
    worker:true,ready:!!p?.ready,version:p?.version,generated_at:p?.generated_at,
    selection_source:p?.selection_source,requested_symbol_count:p?.requested_symbol_count,
    eligible_symbol_count:p?.eligible_symbol_count,available_start:p?.available_start,
    available_end:p?.available_end,strategies:p?.strategies||[],strategy_names:p?.strategy_names||{},
    candidate_count:p?.candidate_count,trade_count:p?.trade_count,path_bars:p?.path_bars,costs:p?.costs||{}
  };
}

function exec(c,p,forcedProfitPct){
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
  const entry=raw*(1+fr),stop=N(c.stop),exitMode=c.exit_mode||'price_plan',hard=exitMode==='sma20_close'?0:stop,orig=N(c.target,NaN),f=N(forcedProfitPct),target=f>0?entry*(1+f/100):orig;
  const noTargetOK=['sma20_close','donchian20_close','day_close'].includes(exitMode);
  if((hard>0&&entry<=hard)||(f<=0&&!noTargetOK&&(!Number.isFinite(orig)||orig<=entry)))return null;
  let out=N(q.at(-1)?.[4]),date=String(q.at(-1)?.[0]||c.entry_date),why='기간종료',hold=Math.max(1,Math.min(q.length,N(c.max_hold,q.length)));
  for(let i=0;i<hold;i++){
    const b=q[i]||[],d=String(b[0]||''),o=N(b[1]),h=N(b[2]),l=N(b[3]),cl=N(b[4]),s20=N(b[5],NaN),dc20=N(b[7],NaN),has=Number.isFinite(target)&&target>entry;
    if(mode==='intraday_trigger'&&exitMode==='day_close'&&i===0){out=cl;date=d;why='당일 종가 청산 · 일봉순서 안전판';break}
    if(hard>0&&o<=hard){out=o;date=d;why='손절 · 갭';break}
    if(hard>0&&l<=hard&&has&&h>=target){out=hard;date=d;why='손절 · 동시터치';break}
    if(hard>0&&l<=hard){out=hard;date=d;why=mode==='intraday_trigger'&&i===0?'손절 · 장중순서 보수판정':'손절';break}
    if(has&&(o>=target||h>=target)){out=target;date=d;why=f>0?`+${f.toFixed(2)}% 강제익절`:'목표가';break}
    if(exitMode==='day_close'){out=cl;date=d;why='당일 종가 청산';break}
    if(exitMode==='sma20_close'&&Number.isFinite(s20)&&cl<s20){out=cl;date=d;why='20일선 종가 이탈';break}
    if(exitMode==='donchian20_close'&&Number.isFinite(dc20)&&cl<dc20){out=cl;date=d;why='Donchian 20일 하단 이탈';break}
    if(i===hold-1){out=cl;date=d;why=exitMode==='sma20_close'||exitMode==='donchian20_close'?'최대보유 종료':'기간종료'}
  }
  const paid=entry*(1+comm),recv=out*(1-fr)*(1-comm),riskFraction=Math.max(.001,(entry-stop)/entry);
  const marks=[];
  for(const b of q){const d=String(b?.[0]||'');if(!d||d>date)break;marks.push([d,Math.max(0,N(b?.[4])*(1-fr)*(1-comm)/paid)])}
  const stressFactor=hard>0?Math.max(0,hard*(1-fr)*(1-comm)/paid):Math.max(0,1-riskFraction);
  return {start_date:c.entry_date,end_date:date,change:recv/paid-1,risk_fraction:riskFraction,stress_factor:stressFactor,marks,priority:N(c.net_risk_reward,N(c.elite_score)/100),key:`${c.symbol}|${c.strategy_id}|${c.signal_date}`,symbol:c.symbol,strategy_id:c.strategy_id,strategy_name:c.strategy_name||c.strategy_id,reason:why,market_state:c.market_state||'unknown'};
}

function makeRows(p,start,end,strategies,forcedProfitPct){
  const selected=new Set(strategies||[]),out=[];
  for(const c of p.trades||[]){
    const entry=String(c.entry_date||'');
    if(!selected.has(c.strategy_id)||entry<start||entry>end)continue;
    const path=[];
    for(const x of c.path||[]){if(String(x?.[0]||'')<=end)path.push(x);else break}
    if(!path.length)continue;
    const r=exec({...c,path},p,forcedProfitPct);if(r)out.push(r);
  }
  return out;
}

function compactAccepted(rows){
  return (rows||[]).map(x=>({
    start_date:x.start_date,end_date:x.end_date,change:x.change,size:x.size,
    symbol:x.symbol,strategy_id:x.strategy_id,strategy_name:x.strategy_name,
    reason:x.reason,market_state:x.market_state
  }));
}

function compactResult(r){
  return {...r,accepted:compactAccepted(r.accepted)};
}

function ablation(rows,initial,options,accepted,full){
  const ids=[...new Set((accepted||[]).map(x=>x.strategy_id).filter(Boolean))];
  if(ids.length<2)return [];
  return ids.map(id=>{
    const name=accepted.find(x=>x.strategy_id===id)?.strategy_name||id;
    const r=globalThis.SwingSequenceReplay.run(rows.filter(x=>x.strategy_id!==id),initial,options);
    return {id,name,ending:r.ending,ret:r.change*100,mdd:r.maxDrawdown*100,delta:(r.change-(full?.change||0))*100,trades:r.accepted.length};
  }).sort((a,b)=>a.delta-b.delta);
}

async function doRun(id,payload){
  const p=await loadPool(id);
  progress(id,'preparing','선택한 기간·전략의 거래 후보를 정리하는 중…');
  const rows=makeRows(p,payload.start,payload.end,payload.strategies,payload.forcedProfitPct||0);
  const options={capacity:Math.max(1,Math.min(20,N(payload.capacity,3))),riskBudget:.01,maxShare:.40};
  progress(id,'simulating',`후보 ${rows.length.toLocaleString('ko-KR')}건을 계좌 단위로 재생하는 중…`);
  const result=globalThis.SwingSequenceReplay.run(rows,N(payload.initial,3000000),options);
  progress(id,'ablation','전략별 기여도를 별도 계산 스레드에서 비교하는 중…');
  const abl=ablation(rows,N(payload.initial,3000000),options,result.accepted,result);
  return {...compactResult(result),ablation:abl,inputRowCount:rows.length,worker:true};
}

onmessage=async e=>{
  const {id,type,payload={}}=e.data||{};
  try{
    if(type==='init'){
      const p=await loadPool(id);postMessage({type:'result',id,data:meta(p)});return;
    }
    if(type==='run'){
      const data=await doRun(id,payload);postMessage({type:'result',id,data});return;
    }
    throw new Error('알 수 없는 Worker 요청입니다.');
  }catch(err){postMessage({type:'error',id,error:String(err?.message||err)});}
};
