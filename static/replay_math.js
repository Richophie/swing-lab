(()=>{
  function finite(v,d=0){const x=Number(v);return Number.isFinite(x)?x:d}
  function value(cash,open){let x=cash;open.forEach(p=>x+=p.size*finite(p.mark,1));return x}
  function stressed(cash,open){let x=cash;open.forEach(p=>{const mark=finite(p.mark,1),stop=finite(p.row.stress_factor,Math.max(0,1-Math.max(0,finite(p.row.risk_fraction))));x+=p.size*Math.max(0,Math.min(mark,stop))});return x}
  function sizeFor(total,cash,risk,opt){const budget=total*opt.riskBudget,rf=Math.max(finite(risk),.001),byRisk=budget/rf,cap=total*opt.maxShare;return Math.max(0,Math.min(cash,byRisk,cap))}
  function monthly(curve,initial){const out=[],groups=new Map();for(const p of curve){const m=String(p.date||'').slice(0,7);if(!m)continue;(groups.get(m)||groups.set(m,[]).get(m)).push(p)}let prior=finite(initial);for(const [month,pts] of groups){const end=finite(pts.at(-1)?.value,prior);out.push({month,start:prior,end,return_pct:prior>0?(end/prior-1)*100:0});prior=end}return out}
  function run(rows,initial,options={}){
    const opt={capacity:3,riskBudget:.01,maxShare:.40,...options},starts=new Map(),ends=new Map(),markUpdates=new Map();
    rows.forEach((raw,seq)=>{const row={...raw,_seq:seq};if(!row.start_date||!row.end_date)return;(starts.get(row.start_date)||starts.set(row.start_date,[]).get(row.start_date)).push(row);(ends.get(row.end_date)||ends.set(row.end_date,[]).get(row.end_date)).push(row);for(const m of row.marks||[]){const day=String(m?.[0]||''),factor=finite(m?.[1],1);if(!day)continue;(markUpdates.get(day)||markUpdates.set(day,[]).get(day)).push([seq,factor])}});
    const dates=[...new Set([...starts.keys(),...ends.keys(),...markUpdates.keys()])].sort();let cash=finite(initial),peak=cash,maxDrawdown=0,stressPeak=cash,stressDrawdown=0,maxOpen=0,rejectCapacity=0,rejectCash=0,rejectDuplicate=0,underwater=0,maxUnderwater=0;const open=new Map(),openSymbols=new Set(),accepted=[],curve=[];
    for(const day of dates){
      const incoming=[...(starts.get(day)||[])].sort((a,b)=>finite(b.priority)-finite(a.priority)||String(a.key||'').localeCompare(String(b.key||''))||a._seq-b._seq);
      for(const row of incoming){if(row.symbol&&openSymbols.has(row.symbol)){rejectDuplicate++;continue}if(open.size>=opt.capacity){rejectCapacity++;continue}const total=value(cash,open),size=sizeFor(total,cash,row.risk_fraction,opt);if(size<1){rejectCash++;continue}open.set(row._seq,{row,size,mark:1});if(row.symbol)openSymbols.add(row.symbol);cash-=size;accepted.push({...row,size});maxOpen=Math.max(maxOpen,open.size)}
      for(const row of [...(ends.get(day)||[])].sort((a,b)=>a._seq-b._seq)){const p=open.get(row._seq);if(!p)continue;cash+=p.size*(1+finite(row.change));if(p.row.symbol)openSymbols.delete(p.row.symbol);open.delete(row._seq)}
      for(const [seq,factor] of markUpdates.get(day)||[]){const p=open.get(seq);if(p)p.mark=factor}
      const total=value(cash,open);if(total>=peak){peak=total;underwater=0}else{underwater++;maxUnderwater=Math.max(maxUnderwater,underwater);if(peak>0)maxDrawdown=Math.min(maxDrawdown,total/peak-1)}const stress=stressed(cash,open);stressPeak=Math.max(stressPeak,stress);if(stressPeak>0)stressDrawdown=Math.min(stressDrawdown,stress/stressPeak-1);curve.push({date:day,value:total,cash,open:open.size})
    }
    if(open.size){open.forEach(p=>cash+=p.size*(1+finite(p.row.change)));open.clear();openSymbols.clear()}
    const months=monthly(curve,initial),worstMonth=months.length?[...months].sort((a,b)=>a.return_pct-b.return_pct)[0]:null;
    return {ending:cash,change:cash/initial-1,maxDrawdown,stressDrawdown,accepted,curve,maxOpen,rejectCapacity,rejectCash,rejectDuplicate,underwaterDays:maxUnderwater,monthly:months,worstMonth,mtm:true}
  }
  globalThis.SwingSequenceReplay={run};
})();
