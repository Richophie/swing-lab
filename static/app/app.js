(() => {
'use strict';

// ---------- small helpers ----------
const view = document.getElementById('view');
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const has = v => v !== null && v !== undefined && Number.isFinite(Number(v));
const pct = (v, digits = 1) => has(v) ? `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(digits)}%` : '—';
const share = v => has(v) ? `${Math.round(Number(v))}%` : '—';
const tone = v => !has(v) || Number(v) === 0 ? '' : Number(v) > 0 ? 'up' : 'down';
const usd = v => has(v) ? `$${Number(v).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}` : '—';
const won = v => has(v) ? `${Math.round(Number(v)).toLocaleString('ko-KR')}원` : '—';
const signedWon = v => has(v) ? `${Number(v) >= 0 ? '+' : '−'}${Math.abs(Math.round(Number(v))).toLocaleString('ko-KR')}원` : '—';
const dateLabel = iso => { const d = new Date(`${String(iso).slice(0, 10)}T12:00:00`); return Number.isNaN(d.getTime()) ? String(iso || '') : `${d.getMonth() + 1}월 ${d.getDate()}일`; };
const timeLabel = iso => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('ko-KR', {month: 'long', day: 'numeric', hour: 'numeric', minute: '2-digit'}); };

// Exchange listings carry legal suffixes that only add noise on a card.
const cleanName = (name, symbol) => String(name || symbol || '')
  .replace(/\s+-\s+(Class [A-Z].*|Common Stock.*|Ordinary Shares.*|American Depositary.*)$/i, '')
  .replace(/\s+(Common Stock|Ordinary Shares|American Depositary Shares?)$/i, '')
  .replace(/,?\s+(Inc\.?|Incorporated|Corporation|Corp\.?|Company|Co\.?|Ltd\.?|Limited|PLC|p\.l\.c\.|N\.V\.|S\.A\.|Holdings?)$/i, '')
  .trim() || String(symbol || '');

let fx = null;
const krwOf = dollars => has(dollars) && fx ? won(Number(dollars) * fx) : null;
const price = dollars => { const k = krwOf(dollars); return k ? `${k} <small>${usd(dollars)}</small>` : usd(dollars); };

function toast(message) {
  const el = document.getElementById('toast');
  el.textContent = message; el.classList.add('show');
  clearTimeout(toast.timer); toast.timer = setTimeout(() => el.classList.remove('show'), 3200);
}

async function api(path, options = {}) {
  const res = await fetch(path, {cache: 'no-store', ...options});
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON error page */ }
  if (!res.ok || (data && data.error)) throw new Error((data && data.error) || `요청을 처리하지 못했습니다 (${res.status})`);
  return data;
}
// Served through the API so the newest file committed by the daily jobs is shown without a redeploy.
const staticJson = name => fetch(`/api/research/${name}?ts=${Date.now()}`, {cache: 'no-store'}).then(r => r.ok ? r.json() : null).catch(() => null);

// ---------- plain-language dictionaries ----------
const STRATEGY = {
  confirmed_pullback: {name: '눌림 후 반등', why: '오르던 종목이 120일 평균선 근처까지 내려왔다가, 거래량과 함께 다시 오르기 시작한 자리입니다.'},
  momentum_pullback: {name: '상승 중 쉬어가기', why: '최근 한 달 강하게 오른 종목이 며칠 조정을 받은 뒤 다시 힘을 내는 자리입니다.'},
  rsi2_trend_reversion: {name: '단기 급락 반등', why: '상승 추세 안에서 며칠 급하게 빠진 자리입니다. 실전 성적이 좋지 않아 추천에서 제외했습니다.'},
  volatility_breakout: {name: '좁은 구간 돌파', why: '한동안 좁게 움직이다 위로 뚫고 나온 자리입니다. 아직 검증 중입니다.'},
};
const strategyName = id => (STRATEGY[id] || {}).name || '매매 후보';
const MARKET = {
  '좋음': {cls: 'is-good', title: '시장 분위기 좋음', text: '평소대로 추천을 냅니다.'},
  '중립': {cls: 'is-mid', title: '시장 분위기 보통', text: '추천은 나오지만 평소보다 신중하게 보세요.'},
  '조심': {cls: 'is-bad', title: '시장 분위기 나쁨 · 쉬는 날', text: '미국 시장 전체가 약해서 새 추천을 내지 않습니다.'},
};
const OUTCOME = {
  SUCCESS: {label: '목표가 도달', cls: 'is-up'}, STOP: {label: '손절', cls: 'is-down'},
  EXPIRED_GAIN: {label: '기간 종료 · 이익', cls: 'is-up'}, EXPIRED_LOSS: {label: '기간 종료 · 손실', cls: 'is-down'},
  EXPIRED_FLAT: {label: '기간 종료 · 본전', cls: 'is-plain'}, OPEN: {label: '진행 중', cls: 'is-ok'},
};
const ENTRY_STATUS = {'진입 적정': 'is-ok', '현재 매수 신호 없음': 'is-plain'};

// ---------- drawing ----------
function sparkline(values) {
  const v = (values || []).map(Number).filter(Number.isFinite);
  if (v.length < 2) return '';
  const min = Math.min(...v), max = Math.max(...v), span = max - min || 1;
  const pts = v.map((y, i) => `${(i / (v.length - 1) * 100).toFixed(2)},${(40 - (y - min) / span * 36 - 2).toFixed(2)}`).join(' ');
  const color = v[v.length - 1] >= v[0] ? 'var(--up)' : 'var(--down)';
  return `<svg class="spark" viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg>`;
}

function priceChart(series, plan) {
  const rows = (series || []).filter(r => has(r.close));
  if (rows.length < 5) return '<p class="muted pad">차트 데이터를 불러오지 못했습니다.</p>';
  const W = 900, H = 340, L = 8, R = 78, T = 12, B = 26;
  const levels = [plan?.entry_low, plan?.entry_high, plan?.target, plan?.stop].filter(has).map(Number);
  const values = rows.flatMap(r => [r.close, r.bb_high, r.bb_low, r.sma120].filter(has).map(Number)).concat(levels);
  const min = Math.min(...values), max = Math.max(...values), pad = (max - min) * 0.05 || 1;
  const x = i => L + i / (rows.length - 1) * (W - L - R);
  const y = v => T + (max + pad - v) / (max - min + pad * 2) * (H - T - B);
  const line = key => rows.map((r, i) => has(r[key]) ? `${x(i).toFixed(1)},${y(r[key]).toFixed(1)}` : null).filter(Boolean).join(' ');
  const band = rows.map((r, i) => has(r.bb_high) ? `${x(i).toFixed(1)},${y(r.bb_high).toFixed(1)}` : null).filter(Boolean)
    .concat(rows.map((r, i) => has(r.bb_low) ? `${x(i).toFixed(1)},${y(r.bb_low).toFixed(1)}` : null).filter(Boolean).reverse()).join(' ');
  const guide = (value, color, label) => has(value) ? `<line x1="${L}" x2="${W - R}" y1="${y(value)}" y2="${y(value)}" stroke="${color}" stroke-width="1.3" stroke-dasharray="5 4"/><text x="${W - R + 6}" y="${y(value) + 4}" fill="${color}" font-size="12" font-weight="700">${label}</text>` : '';
  const zone = has(plan?.entry_low) && has(plan?.entry_high)
    ? `<rect x="${L}" width="${W - L - R}" y="${y(plan.entry_high)}" height="${Math.max(2, y(plan.entry_low) - y(plan.entry_high))}" fill="var(--ok)" opacity=".16"/><text x="${W - R + 6}" y="${(y(plan.entry_high) + y(plan.entry_low)) / 2 + 4}" fill="var(--ok)" font-size="12" font-weight="700">사는 가격</text>` : '';
  const ticks = [0, Math.floor(rows.length / 2), rows.length - 1].map(i => `<text x="${x(i)}" y="${H - 6}" fill="var(--faint)" font-size="11" text-anchor="${i === 0 ? 'start' : i === rows.length - 1 ? 'end' : 'middle'}">${esc(String(rows[i].date).slice(0, 10))}</text>`).join('');
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="최근 주가와 매매 가격선">
    <polygon points="${band}" fill="var(--faint)" opacity=".10"/>
    ${zone}
    <polyline points="${line('sma120')}" fill="none" stroke="var(--warn)" stroke-width="1.4" opacity=".8"/>
    <polyline points="${line('close')}" fill="none" stroke="var(--text)" stroke-width="1.8" stroke-linejoin="round"/>
    ${guide(plan?.target, 'var(--up)', '목표가')}${guide(plan?.stop, 'var(--down)', '손절가')}
    ${ticks}
  </svg>
  <div class="legend"><span><i style="background:var(--text)"></i>주가</span><span><i style="background:var(--warn)"></i>120일 평균</span><span><i style="background:var(--faint);opacity:.4;height:8px"></i>평소 움직이는 범위</span></div>`;
}

// ---------- shared pieces ----------
function planLevels(plan) {
  if (!plan || !has(plan.entry_low)) return '';
  const hold = has(plan.days_min) && has(plan.days_max) ? `${plan.days_min}~${plan.days_max}거래일` : '며칠';
  return `<div class="levels">
    <div class="level"><span>사는 가격</span><b>${usd(plan.entry_low)} ~ ${usd(plan.entry_high)}</b></div>
    <div class="level"><span>목표가</span><b class="up">${usd(plan.target)} <small>${pct(plan.target_pct)}</small></b></div>
    <div class="level"><span>손절가</span><b class="down">${usd(plan.stop)} <small>${has(plan.stop_pct) ? pct(-Math.abs(plan.stop_pct)) : '—'}</small></b></div>
    <div class="level"><span>예상 보유</span><b>${hold}</b></div>
  </div>`;
}
function eventTag(risk) {
  if (!risk || !risk.risk_code || risk.risk_code === 'CLEAR' || risk.risk_code === 'UNKNOWN') return '';
  return `<span class="tag is-warn" title="실적 발표 전후에는 주가가 크게 움직일 수 있습니다">실적 발표 ${has(risk.days_until) ? `${risk.days_until}일 전` : '임박'}</span>`;
}
function pickCard(row) {
  const plan = row.trade_plan || {};
  const status = plan.entry_status ? `<span class="tag ${ENTRY_STATUS[plan.entry_status] || 'is-plain'}">${esc(plan.entry_status)}</span>` : '';
  return `<article class="card pick" data-go="#/stock/${esc(row.symbol)}?s=${esc(row.strategy_id)}">
    <div class="pick-top"><div><div class="pick-name">${esc(cleanName(row.name_ko, row.symbol))}</div><div class="pick-ticker">${esc(row.symbol)}</div></div><span class="tag">${esc(strategyName(row.strategy_id))}</span></div>
    <p class="pick-why">${esc((STRATEGY[row.strategy_id] || {}).why || row.strategy_reason || '')}</p>
    ${sparkline(row.sparkline)}
    ${planLevels(plan)}
    <div class="pick-foot">${status}${eventTag(row.event_risk)}</div>
  </article>`;
}
function historyRow(item) {
  const o = OUTCOME[item.status_code] || {label: item.status || '', cls: 'is-plain'};
  const ret = item.status_code === 'OPEN' ? item.current_return_pct : item.outcome_return_pct;
  return `<div class="row" data-go="#/stock/${esc(item.symbol)}?s=${esc(item.strategy_id)}">
    <div class="row-name"><b>${esc(cleanName(item.name_ko, item.symbol))}</b><small>${esc(item.symbol)} · ${esc(strategyName(item.strategy_id))}</small></div>
    <div class="row-mid"><span class="tag ${o.cls}">${esc(o.label)}</span></div>
    <div class="row-end ${tone(ret)}">${pct(ret)}</div>
  </div>`;
}

// ---------- views ----------
// New York Stock Exchange full-day closures. Update once a year.
const US_HOLIDAYS = new Set(['2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03', '2026-05-25', '2026-06-19', '2026-07-03', '2026-09-07', '2026-11-26', '2026-12-25',
  '2027-01-01', '2027-01-18', '2027-02-15', '2027-03-26', '2027-05-31', '2027-06-18', '2027-07-05', '2027-09-06', '2027-11-25', '2027-12-24']);
const isoOf = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
function tradingDate(iso, n) {
  const d = new Date(`${String(iso).slice(0, 10)}T12:00:00`);
  for (let left = n; left > 0;) { d.setDate(d.getDate() + 1); if (d.getDay() !== 0 && d.getDay() !== 6 && !US_HOLIDAYS.has(isoOf(d))) left -= 1; }
  return d;
}
function addTradingDays(iso, n) { const d = tradingDate(iso, n); return `${d.getMonth() + 1}월 ${d.getDate()}일`; }
// Korean clock time of a New York clock time on that day (handles US daylight saving).
function koreaTime(day, hour, minute) {
  for (const offset of [4, 5]) {
    const utc = new Date(Date.UTC(day.getFullYear(), day.getMonth(), day.getDate(), hour + offset, minute));
    const there = Number(new Intl.DateTimeFormat('en-US', {timeZone: 'America/New_York', hour: 'numeric', hour12: false}).format(utc)) % 24;
    if (there === hour) return new Intl.DateTimeFormat('ko-KR', {timeZone: 'Asia/Seoul', month: 'long', day: 'numeric', weekday: 'short', hour: 'numeric', minute: '2-digit'}).format(utc);
  }
  return '';
}
// The evolution engine's condition names, in words a trader would use.
const pctAbs = v => Math.abs(v * 100).toFixed(0);
const CONDITION_WORDS = {
  drawdown_252d: v => `1년 고점에서 ${pctAbs(v)}% 넘게 내려온`,
  drawdown_60d: v => `최근 석 달 고점에서 ${pctAbs(v)}% 넘게 내려온`,
  dist_sma120: v => `120일 평균보다 ${pctAbs(v)}% 넘게 아래에 있는`,
  up_days_5: v => `최근 5일 중 오른 날이 ${v.toFixed(0)}일 이하인`,
  atr_pct: v => `하루 평균 ${(v * 100).toFixed(1)}% 이상 움직이는`,
  volume_5d_vs_20d: v => `최근 5일 거래량이 평소의 ${(v * 100).toFixed(0)}% 이하로 줄어든`,
  rel_volume: v => `당일 거래량이 평소의 ${(v * 100).toFixed(0)}% 이하인`,
  lower_wick_atr: v => `당일 아래꼬리가 하루 평균 움직임의 ${(v * 100).toFixed(0)}% 이상으로 길게 달린`,
  donchian_pos20: v => `최근 20일 고저 범위의 아래쪽 ${(v * 100).toFixed(0)}% 안에 있는`,
  ret10: v => `최근 10일 동안 ${(v * 100).toFixed(1)}% 넘게 오르지 않은`,
};
const CANDIDATE_TITLES = {
  evolved_champion_v1: '매도세가 마른 급락주 반등',
  evolved_champion_v2: '아래꼬리를 단 급락주 반등',
  deep_drawdown_washout_v1: '크게 빠진 뒤 연속 눌린 종목 반등',
};
const ruleWords = c => c.rule.conditions.map(x => (CONDITION_WORDS[x.feature] || (() => `${x.label} ${x.op} ${x.threshold}`))(Number(x.threshold))).join(', ');
const candidateTitle = c => CANDIDATE_TITLES[c.name] || (c.passed_automatic_gate ? '자동 탐색 통과 규칙' : '검증 중인 규칙');
// The limit-entry variant is watched next to the frozen plan, never instead of it.
const limitLine = mine => {
  const decided = mine.filter(x => x.limit_filled === true || x.limit_filled === false);
  const filled = decided.filter(x => x.limit_filled);
  if (!decided.length) return '';
  const avg = filled.length ? filled.reduce((sum, x) => sum + Number(x.limit_return_pct), 0) / filled.length : null;
  return `<br>지정가로 샀다면: ${decided.length}건 중 ${filled.length}건 체결${filled.length ? ` · 평균 ${pct(avg, 2)}` : ''}`;
};
const stopWords = c => c.rule.stop_atr
  ? `산 가격에서 하루 평균 움직임(ATR)의 ${c.rule.stop_atr}배만큼 내려가면 그날 손절합니다. 갭으로 떨어지면 손절가보다 더 낮게 팔릴 수 있습니다.`
  : '손절가 없이 날짜로만 파는 규칙이라 보유 중 크게 빠질 수 있습니다.';
// Candidates that passed every automatic gate come first.
const candidatesOf = evo => [...((evo || {}).family_candidates || [])].sort((a, b) => Number(!!b.passed_automatic_gate) - Number(!!a.passed_automatic_gate));

// One live signal as a plain to-do: when and at what price to buy, when to sell, and where it usually ended.
function signalCard(x, c, track) {
  const hold = c.rule.hold_days;
  const bought = has(x.entry_price);
  const buyDay = x.entry_date ? new Date(`${x.entry_date}T12:00:00`) : tradingDate(x.signal_date, 1);
  const sellDay = x.exit_date ? new Date(`${x.exit_date}T12:00:00`) : tradingDate(x.signal_date, hold);
  const base = bought ? Number(x.entry_price) : Number(x.signal_close);
  const krw = v => { const k = krwOf(v); return k ? ` · 약 ${k}` : ''; };
  const look = ((track.outlook || {})[c.name]) || {};
  const at = r => base * (1 + Number(r) / 100);
  const now = bought && has(x.last_close) ? (Number(x.last_close) / Number(x.entry_price) - 1) * 100 : null;
  const tag = !bought ? '<span class="tag is-ok">새 신호 · 아직 사기 전</span>' : `<span class="tag is-plain">보유 ${x.days_held}일째 / ${hold}일</span>`;
  const buy = bought
    ? `<div class="card plan-box"><span>산 가격</span><b>${usd(x.entry_price)}</b><small>${dateLabel(x.entry_date)} 장 시작 가격${krw(x.entry_price)}${has(now) ? `<br>최근 종가 ${usd(x.last_close)} · <span class="${tone(now)}">${pct(now)}</span>` : ''}</small></div>`
    : `<div class="card plan-box"><span>사는 가격</span><b>약 ${usd(x.signal_close)}</b><small>${koreaTime(buyDay, 9, 30)} 미국 장이 열릴 때 시장가로 삽니다. 실제 가격은 그때 정해지며, 전날 종가가 ${usd(x.signal_close)}였습니다${krw(x.signal_close)}.${has(x.limit_price) ? `<br>더 싸게 사고 싶다면 지정가 <b style="display:inline;font-size:inherit;margin:0">${usd(x.limit_price)}</b>를 그날만 걸어 두세요. 닿지 않으면 건너뜁니다.` : ''}</small></div>`;
  const range = has(look.p25_return_pct)
    ? `과거 같은 매매 ${look.trades}건 중 절반이 ${usd(at(look.p25_return_pct))} ~ ${usd(at(look.p75_return_pct))} (${pct(look.p25_return_pct)} ~ ${pct(look.p75_return_pct)}) 사이에서 끝났습니다.` : '';
  const sell = `<div class="card plan-box is-target"><span>파는 가격</span><b>${has(look.median_return_pct) ? `보통 ${usd(at(look.median_return_pct))} 근처` : '날짜에 맞춰 매도'}</b><small>가격을 정해 두지 않고 ${koreaTime(sellDay, 15, 50)} 미국 장 마감 직전에 시장가로 팝니다. ${range}</small></div>`;
  const stop = x.stop_atr || c.rule.stop_atr
    ? `<div class="card plan-box is-stop"><span>손절가</span><b>${usd(base - Number(x.stop_atr || c.rule.stop_atr) * Number(x.atr))}</b><small>${bought ? '' : '산 가격이 정해지면 다시 계산됩니다. '}이 가격 아래로 내려가면 그날 팝니다.</small></div>`
    : `<div class="card plan-box is-stop"><span>손절가</span><b>없음</b><small>날짜에만 팝니다. ${has(look.big_loss_share_pct) ? `과거 ${Math.round(100 / Math.max(1, look.big_loss_share_pct))}번에 1번은 10% 넘게 잃었으니 한 종목에 몰지 마세요. 계좌의 8분의 1까지만 넣으세요.` : ''}</small></div>`;
  // Results due while the position is held: these trades swung harder in both directions.
  const reports = x.earnings_date && x.earnings_date >= isoOf(buyDay) && x.earnings_date <= isoOf(sellDay);
  const earnings = reports ? `<p class="signal-note"><span class="tag is-warn">보유 중 실적 발표</span> ${dateLabel(x.earnings_date)}쯤 실적 발표가 예정돼 있습니다. 과거에 이런 신호는 10% 넘게 잃는 일이 두 배쯤 잦았고, 평균 수익도 더 컸습니다. 크게 흔들리는 것이 싫다면 이 종목은 건너뛰세요.</p>` : '';
  return `<div class="signal" data-go="#/stock/${esc(x.symbol)}"><div class="signal-head"><b>${esc(x.symbol)}</b>${tag}<small>${dateLabel(x.signal_date)} 신호</small></div>${earnings}<div class="plan">${buy}${sell}${stop}</div></div>`;
}

function experimentSection(track, evo, pit) {
  // The home screen only lists rules that passed every test; the rest stay in the report.
  const candidates = candidatesOf(evo).filter(c => c.passed_automatic_gate);
  if (!candidates.length || !track) return '';
  const limit = track.limit_entry;
  const limitNote = limit ? `<div class="card pad prose" style="margin-top:12px"><p><b>지정가로 사는 방법(관찰 중)</b></p><p>다음 날 시가에 바로 사는 대신, 신호일 종가보다 하루 평균 움직임(ATR)의 ${limit.discount_atr}배 낮은 가격에 그날 하루만 지정가를 걸어 두는 방법입니다. 과거에는 한 건당 평균이 더 높았지만 신호 10건 중 4건 정도만 체결됐고, 확정 기준은 통과하지 못했습니다. 닿지 않으면 그 종목은 건너뜁니다. 파는 날은 같습니다.</p></div>` : '';
  const blocks = candidates.map(c => {
    const hold = c.rule.hold_days;
    const mine = (track.signals || []).filter(x => x.candidate === c.name);
    const open = mine.filter(x => x.status === 'OPEN').sort((a, b) => b.signal_date.localeCompare(a.signal_date));
    const closed = mine.filter(x => x.status === 'CLOSED');
    const avg = closed.length ? closed.reduce((sum, x) => sum + Number(x.return_pct), 0) / closed.length : null;
    const all = (((pit || {}).candidates || {})[c.name] || {})['전체'] || {};
    const left = all.left_index || {}, members = all.all_members || {};
    const row = x => signalCard(x, c, track);
    const badge = c.passed_automatic_gate ? '<span class="tag is-ok">과거 검증 통과</span>' : '<span class="tag is-warn">검증 미통과</span>';
    return `<div class="card pad prose" style="margin-top:12px"><p><b>${candidateTitle(c)}</b> ${badge}</p>
      <p>${ruleWords(c)} S&P 500 종목을 다음 날 시가에 사서 <b>${hold}거래일 뒤 종가</b>에 팝니다. ${stopWords(c)}</p>
      ${members.trades ? `<p>과거 성적: 한 건당 평균 ${pct(members.avg_return_pct, 2)} (${members.trades}건, 이익 비율 ${share(members.win_rate_pct)}). 나중에 지수에서 빠진 회사만 보면 ${pct(left.avg_return_pct, 2)}였습니다.${c.passed_automatic_gate ? '' : ' 살아남은 회사 덕을 본 규칙일 가능성이 큽니다.'}</p>` : ''}
      <p class="muted" style="font-size:13.5px">실제 기록(${c.frozen_at}부터): 신호 ${mine.length}건 · 종료 ${closed.length}건${closed.length ? ` · 평균 ${pct(avg, 2)}` : ''}${limitLine(mine)}</p></div>
      ${open.length ? open.slice(0, 10).map(row).join('') : `<p class="muted" style="margin:8px 4px 0;font-size:13.5px">${dateLabel(track.panel_last_date)} 기준 해당 종목 없음</p>`}`;
  }).join('');
  const sizing = `<div class="card pad prose" style="margin-top:12px"><p><b>돈을 8칸으로 나눠 한 종목에 한 칸만 쓰세요</b></p><p>이 규칙들은 20번에 1번꼴로 10% 넘게 잃고, 그런 매매만 미리 골라내는 방법은 찾지 못했습니다. 과거 기록에서 손실 폭을 줄인 방법은 여러 종목에 똑같이 나눠 사는 것 하나였습니다. 5칸과 8칸은 한 해 수익이 약 17%로 같았지만, 가장 크게 빠졌을 때가 5칸은 -27%, 8칸은 -22%였습니다(3칸은 -33%). 신호가 없어 남는 칸은 비워 두세요. 약한 신호로 채우면 오히려 손실이 커졌습니다.</p></div>`;
  return `<section class="section"><div class="section-head"><h2>검증을 통과한 규칙의 신호 <span class="tag is-warn">실전 확인 중</span></h2><a class="link" href="#/report">근거 보기</a></div>
    <p class="muted">컴퓨터가 과거 데이터에서 찾아 세 가지 시험을 통과한 규칙입니다. 과거에 통했다는 뜻이지 앞으로의 수익을 보장하지 않으며, 2025년 이후에는 성적이 약해졌습니다. 실제 돈을 넣는다면 잃어도 되는 소액으로만 하세요. 신호는 미국 장 마감 뒤 하루 한 번 갱신됩니다. 시간은 한국 시간입니다.</p>${blocks}${sizing}${limitNote}</section>`;
}

async function todayView() {
  const [latest, history, diag, track, evo, pit] = await Promise.all([api('/api/latest'), api('/api/history?size=4').catch(() => null), staticJson('forward_diagnostics.json'), staticJson('evolution_candidate_shadow.json'), staticJson('strategy_evolution.json'), staticJson('evolution_pit_lite.json')]);
  fx = latest.usdkrw || fx;
  const market = latest.market || {};
  const m = MARKET[market.state] || {cls: '', title: '시장 확인 중', text: market.brief || ''};
  const rows = (latest.results || []).filter(r => r.aggregate_eligible);
  const top = rows.slice(0, 3), rest = rows.slice(3);
  const o = (diag || {}).overall || {};
  const losing = o.closed >= 30 && Number(o.avg_return_pct) < 0;

  let picks;
  if (top.length) {
    picks = `<div class="picks">${top.map(pickCard).join('')}</div>${rest.length ? `<details class="card more"><summary>조건을 통과한 종목 ${rest.length}개 더 보기</summary><div class="inner"><div class="picks">${rest.map(pickCard).join('')}</div></div></details>` : ''}`;
    // While the live record of these rules is losing, their picks are folded away behind a warning.
    if (losing) picks = `<details class="card more"><summary>기존 규칙이 고른 종목 ${rows.length}개 보기</summary><div class="inner">${picks}</div></details>`;
  } else {
    const reason = market.state === '조심'
      ? '미국 시장 전체가 약할 때는 새로 사지 않는 것이 규칙입니다. 시장이 회복되면 다시 추천이 나옵니다.'
      : '오늘은 조건을 모두 통과한 종목이 없습니다. 억지로 고르지 않습니다.';
    picks = `<div class="card empty"><h3>오늘은 추천이 없습니다</h3><p>${reason}</p></div>`;
  }

  const days = ((history || {}).days || []).filter(d => (d.items || []).length);
  const recent = days.length ? `<div class="card rows">${days.map(d => `<div class="day-label">${dateLabel(d.date)} 추천</div>${d.items.slice(0, 6).map(historyRow).join('')}${d.items.length > 6 ? `<div class="row" data-go="#/report"><div class="row-name muted">외 ${d.items.length - 6}건</div><div class="row-mid"></div><div class="row-end muted">성적표에서 보기</div></div>` : ''}`).join('')}</div>` : '<div class="card empty"><p>아직 기록이 없습니다.</p></div>';

  view.innerHTML = `
    <div class="page-head"><h1>오늘의 추천</h1><p>${losing ? '과거 검증을 통과한 규칙의 신호를 먼저 보여드립니다. 예전부터 쓰던 추천 규칙은 실제 성적이 나빠 아래로 내렸습니다.' : `미국 주식 약 ${has(latest.candidate_count) ? Number(latest.candidate_count).toLocaleString('ko-KR') : '500'}개 중 조건을 통과한 종목만, 하루 최대 3개를 먼저 보여드립니다.`}</p></div>
    <div class="card market ${m.cls}"><span class="market-dot"></span><div><b>${esc(m.title)}</b><span>${esc(m.text)}</span></div></div>
    ${losing ? experimentSection(track, evo, pit) : ''}
    <section class="section"><div class="section-head"><h2>${losing ? '기존 추천 규칙 <span class="tag is-warn">최근 성적 부진</span>' : '지금 살 만한 종목'}</h2><span class="muted">${latest.scanned_at ? `${timeLabel(latest.scanned_at)} 기준` : ''}</span></div>
    ${losing ? `<p class="muted">이 규칙들이 실제로 추천한 ${o.closed}건은 한 건당 평균 ${pct(o.avg_return_pct, 2)}로 손실이었습니다. 참고용으로만 남겨 둡니다.</p>` : ''}${picks}</section>
    ${losing ? '' : experimentSection(track, evo, pit)}
    ${o.closed ? `<section class="section"><div class="card notice"><div><b>기존 추천의 실제 성적</b><span>추천 ${o.closed}건 · 한 건당 평균 <span class="${tone(o.avg_return_pct)}">${pct(o.avg_return_pct, 2)}</span> · 이익으로 끝난 비율 ${share(o.win_rate_pct)}</span></div><a class="btn" href="#/report">성적표 보기</a></div></section>` : ''}
    <section class="section"><div class="section-head"><h2>${losing ? '기존 추천은 어떻게 됐나' : '최근 추천은 어떻게 됐나'}</h2><a class="link" href="#/report">전체 성적</a></div>${recent}</section>`;
}

function searchView() {
  view.innerHTML = `
    <div class="page-head"><h1>종목 찾기</h1><p>궁금한 미국 주식의 티커를 넣으면, 지금 사도 되는 자리인지 같은 기준으로 확인해 드립니다.</p></div>
    <form class="search-box" id="searchForm"><input class="input" id="ticker" placeholder="예: AAPL" autocomplete="off" autocapitalize="characters" aria-label="미국 주식 티커"><button class="btn primary" type="submit">확인</button></form>
    <div class="chips">${['AAPL', 'NVDA', 'MSFT', 'TSLA', 'GOOGL', 'AMZN'].map(t => `<button class="chip" type="button" data-go="#/stock/${t}">${t}</button>`).join('')}</div>`;
  const input = document.getElementById('ticker');
  document.getElementById('searchForm').addEventListener('submit', e => {
    e.preventDefault();
    const t = input.value.trim().toUpperCase().replace(/[^A-Z0-9.\-]/g, '');
    if (t) location.hash = `#/stock/${t}`; else input.focus();
  });
  input.focus();
}

async function stockView(symbol, strategy) {
  const query = strategy ? `?strategy=${encodeURIComponent(strategy)}` : '';
  const d = await api(`/api/detail/${encodeURIComponent(symbol)}${query}`);
  fx = d.usdkrw || fx;
  const plan = d.trade_plan || {}, sid = d.strategy_id, sig = d.signal || {};
  const active = !!(plan.signal_active ?? sig.active) && has(plan.entry_low);
  const current = plan.current_price;
  const verdict = active
    ? `<div class="verdict"><b>${esc(strategyName(sid))} 자리입니다</b>${esc((STRATEGY[sid] || {}).why || d.strategy_reason || '')}</div>`
    : `<div class="verdict is-off"><b>지금은 사는 자리가 아닙니다</b>우리 기준의 매수 조건을 충족하지 않습니다. 가격·손절 계획 없이 사는 것은 권하지 않습니다.</div>`;
  const facts = [
    ['최근 한 달 수익률', '20거래일 동안 오른 폭', pct(sig.ret20_pct)],
    ['최근 일주일 수익률', '5거래일 동안 오른 폭', pct(sig.ret5_pct)],
    ['120일 평균과의 거리', '0%에 가까울수록 평균 근처', pct(sig.d120)],
    ['과열·침체 지표 (RSI)', '30 아래면 많이 빠진 상태, 70 위면 과열', has(sig.rsi) ? Number(sig.rsi).toFixed(0) : '—'],
    ['하루 평균 움직임', '보통 하루에 오르내리는 폭', has(sig.atr_pct) ? `${Number(sig.atr_pct).toFixed(1)}%` : '—'],
    ['거래량', '최근 20일 평균 대비', has((d.flow || {}).relative_volume) ? `${Number(d.flow.relative_volume).toFixed(2)}배` : '—'],
  ].filter(([, , v]) => v !== '—').map(([k, hint, v]) => `<div class="fact"><span>${k}<small>${hint}</small></span><b>${v}</b></div>`).join('');

  view.innerHTML = `
    <button class="back" type="button" id="back">‹ 뒤로</button>
    <div class="stock-head"><div><h1>${esc(cleanName(d.name_ko, symbol))}</h1><div class="muted">${esc(symbol)}${active ? ` · <span class="tag">${esc(strategyName(sid))}</span>` : ''}</div></div>
      <div class="stock-price">${has(current) ? usd(current) : ''}<small>${krwOf(current) || ''}</small></div></div>
    ${verdict}
    ${active ? `<div class="plan">
      <div class="card plan-box"><span>사는 가격</span><b>${usd(plan.entry_low)} ~ ${usd(plan.entry_high)}</b><small>${esc(plan.entry_status || '')}${has(plan.current_vs_entry_pct) ? ` · 현재가는 구간 대비 ${pct(plan.current_vs_entry_pct)}` : ''}</small></div>
      <div class="card plan-box is-target"><span>목표가 · 여기서 팝니다</span><b>${usd(plan.target)} (${pct(plan.target_pct)})</b><small>${has(plan.days_max) ? `닿지 않아도 ${plan.days_max}거래일이 지나면 정리합니다` : ''}</small></div>
      <div class="card plan-box is-stop"><span>손절가 · 여기서 포기합니다</span><b>${usd(plan.stop)} (${has(plan.stop_pct) ? pct(-Math.abs(plan.stop_pct)) : '—'})</b><small>이 가격 아래로 내려가면 손실을 확정합니다</small></div>
    </div>` : ''}
    <div class="card chart-card" id="chart"><p class="muted pad">차트 불러오는 중…</p></div>
    ${active ? `<section class="section"><div class="section-head"><h2>내 돈으로 계산해 보기</h2></div><div class="card pad calc">
      <div class="field"><label for="capital">투자 가능한 금액 (원)</label><input class="input" id="capital" inputmode="numeric" value="3,000,000"></div>
      <div class="calc-out" id="calcOut"></div></div>
      <div class="actions"><button class="btn primary" id="paperBuy" type="button">가상계좌로 사 보기</button><a class="btn" href="#/paper">가상계좌 보기</a></div></section>` : ''}
    <section class="section"><div class="section-head"><h2>지금 상태</h2></div><div class="card pad facts">${facts}</div></section>
    <details class="card more" id="btBox"><summary>과거에 같은 방법으로 이 종목을 샀다면</summary><div class="inner" id="btOut"><p class="muted">불러오는 중…</p></div></details>`;

  document.getElementById('back').onclick = () => history.length > 1 ? history.back() : (location.hash = '#/');
  api(`/api/chart/${encodeURIComponent(symbol)}?strategy=${encodeURIComponent(sid)}`)
    .then(c => { document.getElementById('chart').innerHTML = priceChart(c.series, active ? plan : null); })
    .catch(() => { document.getElementById('chart').innerHTML = '<p class="muted pad">차트를 불러오지 못했습니다.</p>'; });

  if (active) {
    const capital = document.getElementById('capital'), out = document.getElementById('calcOut');
    const entry = (Number(plan.entry_low) + Number(plan.entry_high)) / 2;
    const calc = () => {
      const digits = capital.value.replace(/[^\d]/g, '');
      capital.value = digits ? Number(digits).toLocaleString('ko-KR') : '';
      const money = Number(digits);
      if (!money || !fx) { out.innerHTML = '<p class="muted">금액을 입력하면 몇 주를 살지 계산합니다.</p>'; return; }
      // Same sizing rule as the paper account: risk 1% of the account, at most 40% in one stock.
      const perShare = entry * fx, riskPerShare = (entry - Number(plan.stop)) * fx;
      const qty = Math.max(0, Math.floor(Math.min(money * 0.01 / riskPerShare, money * 0.40 / perShare)));
      if (qty < 1) { out.innerHTML = `<p class="muted">이 종목은 1주만 사도 손절 시 손실이 약 ${won(riskPerShare)}으로, 계좌의 1%(${won(money * 0.01)})를 넘습니다. 금액을 늘리거나 더 싼 종목을 고르세요.</p>`; return; }
      out.innerHTML = `
        <div class="level"><span>살 수량</span><b>${qty}주 · 약 ${won(qty * perShare)}</b></div>
        <div class="level"><span>목표가에 팔면</span><b class="up">${signedWon(qty * (Number(plan.target) - entry) * fx)}</b></div>
        <div class="level"><span>손절가에 팔면</span><b class="down">${signedWon(-qty * riskPerShare)}</b></div>
        <p class="muted" style="font-size:13px">한 번의 손실이 계좌의 1%를 넘지 않도록 수량을 정했습니다. 수수료 제외, 환율 ${Number(fx).toLocaleString('ko-KR')}원 기준.</p>`;
    };
    capital.addEventListener('input', calc); calc();
    document.getElementById('paperBuy').onclick = async e => {
      e.target.disabled = true;
      try { await paperApi('/api/paper/submit', {method: 'POST', body: {symbol, strategy: sid}}); toast('가상 주문을 넣었습니다. 다음 거래일 시가에 체결됩니다.'); }
      catch (err) { toast(err.message); }
      e.target.disabled = false;
    };
  }

  document.getElementById('btBox').addEventListener('toggle', async e => {
    if (!e.target.open || e.target.dataset.loaded) return;
    e.target.dataset.loaded = '1';
    const box = document.getElementById('btOut');
    try {
      const b = await api(`/api/backtest/${encodeURIComponent(symbol)}?strategy=${encodeURIComponent(sid)}`);
      const full = b.full_10y || b.full || b, n = full.trades;
      if (!has(n) || Number(n) === 0) { box.innerHTML = '<p class="muted">지난 10년 동안 이 종목에서는 같은 조건이 나온 적이 없습니다.</p>'; return; }
      box.innerHTML = `<div class="kpis">
        <div class="card kpi"><span>거래 횟수</span><b>${n}번</b><small>지난 10년</small></div>
        <div class="card kpi"><span>이익으로 끝난 비율</span><b>${share(full.win_rate)}</b><small>&nbsp;</small></div>
        <div class="card kpi"><span>한 번당 평균</span><b class="${tone(full.avg_trade)}">${pct(full.avg_trade, 2)}</b><small>수수료 포함</small></div>
        <div class="card kpi"><span>가장 크게 빠진 폭</span><b class="down">${pct(full.max_drawdown)}</b><small>&nbsp;</small></div></div>
        <p class="muted" style="margin-top:12px;font-size:13.5px">한 종목의 과거 결과는 횟수가 적어 참고만 하세요. 추천 여부를 정하는 데는 쓰지 않습니다.</p>`;
    } catch (err) { box.innerHTML = `<p class="muted">${esc(err.message)}</p>`; }
  });
}

// ---------- paper account ----------
const CLIENT_KEY = 'swingLabPaperClientV1', BACKUP_KEY = 'swingLabPaperStateBackupV1';
function clientId() {
  let id = null;
  try { id = localStorage.getItem(CLIENT_KEY); } catch { /* storage blocked */ }
  if (!id) {
    id = (crypto?.randomUUID?.() || `paper-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    try { localStorage.setItem(CLIENT_KEY, id); } catch { /* storage blocked */ }
  }
  return id;
}
const readBackup = () => { try { const x = JSON.parse(localStorage.getItem(BACKUP_KEY) || 'null'); return x && Array.isArray(x.orders) ? x : null; } catch { return null; } };
const saveBackup = state => { try { if (state && Array.isArray(state.orders)) localStorage.setItem(BACKUP_KEY, JSON.stringify(state)); } catch { /* storage blocked */ } };
const hasActivity = s => !!s && Array.isArray(s.orders) && (s.orders.length > 0 || (s.events || []).length > 0);
async function paperApi(path, {method = 'GET', body} = {}) {
  const headers = {'X-Paper-Client': clientId(), ...(body ? {'Content-Type': 'application/json'} : {})};
  let data = await api(path, {method, headers, body: body ? JSON.stringify(body) : undefined});
  // The free server forgets accounts on restart; put back this browser's copy when that happens.
  if (path === '/api/paper' && method === 'GET' && !hasActivity(data) && hasActivity(readBackup())) {
    try { data = await api('/api/paper/restore', {method: 'POST', headers: {...headers, 'Content-Type': 'application/json'}, body: JSON.stringify({state: readBackup()})}); } catch { /* keep the empty account */ }
  }
  if (data && Array.isArray(data.orders)) saveBackup(data);
  return data;
}
function orderRow(o) {
  const name = `<div class="row-name"><b>${esc(cleanName(o.name_ko, o.symbol))}</b><small>${esc(o.symbol)} · ${o.qty}주</small></div>`;
  if (o.status === 'PENDING') return `<div class="row" data-go="#/stock/${esc(o.symbol)}?s=${esc(o.strategy_id)}">${name}<div class="row-mid">다음 거래일 시가에 매수 예정</div><div class="row-end"><button class="btn small" data-close="${esc(o.id)}" type="button">취소</button></div></div>`;
  if (o.status === 'FILLED') {
    const ret = has(o.last_close_usd) && has(o.entry_fill_usd) ? (o.last_close_usd / o.entry_fill_usd - 1) * 100 : null;
    return `<div class="row" data-go="#/stock/${esc(o.symbol)}?s=${esc(o.strategy_id)}">${name}<div class="row-mid">산 가격 ${usd(o.entry_fill_usd)} · 목표 ${usd(o.target)} · 손절 ${usd(o.stop)}</div><div class="row-end"><span class="${tone(ret)}">${pct(ret, 2)}</span> <button class="btn small" data-close="${esc(o.id)}" type="button">지금 팔기</button></div></div>`;
  }
  if (o.status === 'CLOSED') return `<div class="row" data-go="#/stock/${esc(o.symbol)}?s=${esc(o.strategy_id)}">${name}<div class="row-mid">${esc(o.exit_reason || '정리')} · ${dateLabel(o.exit_date)}</div><div class="row-end ${tone(o.pnl_krw)}">${signedWon(o.pnl_krw)}<br><small>${pct(o.return_pct, 2)}</small></div></div>`;
  return `<div class="row">${name}<div class="row-mid">${o.status === 'CANCELLED' ? '취소됨' : '체결되지 않음'}</div><div class="row-end muted">—</div></div>`;
}
function renderPaper(p) {
  const s = p.summary || {}, orders = p.orders || [];
  const total = Number(s.equity_krw) - Number(s.starting_cash_krw);
  const group = (title, list, empty) => `<section class="section"><div class="section-head"><h2>${title}</h2></div>${list.length ? `<div class="card rows">${list.map(orderRow).join('')}</div>` : `<div class="card empty"><p>${empty}</p></div>`}</section>`;
  const holding = orders.filter(o => o.status === 'FILLED'), waiting = orders.filter(o => o.status === 'PENDING');
  const done = orders.filter(o => !['FILLED', 'PENDING'].includes(o.status)).reverse();
  view.innerHTML = `
    <div class="page-head"><h1>가상계좌</h1><p>진짜 돈 없이 추천대로 사고팔아 보는 연습 계좌입니다. 실제 주문은 나가지 않습니다.</p></div>
    <div class="kpis">
      <div class="card kpi"><span>총 자산</span><b>${won(s.equity_krw)}</b><small class="${tone(total)}">시작 대비 ${signedWon(total)}</small></div>
      <div class="card kpi"><span>쓸 수 있는 현금</span><b>${won(s.available_cash_krw)}</b><small>시작 금액 ${won(s.starting_cash_krw)}</small></div>
      <div class="card kpi"><span>보유 중 손익</span><b class="${tone(s.unrealized_pnl_krw)}">${signedWon(s.unrealized_pnl_krw)}</b><small>아직 팔지 않은 종목</small></div>
      <div class="card kpi"><span>확정 손익</span><b class="${tone(s.realized_pnl_krw)}">${signedWon(s.realized_pnl_krw)}</b><small>끝난 거래 ${s.closed_trades || 0}건</small></div>
    </div>
    <div class="actions"><button class="btn" id="paperRefresh" type="button">최신 가격 반영</button><button class="btn danger" id="paperReset" type="button">계좌 초기화</button></div>
    ${group('보유 중', holding, '보유 중인 종목이 없습니다. 추천 종목 화면에서 “가상계좌로 사 보기”를 눌러 보세요.')}
    ${waiting.length ? group('매수 대기', waiting, '') : ''}
    ${done.length ? group('끝난 거래', done, '') : ''}`;
  const run = async (button, path, body, message) => {
    button.disabled = true;
    try { renderPaper(await paperApi(path, {method: 'POST', body})); toast(message); }
    catch (err) { toast(err.message); button.disabled = false; }
  };
  document.getElementById('paperRefresh').onclick = e => run(e.target, '/api/paper/refresh', null, '최신 가격을 반영했습니다.');
  document.getElementById('paperReset').onclick = e => { if (confirm('가상계좌의 모든 기록을 지우고 처음 금액으로 되돌릴까요?')) run(e.target, '/api/paper/reset', null, '계좌를 초기화했습니다.'); };
  view.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', e => { e.stopPropagation(); run(b, '/api/paper/close', {order_id: b.dataset.close}, '처리했습니다.'); }));
}
async function paperView() {
  if (!fx) api('/api/latest').then(l => { fx = l.usdkrw || fx; }).catch(() => {});
  renderPaper(await paperApi('/api/paper'));
}

// ---------- report ----------
function statRow(name, m) {
  return `<tr><td>${esc(name)}</td><td>${m.closed ?? m.trades ?? 0}</td><td class="${tone(m.avg_return_pct)}">${pct(m.avg_return_pct, 2)}</td><td>${share(m.win_rate_pct)}</td><td>${share(m.target_hit_pct)}</td><td>${share(m.stop_pct)}</td></tr>`;
}
const statTable = rows => `<div class="card table-wrap"><table class="data"><thead><tr><th></th><th>추천 수</th><th>한 건당 평균</th><th>이익 비율</th><th>목표가 도달</th><th>손절</th></tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
function evolutionSection(evo, track, pit) {
  if (!evo) return '';
  const prev = evo.previous_ledger || {}, scored = Number(evo.candidates_scored_total || 0) + Number(prev.candidates_scored_total || 0);
  const cov = (pit || {}).coverage || {};
  const seg = (c, name, key) => { const m = (c.stats || {})[key] || {}; return `<tr><td>${name}</td><td>${m.trades ?? 0}</td><td class="${tone(m.avg_return_pct)}">${pct(m.avg_return_pct, 2)}</td><td>${share(m.win_rate_pct)}</td></tr>`; };
  const blocks = candidatesOf(evo).map(c => {
    const all = (((pit || {}).candidates || {})[c.name] || {})['전체'] || {};
    return `<div class="card pad prose" style="margin-top:12px"><p><b>${candidateTitle(c)}</b> — ${c.passed_automatic_gate ? '세 가지 시험을 모두 통과했습니다.' : '자동 기준은 통과하지 못했고 참고용으로만 지켜봅니다.'}</p>
      <p>${ruleWords(c)} 종목을 다음 날 시가에 사서 ${c.rule.hold_days}거래일 뒤 종가에 파는 규칙입니다.</p>
      ${all.all_members ? `<p>살아남은 회사 효과 확인: 신호일에 지수에 있던 회사 전체 ${pct(all.all_members.avg_return_pct, 2)}, 지금도 지수에 있는 회사 ${pct(all.still_in_index.avg_return_pct, 2)}, 나중에 빠진 회사 ${pct(all.left_index.avg_return_pct, 2)}.</p>` : ''}</div>
      <div class="card table-wrap" style="margin-top:8px"><table class="data"><thead><tr><th>과거 성적${c.passed_automatic_gate ? '' : ' (예전 종목 기준)'}</th><th>거래 수</th><th>한 건당 평균</th><th>이익 비율</th></tr></thead><tbody>
      ${seg(c, '탐색 구간 ① 2017~2019', 'train_1')}${seg(c, '탐색 구간 ② 2019~2021', 'train_2')}${seg(c, '탐색 구간 ③ 2021~2022', 'train_3')}
      ${seg(c, '시험 ① 2023~2024', 'validation')}${seg(c, '시험 ② 탐색에 안 쓴 종목', 'symbol_test')}${seg(c, '시험 ③ 2025년 이후', 'lockbox')}</tbody></table></div>`;
  }).join('');
  return `<section class="section"><div class="section-head"><h2>새 규칙을 찾는 자동 탐색</h2></div><div class="card pad prose">
    <p>컴퓨터가 지난 10년 데이터에서 “어떤 조건일 때 사서 며칠 들고 있으면 이익인가”를 스스로 조합해 보고, 살아남은 규칙을 탐색에 쓰지 않은 기간과 종목으로 다시 시험합니다. 평일마다 자동으로 반복합니다.</p>
    <p><b>지금까지 ${scored.toLocaleString('ko-KR')}개 규칙을 시험했고, 세 가지 시험을 모두 통과한 것은 ${(evo.champions || []).length}개입니다.</b> 오래 돌릴수록 우연히 맞는 규칙이 나오기 때문에, 시도 횟수가 늘면 통과 기준도 올라갑니다.</p>
    <p>대상은 “신호가 난 날 S&P 500에 들어 있던 회사”입니다. 지금 큰 회사만 보면 살아남은 회사 덕에 성적이 좋게 나오기 때문입니다. 다만 지수에서 빠진 회사 ${cov.former_members_since_2017 || '—'}곳 중 가격 자료가 무료로 남아 있는 곳은 ${cov.former_members_with_prices || '—'}곳뿐이라, 이 문제를 완전히 없애지는 못했습니다.</p>
    <p>통과한 규칙도 정식 추천에는 넣지 않고, 첫 화면의 “검증을 통과한 규칙의 신호”에서 실제 신호를 날마다 기록해 확인합니다.</p></div>${blocks}</section>`;
}
async function reportView() {
  const [d, exit, regime, entry, shadow, feat, evo, evoShadow, pit] = await Promise.all(['forward_diagnostics.json', 'exit_policy_research.json', 'regime_rank_research.json', 'entry_timing_research.json', 'exit_challenger_shadow.json', 'entry_feature_research.json', 'strategy_evolution.json', 'evolution_candidate_shadow.json', 'evolution_pit_lite.json'].map(staticJson));
  if (!d || !(d.overall || {}).closed) { view.innerHTML = '<div class="page-head"><h1>성적표</h1></div><div class="card empty"><p>아직 결과가 확정된 추천이 없습니다.</p></div>'; return; }
  const o = d.overall, t = d.target_reachability || {}, names = d.strategy_names || {};
  const plainName = id => STRATEGY[id] ? STRATEGY[id].name : (names[id] || id);
  const passed = (exit ? Object.values(exit.strategies || {}) : []).filter(s => s.train_pick_passes_oos).map(s => `${plainName(Object.keys(exit.strategies).find(k => exit.strategies[k] === s))}의 “${s.policies[s.train_pick].label}”`);
  const gatePassed = regime && regime.regime_all_strategies.train_pick_passes_oos;
  const entryPassed = entry ? Object.values(entry.strategies || {}).some(s => s.train_pick_passes_oos) : false;
  const sc = (shadow || {}).challenger || {}, sb = (shadow || {}).baseline || {};
  view.innerHTML = `
    <div class="page-head"><h1>성적표</h1><p>${dateLabel(d.first_market_date)}부터 ${dateLabel(d.last_market_date)}까지, 장 마감 후 확정된 추천이 실제로 어떻게 끝났는지 그대로 보여드립니다. 좋은 결과만 고르지 않습니다.</p></div>
    <div class="kpis">
      <div class="card kpi"><span>한 건당 평균 수익률</span><b class="${tone(o.avg_return_pct)}">${pct(o.avg_return_pct, 2)}</b><small>추천 ${o.closed}건</small></div>
      <div class="card kpi"><span>이익으로 끝난 비율</span><b>${share(o.win_rate_pct)}</b><small>10번 중 약 ${Math.round(Number(o.win_rate_pct) / 10)}번</small></div>
      <div class="card kpi"><span>목표가까지 간 비율</span><b>${share(o.target_hit_pct)}</b><small>나머지는 기간 종료나 손절</small></div>
      <div class="card kpi"><span>손절로 끝난 비율</span><b>${share(o.stop_pct)}</b><small>평균 손실 ${pct(o.avg_loss_pct, 2)}</small></div>
    </div>
    <section class="section"><div class="section-head"><h2>한눈에 보는 결론</h2></div><div class="card pad prose">
      <p><b>지금까지는 손실입니다.</b> 추천대로 모두 따라 샀다면 한 건당 평균 ${pct(o.avg_return_pct, 2)}였습니다. 같은 기간 미국 시장도 조정을 받았고, 모든 방식의 매수 신호가 함께 부진했습니다.</p>
      <p><b>그래서 바꾼 것.</b> 과거 데이터와 실전 모두에서 손실이었던 “단기 급락 반등” 방식은 2026년 11월 11일부터 추천에서 뺐습니다. 지금은 두 가지 방식만 추천합니다.</p>
      <p><b>바꾸지 않은 것.</b> 목표가를 낮추거나, 시장이 나쁠 때 쉬는 기준을 바꾸거나, 사는 타이밍을 조정하는 안을 과거 데이터로 시험했지만 뚜렷하게 나아지지 않아 그대로 두었습니다.</p>
    </div></section>
    <section class="section"><div class="section-head"><h2>방식별 성적</h2></div>${statTable(Object.entries(d.by_strategy || {}).map(([k, m]) => statRow(plainName(k), m)))}</section>
    <section class="section"><div class="section-head"><h2>월별 성적</h2></div>${statTable(Object.entries(d.by_month || {}).map(([k, m]) => statRow(`${Number(k.slice(5))}월`, m)))}</section>
    <section class="section"><div class="section-head"><h2>추천 후 며칠 동안 얼마나 올랐나</h2></div><div class="card pad"><p class="muted" style="margin-bottom:14px">추천 뒤 ${has(t.median_bars_observed) ? Math.round(t.median_bars_observed) : 5}거래일 안에 한 번이라도 이만큼 올랐던 비율입니다. 목표가는 보통 +${has(t.median_target_pct) ? Number(t.median_target_pct).toFixed(1) : '—'}% 지점이었습니다.</p><div class="bars">${(t.mfe_reach_by_level || []).map(x => `<div class="bar"><span>+${x.level_pct}% 이상</span><div><i style="width:${Math.max(0, Math.min(100, Number(x.reached_pct)))}%"></i></div><b>${share(x.reached_pct)}</b></div>`).join('')}</div></div></section>
    <section class="section"><div class="section-head"><h2>개선하려고 시험해 본 것</h2></div><div class="issues">
      <div class="issue"><b>파는 방법 바꾸기 — ${passed.length ? '한 가지 통과' : '통과 없음'}</b><p>목표가 낮추기, 손절 넓히기, 더 오래 들고 가기 등 8가지를 비교했습니다. ${passed.length ? `${passed.join(', ')}만 통과해 실제 주문 없이 따로 추적하고 있습니다${shadow ? ` (현재 규칙 ${sb.trades || 0}건, 새 규칙 ${sc.trades || 0}건 종료 · ${shadow.minimum_closed_trades_required}건이 쌓이면 판단)` : ''}.` : '기준을 통과한 안이 없습니다.'}</p></div>
      <div class="issue"><b>시장이 나쁠 때 쉬는 기준 바꾸기 — ${gatePassed ? '통과' : '통과 없음'}</b><p>더 빨리 반응하는 6가지 기준을 시험했지만, 한 시기에 좋았던 기준이 다른 시기에는 나빴습니다.</p></div>
      <div class="issue"><b>사는 타이밍 바꾸기 — ${entryPassed ? '통과' : '통과 없음'}</b><p>하루 기다리기, 더 싸게 지정가로 사기, 반등을 확인하고 사기 등 7가지를 시험했습니다. 싸게 사려 하면 떨어지는 종목만 잡히고, 확인하고 사면 이익도 함께 줄었습니다.</p></div>
      ${feat ? `<div class="issue"><b>어떤 자리에서 사야 이기는지 찾기 — 후보 두 가지 추적 중</b><p>종목을 약 ${feat.symbol_count}개로 넓혀 지난 10년의 매수 신호 ${Number(feat.signal_count).toLocaleString('ko-KR')}건을 다시 분석했습니다. “상승 중 쉬어가기”는 신호가 나온 날 강하게 오르며 마감한 경우가, “눌림 후 반등”은 계획 손익비가 높은 경우가 조금 나았습니다. 다만 차이가 작고 최근 석 달 실제 추천에서는 확인되지 않아, 추천 규칙은 바꾸지 않고 따로 추적만 합니다.</p></div>` : ''}
    </div></section>
    ${evolutionSection(evo, evoShadow, pit)}
    <p class="muted" style="margin-top:18px;font-size:13px">수익률은 수수료를 빼기 전, 추천한 사는 가격의 중간값 기준입니다. 자세한 연구 화면은 아래 “연구실”에 있습니다.</p>`;
}

// ---------- router ----------
const ROUTES = [
  [/^#?\/?$/, 'today', () => todayView()],
  [/^#\/search$/, 'search', () => searchView()],
  [/^#\/paper$/, 'paper', () => paperView()],
  [/^#\/report$/, 'report', () => reportView()],
  [/^#\/stock\/([A-Za-z0-9.\-]{1,12})(?:\?s=([a-z0-9_]+))?$/, 'today', m => stockView(m[1].toUpperCase(), m[2])],
];
let navigation = 0;
async function route() {
  const hash = location.hash || '#/';
  const found = ROUTES.map(([re, tab, fn]) => [hash.match(re), tab, fn]).find(([m]) => m) || [[''], 'today', () => todayView()];
  const [match, tab, fn] = found, mine = ++navigation;
  document.querySelectorAll('.tabs a').forEach(a => a.classList.toggle('on', a.dataset.tab === tab && !hash.startsWith('#/stock/')));
  view.innerHTML = '<p class="loading">불러오는 중…</p>';
  window.scrollTo(0, 0);
  try { await fn(match); }
  catch (err) { if (mine === navigation) view.innerHTML = `<div class="card empty"><h3>화면을 불러오지 못했습니다</h3><p>${esc(err.message)}</p><div class="actions" style="justify-content:center"><button class="btn" type="button" onclick="location.reload()">다시 시도</button></div></div>`; }
}
view.addEventListener('click', e => {
  if (e.target.closest('button[data-close], a, summary, input, .btn')) return;
  const go = e.target.closest('[data-go]');
  if (go) location.hash = go.dataset.go;
});
window.addEventListener('hashchange', route);
api('/api/version').then(v => { document.getElementById('appVersion').textContent = `버전 ${v.version}`; }).catch(() => {});
route();
})();
