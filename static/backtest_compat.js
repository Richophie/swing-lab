(()=>{
  function num(v, fallback=0){const n=Number(v);return Number.isFinite(n)?n:fallback}
  function fmt(v,digits=2){const n=Number(v);return Number.isFinite(n)?n.toFixed(digits):'—'}
  function normalize(x){
    if(!x)return null;
    return {
      return_pct:num(x.return_pct??x.total_return_pct),
      win_rate:num(x.win_rate??x.win_rate_pct),
      trades:num(x.trades),
      avg_trade:num(x.avg_trade??x.avg_trade_pct),
      profit_factor:x.profit_factor,
      max_drawdown:num(x.max_drawdown??x.max_drawdown_pct),
      buy_hold_pct:x.buy_hold_pct,
      sharpe:x.sharpe,
      cost_drag:x.estimated_cost_drag_per_trade_pct,
    };
  }
  function block(title, raw){
    const x=normalize(raw);
    if(!x)return `<div class="bt"><h4>${title}</h4><div class="status">이 구간은 검증 데이터가 충분하지 않습니다.</div></div>`;
    return `<div class="bt"><h4>${title}</h4><div class="metrics"><span>전략 누적수익<b>${fmt(x.return_pct)}%</b></span><span>승률<b>${fmt(x.win_rate,1)}%</b></span><span>거래 수<b>${x.trades}</b></span><span>평균 거래<b>${fmt(x.avg_trade)}%</b></span><span>Profit Factor<b>${x.profit_factor==null?'—':fmt(x.profit_factor)}</b></span><span>최대 낙폭<b>${fmt(x.max_drawdown)}%</b></span></div>${Number.isFinite(Number(x.buy_hold_pct))?`<div class="ticker" style="margin-top:8px">같은 기간 단순 보유 ${fmt(x.buy_hold_pct)}%${Number.isFinite(Number(x.cost_drag))?` · 추정 거래비용 영향/건 ${fmt(x.cost_drag,3)}%p`:''}</div>`:''}</div>`;
  }
  window.backtestHTML=function(b={}){
    const full=b.full_10y??b.full??b.full10y;
    const recent=b.recent_2y??b.recent2y??b.recent;
    return `${block('10년 전체',full)}${block('최근 2년',recent)}${b.engine?`<div class="ticker" style="margin-top:10px">${b.engine}</div>`:''}`;
  };
})();
