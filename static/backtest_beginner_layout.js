(()=>{
  'use strict';
  // Visual-only layer. Does not change signals, fills, risk rules, or backtest calculations.
  const PAGE = 'backtestlab';
  const fmt = new Intl.NumberFormat('ko-KR');
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = value => { const n = Number(value); return Number.isFinite(n) ? n : 0; };
  const krw = n => (n < 0 ? '-' : '+') + fmt.format(Math.round(Math.abs(n))) + '원';

  if (typeof window.renderSwingWorkerResult === 'function' && !window.renderSwingWorkerResult.__beginnerWrapped) {
    const original = window.renderSwingWorkerResult;
    const wrapped = function(result, initial) {
      window.__beginnerBacktestResult = {result:result, initial:initial};
      return original.apply(this, arguments);
    };
    wrapped.__beginnerWrapped = true;
    window.renderSwingWorkerResult = wrapped;
  }

  function prepareControls(root) {
    const form = root.querySelector('.btlab-form');
    if (form && !form.closest('.bt-beginner-settings')) {
      const settings = document.createElement('details');
      settings.className = 'bt-beginner-settings';
      settings.innerHTML = '<summary><span>날짜·초기자금·동시보유 직접 설정</span><small>기본값을 그대로 사용해도 됩니다.</small></summary>';
      form.before(settings);
      settings.appendChild(form);
    }
    const quick = root.querySelector('.bt-fast-period');
    if (quick) {
      if (quick.closest('.bt-beginner-settings')) {
        quick.closest('.bt-beginner-settings').before(quick);
      }
      if (!quick.dataset.beginnerReady) {
        quick.dataset.beginnerReady = '1';
        const label = quick.querySelector('b');
        if (label) label.textContent = '① 테스트 기간';
      }
    }
    const strategyHead = root.querySelector('.bt-strategy-head > div > b');
    if (strategyHead && !strategyHead.dataset.beginnerReady) {
      strategyHead.textContent = '② 매매 전략';
      strategyHead.dataset.beginnerReady = '1';
    }
    const button = root.querySelector('#btLabRun span');
    if (button && button.textContent.trim() === '백테스트 실행') button.textContent = '③ 백테스트 시작하기';
  }

  function stats(rows) {
    const groups = new Map();
    const reasons = new Map();
    let wins = 0;
    for (const row of rows) {
      const gain = num(row.size) * num(row.change);
      if (num(row.change) > 0) wins++;
      const name = row.strategy_name || row.strategy_id || '기타 전략';
      const group = groups.get(name) || {name:name, profit:0, count:0, wins:0};
      group.profit += gain;
      group.count++;
      if (num(row.change)>0) group.wins++;
      groups.set(name,group);
      const reason = row.reason || '기타';
      reasons.set(reason, (reasons.get(reason) || 0) + 1);
    }
    return {
      winCount:wins,
      strategies:[...groups.values()].sort((a,b)=>b.profit-a.profit),
      exits:[...reasons.entries()].sort((a,b)=>b[1]-a[1])
    };
  }

  function impactGraph(items) {
    if (!items.length) return '';
    const max = Math.max(1,...items.map(x=>Math.abs(x.profit)));
    return '<section class="bt-beginner-impact"><div class="bt-beginner-section-head"><div><small>STRATEGY CHECK</small><h4>어떤 전략이 돈을 벌거나 잃었을까요?</h4></div><span>전략별 실현 손익 · 원화</span></div>' +
      items.map(x=>{
        const width=Math.max(1,Math.round(Math.abs(x.profit)/max*100));
        return '<div class="bt-beginner-impact-row"><div class="bt-beginner-impact-label"><b>'+esc(x.name)+'</b><span>'+x.count+'건</span></div><div class="bt-beginner-impact-track"><i class="'+(x.profit>=0?'positive':'negative')+'" style="width:'+width+'%"></i></div><strong class="'+(x.profit>=0?'up':'down')+'">'+krw(x.profit)+'</strong></div>';
      }).join('') +
      '<p>전략별 막대는 체결된 거래의 실현 손익 합계입니다. 전체 계좌 수익률과는 계산 기준이 달라요.</p></section>';
  }

  function makeInsights(data) {
    const rows = data && Array.isArray(data.accepted) ? data.accepted : [];
    const s=stats(rows);
    if (!rows.length) return '<div class="bt-beginner-empty">체결된 가상 거래가 없어 원인 분석을 만들지 않았어요.</div>';
    const loser=[...s.strategies].sort((a,b)=>a.profit-b.profit)[0];
    const exit=s.exits[0];
    const winRate=(s.winCount/rows.length*100).toFixed(1);
    const lossText=loser && loser.profit<0 ? esc(loser.name)+'에서 '+fmt.format(Math.round(Math.abs(loser.profit)))+'원 손실' : '전략별 실현 손익을 확인하세요';
    return '<div class="bt-beginner-section-head"><div><small>QUICK ANALYSIS</small><h4>이번 결과에서 먼저 살펴볼 3가지</h4></div><span>백테스트 가상 체결 기준</span></div>' +
      '<div class="bt-beginner-insights">' +
      '<article><small>가장 손실이 큰 전략</small><b>'+lossText+'</b><p>전략별 매매를 살펴보면 개선할 대상을 좁힐 수 있어요.</p></article>' +
      '<article><small>가장 흔한 매도 이유</small><b>'+esc(exit ? exit[0] : '—')+' · '+(exit?exit[1]:0)+'건</b><p>수익 실현보다 손절이나 기간 종료가 많은지 살펴보세요.</p></article>' +
      '<article><small>수익으로 끝난 거래</small><b>'+s.winCount+' / '+rows.length+'건 ('+winRate+'%)</b><p>승률뿐 아니라 이길 때 얼마를 벌고 질 때 얼마를 잃는지도 중요해요.</p></article>' +
      '</div>' + impactGraph(s.strategies);
  }

  function simplifyPrimary(result, rows) {
    const hero=result.querySelector('.bt-overview-copy');
    if (hero) {
      const e=hero.querySelector('.eyebrow');
      if(e)e.textContent='이번 테스트 성적표';
      const p=hero.querySelector('p');
      if(p)p.textContent='먼저 전체 수익률과 계좌가 가장 크게 떨어진 폭을 확인하세요.';
    }
    const area=result.querySelector('.bt-primary-metrics');
    if(!area)return;
    const metrics=[...area.querySelectorAll(':scope > .bt-deep-metric')];
    if(metrics[0]){
      const label=metrics[0].querySelector('small');
      if(label)label.textContent='최대 하락폭';
      const sub=metrics[0].querySelector('em');
      if(sub)sub.textContent='최고 자산에서 가장 크게 떨어진 비율';
    }
    if(metrics[2]){
      const label=metrics[2].querySelector('small');
      if(label)label.textContent='수익 거래 비율';
    }
    if(metrics[3]){
      const label=metrics[3].querySelector('small');
      if(label)label.textContent='손익비 (PF)';
      const sub=metrics[3].querySelector('em');
      if(!sub){const em=document.createElement('em');metrics[3].appendChild(em);}
      metrics[3].querySelector('em').textContent='총이익 ÷ 총손실, 1보다 크면 이익 우세';
    }
    if(metrics[1]){
      const advanced=document.createElement('details');
      advanced.className='bt-beginner-risk-details';
      advanced.innerHTML='<summary>추가 위험지표 · 손절 기준 낙폭 보기</summary>';
      metrics[1].querySelector('small').textContent='손절 기준 가정 낙폭';
      metrics[1].querySelector('em')?.remove();
      area.after(advanced);
      advanced.appendChild(metrics[1]);
    }
    const trade=document.createElement('div');
    trade.className='bt-deep-metric';
    trade.innerHTML='<small>가상 체결 수</small><b>'+fmt.format(rows.length)+'건</b><em>실제 증권사 주문이 아닌 과거 시뮬레이션</em>';
    area.appendChild(trade);
  }

  function prepareTrades(section) {
    const table=section.querySelector('.bt-trades-table');
    if(!table)return;
    const tools=section.querySelector('.bt-trade-tools');
    if(!tools)return;
    const toggle=document.createElement('button');
    toggle.type='button';
    toggle.className='bt-beginner-showall';
    toggle.textContent='전체 거래 펼쳐보기';
    toggle.setAttribute('aria-expanded','false');
    const tableRows=table.querySelectorAll('.bt-deep-tr').length;
    if(tableRows<=10)return;
    tools.appendChild(toggle);
    toggle.onclick=()=>{
      const expanded=table.classList.toggle('bt-beginner-show-all');
      toggle.setAttribute('aria-expanded',String(expanded));
      toggle.textContent=expanded?'최근 10건만 보기':'전체 거래 펼쳐보기';
    };
    const search=section.querySelector('input');
    if(search)search.addEventListener('input',()=>{
      const searching=!!search.value.trim();
      if(searching)table.classList.add('bt-beginner-show-all');
      else if(toggle.getAttribute('aria-expanded')==='false')table.classList.remove('bt-beginner-show-all');
    });
  }

  function simplifyResult(root, explicitResult=null) {
    // Accept either the page container (observer path) or the result node (Worker path).
    const result=root.matches?.('#btLabResult')?root:root.querySelector('#btLabResult');
    if(!result||result.dataset.beginnerLayout==='1')return;
    const layout=result.querySelector('.bt-result-layout');
    if(!layout)return;
    const intro=result.querySelector('.bt-result-head p');
    if(intro)intro.textContent='수익률 → 위험 → 손실 원인 순서로 읽으면 됩니다. 세부 자료는 필요할 때만 펼치세요.';
    result.querySelector('.bt-read-order')?.remove();
    const content=layout.querySelector('.bt-result-content');
    if(!content)return;
    const summary=content.querySelector('[data-worker-pane="summary"],[data-bt-pane="summary"]');
    if(!summary)return;
    result.dataset.beginnerLayout='1';
    result.classList.add('bt-beginner-result');
    const data=explicitResult||(window.__beginnerBacktestResult&&window.__beginnerBacktestResult.result)||
      (window.__lastSwingReplay&&window.__lastSwingReplay.result)||null;
    const rows=data&&Array.isArray(data.accepted)?data.accepted:[];
    simplifyPrimary(summary,rows);
    const warning=document.createElement('div');
    warning.className='bt-beginner-paper-note';
    const firstFill=rows.reduce((x,row)=>!row.start_date?x:!x||row.start_date<x?row.start_date:x,'');
    const lastFill=rows.reduce((x,row)=>!row.end_date?x:!x||row.end_date>x?row.end_date:x,'');
    warning.textContent='※ 과거 데이터를 이용한 가상 체결입니다. 실제 주문이 아니며 미래 수익을 보장하지 않습니다.'+(firstFill&&lastFill?' 실제 체결 발생 구간: '+firstFill+' ~ '+lastFill+'.':'');
    summary.prepend(warning);
    const analysis=document.createElement('section');
    analysis.className='bt-beginner-analysis';
    analysis.innerHTML=makeInsights(data);
    summary.after(analysis);
    const more=document.createElement('div');
    more.className='bt-beginner-more-head';
    more.innerHTML='<h4>더 자세히 알아보고 싶다면</h4><p>필요한 항목만 펼쳐 보세요. 계산 결과와 원본 거래 내역은 그대로 남겨뒀어요.</p>';
    analysis.after(more);
    const titles={
      strategy:['전략별 자세한 성적','거래별 승률·평균 수익과 제거 실험 확인'],
      diagnostic:['손실 원인과 구조 분석','손절 사유와 탈락한 신호 확인'],
      period:['연도별·월별 성과','어느 시기에 전략이 약해졌는지 확인'],
      trades:['가상 매매 기록 '+fmt.format(rows.length)+'건','종목과 손익을 검색하고 최근 10건부터 확인']
    };
    for(const key of ['strategy','diagnostic','period','trades']){
      const section=content.querySelector('[data-worker-pane="'+key+'"],[data-bt-pane="'+key+'"]');
      if(!section)continue;
      const d=document.createElement('details');
      d.className='bt-beginner-accordion';
      d.innerHTML='<summary><span><b>'+titles[key][0]+'</b><small>'+titles[key][1]+'</small></span><i aria-hidden="true">⌄</i></summary>';
      content.appendChild(d);
      d.appendChild(section);
      if(key==='trades')prepareTrades(section);
    }
  }

  // Worker renderer invokes this synchronously after writing its result. The observer
  // remains a fallback for legacy and non-worker backtests.
  window.SwingBacktestBeginner={apply:(root,data)=>simplifyResult(root,data)};

  function upgrade() {
    const root=document.getElementById(PAGE);
    if(!root)return;
    prepareControls(root);
    simplifyResult(root);
  }
  function boot(){
    const root=document.getElementById(PAGE);
    if(!root)return false;
    const observer=new MutationObserver(upgrade);
    observer.observe(root,{childList:true,subtree:true});
    upgrade();
    return true;
  }
  if(!boot()){
    const search=new MutationObserver(()=>{if(boot())search.disconnect()});
    search.observe(document.body,{childList:true,subtree:true});
  }
})();
