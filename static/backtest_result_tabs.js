(()=>{
  const fmtPct=(v,d=2)=>`${Number(v)>=0?'+':''}${Number(v||0).toFixed(d)}%`;
  const fmtWon=v=>`${Math.round(Number(v)||0).toLocaleString('ko-KR')}원`;
  const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const days=(a,b)=>Math.max(0,Math.round((new Date(`${b}T12:00:00`)-new Date(`${a}T12:00:00`))/86400000));
  const mean=a=>a.length?a.reduce((x,y)=>x+y,0)/a.length:0;
  const median=a=>{if(!a.length)return 0;const b=[...a].sort((x,y)=>x-y),m=Math.floor(b.length/2);return b.length%2?b[m]:(b[m-1]+b[m])/2};
  function captureRunner(){
    const api=window.SwingSequenceReplay;
    if(!api||api.__deepTabsWrapped)return false;
    const base=api.run.bind(api);
    api.__deepTabsWrapped=true;
    api.__deepTabsBase=base;
    api.run=(rows,initial,options={})=>{
      const result=base(rows,initial,options);
      window.__lastSwingReplay={rows,initial,options,result,at:Date.now()};
      setTimeout(()=>enhance(result,rows,initial,options),0);
      return result;
    };
    return true;
  }
  function pnlStats(rows){
    const changes=rows.map(x=>Number(x.change)||0);
    const pnls=rows.map(x=>(Number(x.size)||0)*(Number(x.change)||0));
    const gp=pnls.filter(x=>x>0).reduce((a,b)=>a+b,0),gl=Math.abs(pnls.filter(x=>x<0).reduce((a,b)=>a+b,0));
    return {trades:rows.length,wins:changes.filter(x=>x>0).length,win:rows.length?changes.filter(x=>x>0).length/rows.length*100:0,avg:mean(changes)*100,median:median(changes)*100,pnl:pnls.reduce((a,b)=>a+b,0),pf:gl>0?gp/gl:(gp>0?99:0),avgHold:mean(rows.map(x=>days(x.start_date,x.end_date))),best:changes.length?Math.max(...changes)*100:0,worst:changes.length?Math.min(...changes)*100:0};
  }
  function groupBy(rows,key){const m=new Map();rows.forEach(r=>{const k=key(r);if(!m.has(k))m.set(k,[]);m.get(k).push(r)});return [...m.entries()]}
  function yearAccount(curve,initial){
    if(!curve?.length)return [];
    const sorted=[...curve].sort((a,b)=>String(a.date).localeCompare(String(b.date))),by=new Map();let prior=Number(initial)||0;
    for(const p of sorted){const y=String(p.date).slice(0,4);if(!by.has(y))by.set(y,{year:y,start:prior,points:[]});by.get(y).points.push(Number(p.value)||0)}
    const out=[];
    for(const y of [...by.keys()].sort()){const x=by.get(y),vals=x.points,end=vals.at(-1)||x.start;let peak=x.start,mdd=0;for(const v of vals){peak=Math.max(peak,v);if(peak>0)mdd=Math.min(mdd,v/peak-1)}out.push({year:y,start:x.start,end,ret:x.start>0?(end/x.start-1)*100:0,mdd:mdd*100});prior=end;const next=[...by.keys()].sort().find(z=>z>y);if(next)by.get(next).start=prior}
    return out;
  }
  function strategyRows(a){return groupBy(a,r=>r.strategy_name||r.strategy_id||'미분류').map(([name,rows])=>({name,...pnlStats(rows)})).sort((x,y)=>y.pnl-x.pnl)}
  function reasonRows(a){return groupBy(a,r=>r.reason||'기타').map(([name,rows])=>({name,...pnlStats(rows)})).sort((x,y)=>y.trades-x.trades)}
  function symbolRows(a){return groupBy(a,r=>r.symbol||'—').map(([name,rows])=>({name,...pnlStats(rows)})).sort((x,y)=>y.pnl-x.pnl)}
  function ablation(rows,initial,options,accepted){const base=window.SwingSequenceReplay?.__deepTabsBase;if(!base)return [];const strategies=[...new Set(accepted.map(x=>x.strategy_id).filter(Boolean))];if(strategies.length<2)return [];const full=window.__lastSwingReplay?.result;return strategies.map(id=>{const name=accepted.find(x=>x.strategy_id===id)?.strategy_name||id,r=base(rows.filter(x=>x.strategy_id!==id),initial,options);return{id,name,ending:r.ending,ret:r.change*100,mdd:r.maxDrawdown*100,delta:(r.change-(full?.change||0))*100,trades:r.accepted.length}}).sort((a,b)=>a.delta-b.delta)}
  function metric(label,value,sub='',cls=''){return `<div class="bt-deep-metric ${cls}"><small>${esc(label)}</small><b>${value}</b>${sub?`<em>${esc(sub)}</em>`:''}</div>`}
  function strategyTable(items,totalPnl){return `<div class="bt-deep-table bt-strategy-table"><div class="bt-deep-th"><span>기법</span><span>체결</span><span>승률</span><span>평균</span><span>PF</span><span>실현기여</span><span>평균보유</span></div>${items.map(x=>`<div class="bt-deep-tr"><b>${esc(x.name)}</b><span>${x.trades}건</span><span>${x.win.toFixed(1)}%</span><span class="${x.avg>=0?'up':'down'}">${fmtPct(x.avg)}</span><span>${x.pf>=99?'∞':x.pf.toFixed(2)}</span><span class="${x.pnl>=0?'up':'down'}">${fmtWon(x.pnl)}<small>${totalPnl?`${(x.pnl/Math.abs(totalPnl)*100).toFixed(0)}%`:''}</small></span><span>${x.avgHold.toFixed(1)}일</span></div>`).join('')}</div>`}
  function yearTable(items){return `<div class="bt-deep-table bt-year-table"><div class="bt-deep-th"><span>연도</span><span>연초자산</span><span>연말자산</span><span>계좌수익률</span><span>연중 MDD</span></div>${items.map(x=>`<div class="bt-deep-tr"><b>${x.year}</b><span>${fmtWon(x.start)}</span><span>${fmtWon(x.end)}</span><span class="${x.ret>=0?'up':'down'}">${fmtPct(x.ret)}</span><span class="down">${fmtPct(x.mdd)}</span></div>`).join('')}</div>`}
  function tradesTable(items){return `<div class="bt-trade-tools"><input id="btTradeFilter" placeholder="종목·기법·청산이유 검색"><span>${items.length}건 전체</span></div><div class="bt-deep-table bt-trades-table" id="btTradesTable"><div class="bt-deep-th"><span>기간</span><span>종목</span><span>기법</span><span>투입금</span><span>결과</span><span>청산</span></div>${[...items].reverse().map(x=>`<div class="bt-deep-tr" data-search="${esc(`${x.symbol} ${x.strategy_name} ${x.reason}`.toLowerCase())}"><span>${esc(x.start_date)}<small>→ ${esc(x.end_date)}</small></span><b>${esc(x.symbol)}</b><span>${esc(x.strategy_name)}</span><span>${fmtWon(x.size)}</span><span class="${Number(x.change)>=0?'up':'down'}">${fmtPct(Number(x.change)*100)}</span><span>${esc(x.reason||'—')}</span></div>`).join('')}</div>`}
  function diagnostics(result,accepted,rows,initial,options){
    const s=pnlStats(accepted),reasons=reasonRows(accepted),symbols=symbolRows(accepted),abl=ablation(rows,initial,options,accepted),longest=accepted.length?Math.max(...accepted.map(x=>days(x.start_date,x.end_date))):0,top5=symbols.slice(0,5).reduce((a,x)=>a+Math.max(0,x.pnl),0),grossPos=symbols.reduce((a,x)=>a+Math.max(0,x.pnl),0);
    return `<div class="bt-diagnostic-grid">${metric('평균 거래',fmtPct(s.avg),'거래 1회 수익률')}${metric('중앙값 거래',fmtPct(s.median),'극단값 영향 제거')}${metric('Profit Factor',s.pf>=99?'∞':s.pf.toFixed(2),'원화 손익 기준')}${metric('최고 / 최악',`${fmtPct(s.best)} / ${fmtPct(s.worst)}`)}${metric('평균 / 최장 보유',`${s.avgHold.toFixed(1)}일 / ${longest}일`,'달력일 기준')}${metric('슬롯 탈락',`${result.rejectCapacity||0}건`,`동시보유 ${result.maxOpen||0}까지`)}${metric('중복종목 탈락',`${result.rejectDuplicate||0}건`,'이미 보유 중인 종목')}${metric('현금부족 탈락',`${result.rejectCash||0}건`,'포지션 크기 < 1원')}</div><section class="bt-deep-section"><div class="bt-deep-title"><h4>청산 이유</h4><small>어디서 수익과 손실이 생겼는지</small></div><div class="bt-reason-grid">${reasons.map(x=>`<div><b>${esc(x.name)}</b><span>${x.trades}건 · 승률 ${x.win.toFixed(1)}%</span><strong class="${x.pnl>=0?'up':'down'}">${fmtWon(x.pnl)}</strong></div>`).join('')}</div></section><section class="bt-deep-section"><div class="bt-deep-title"><h4>전략 제거 실험</h4><small>현재 조합에서 하나씩 빼면 계좌가 어떻게 바뀌는지</small></div>${abl.length?`<div class="bt-deep-table bt-ablation-table"><div class="bt-deep-th"><span>제거 기법</span><span>제거 후 수익률</span><span>현재 대비</span><span>MDD</span><span>체결</span></div>${abl.map(x=>`<div class="bt-deep-tr"><b>${esc(x.name)}</b><span class="${x.ret>=0?'up':'down'}">${fmtPct(x.ret)}</span><span class="${x.delta>=0?'up':'down'}">${fmtPct(x.delta)}p</span><span class="down">${fmtPct(x.mdd)}</span><span>${x.trades}건</span></div>`).join('')}</div>`:'<div class="bt-deep-empty">단일 전략이라 제거 비교가 없습니다.</div>'}</section><section class="bt-deep-section"><div class="bt-deep-title"><h4>종목 집중도</h4><small>특정 몇 종목이 결과를 끌어올렸는지 확인</small></div><p class="bt-concentration">수익 기여 상위 5종목이 전체 양(+)의 종목 손익 중 <b>${grossPos>0?(top5/grossPos*100).toFixed(1):'0.0'}%</b>를 차지합니다.</p><div class="bt-symbol-grid">${symbols.slice(0,12).map(x=>`<div><b>${esc(x.name)}</b><span>${x.trades}건</span><strong class="${x.pnl>=0?'up':'down'}">${fmtWon(x.pnl)}</strong></div>`).join('')}</div></section>`;
  }
  function scrubSummary(root){const temp=document.createElement('div');temp.innerHTML=root.innerHTML;temp.querySelector('.btlab-breaks')?.remove();[...temp.querySelectorAll('.btlab-card')].forEach(c=>{if(c.querySelector('h3')?.textContent.includes('최근 가상 체결'))c.remove()});return temp.innerHTML}
  function enhance(result,rows,initial,options){
    const root=document.querySelector('#backtestlab #btLabResult');if(!root||!result||root.querySelector('.bt-result-tabs'))return;
    const accepted=result.accepted||[],stats=pnlStats(accepted),strategies=strategyRows(accepted),years=yearAccount(result.curve||[],initial),summary=scrubSummary(root),totalPnl=stats.pnl;
    root.innerHTML=`<div class="bt-result-head"><div><div class="eyebrow">DEEP REVIEW · 결과 뜯어보기</div><h3>백테스트 상세분석</h3></div><span>${accepted.length.toLocaleString('ko-KR')}건 체결</span></div><div class="bt-result-tabs" role="tablist"><button class="on" data-bt-tab="summary">요약</button><button data-bt-tab="strategy">전략기여</button><button data-bt-tab="period">연도·구간</button><button data-bt-tab="trades">체결내역</button><button data-bt-tab="diagnostic">진단</button></div><div class="bt-result-pane on" data-bt-pane="summary">${summary}</div><div class="bt-result-pane" data-bt-pane="strategy"><div class="bt-deep-callout"><b>전략별 ‘평균 수익률’이 아니라 실제 계좌에 기여한 원화 손익까지 봅니다.</b><span>승률이 높아도 큰 손절 때문에 손익 기여가 마이너스일 수 있어요.</span></div>${strategyTable(strategies,totalPnl)}</div><div class="bt-result-pane" data-bt-pane="period"><div class="bt-deep-callout"><b>여기는 연도별 ‘거래 평균’이 아니라 실제 계좌 수익률입니다.</b><span>각 연도의 연초·연말 계좌가치와 그 해 안에서의 MDD를 다시 계산합니다.</span></div>${yearTable(years)}</div><div class="bt-result-pane" data-bt-pane="trades">${tradesTable(accepted)}</div><div class="bt-result-pane" data-bt-pane="diagnostic">${diagnostics(result,accepted,rows,initial,options)}</div>`;
    root.querySelectorAll('[data-bt-tab]').forEach(b=>b.onclick=()=>{root.querySelectorAll('[data-bt-tab]').forEach(x=>x.classList.toggle('on',x===b));root.querySelectorAll('[data-bt-pane]').forEach(x=>x.classList.toggle('on',x.dataset.btPane===b.dataset.btTab))});
    const f=root.querySelector('#btTradeFilter');if(f)f.oninput=()=>{const q=f.value.trim().toLowerCase();root.querySelectorAll('#btTradesTable .bt-deep-tr').forEach(x=>x.style.display=!q||x.dataset.search?.includes(q)?'grid':'none')};
  }
  if(!document.getElementById('backtestDeepCss')){const l=document.createElement('link');l.id='backtestDeepCss';l.rel='stylesheet';l.href='/static/backtest_result_tabs.css?v=20260814-1';document.head.appendChild(l)}
  const timer=setInterval(()=>{if(captureRunner())clearInterval(timer)},250);setTimeout(()=>clearInterval(timer),20000);
})();