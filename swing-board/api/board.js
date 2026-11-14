// 현황판 API: board.json(가상매매 장부) + 실시간 시세 → 종목별 현재가·수익률·오늘 할 일(리밸런싱 안내)
// 한국 시세: 네이버 금융, 미국 시세: Yahoo Finance. 실제 주문은 없음.
const board = require("../board.json");

const UA = { "User-Agent": "Mozilla/5.0 (compatible; swing-board/1.0)" };

async function getJSON(url, ms = 8000) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), ms);
  try {
    const r = await fetch(url, { headers: UA, signal: ctl.signal });
    if (!r.ok) return null;
    return await r.json();
  } catch (e) {
    return null;
  } finally {
    clearTimeout(t);
  }
}

function partsIn(tz, d = new Date()) {
  const f = new Intl.DateTimeFormat("en-CA", {
    timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false, weekday: "short",
  });
  const p = Object.fromEntries(f.formatToParts(d).map((x) => [x.type, x.value]));
  return { date: `${p.year}-${p.month}-${p.day}`, hm: Number(p.hour) * 60 + Number(p.minute), wd: p.weekday };
}

// ---------- 시세 ----------
async function krQuote(code, since) {
  const s = since.replace(/-/g, "");
  const [basic, bars] = await Promise.all([
    getJSON(`https://m.stock.naver.com/api/stock/${code}/basic`),
    getJSON(`https://api.stock.naver.com/chart/domestic/item/${code}/day?startDateTime=${s}0000&endDateTime=299912312359`),
  ]);
  const num = (v) => (v == null ? null : Number(String(v).replace(/,/g, "")));
  const out = { price: null, chgPct: null, bars: [] };
  if (basic) {
    out.price = num(basic.closePrice);
    out.chgPct = num(basic.fluctuationsRatio);
    if (basic.compareToPreviousPrice && basic.compareToPreviousPrice.name === "FALLING" && out.chgPct > 0) out.chgPct = -out.chgPct;
    out.status = basic.marketStatus;
  }
  if (Array.isArray(bars)) {
    out.bars = bars.map((b) => ({
      date: `${b.localDate.slice(0, 4)}-${b.localDate.slice(4, 6)}-${b.localDate.slice(6, 8)}`,
      open: b.openPrice, high: b.highPrice, low: b.lowPrice, close: b.closePrice,
    }));
  }
  if (out.price == null && out.bars.length) out.price = out.bars[out.bars.length - 1].close;
  return out;
}

async function usQuote(sym) {
  const js = await getJSON(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?range=1mo&interval=1d`);
  const out = { price: null, chgPct: null, bars: [] };
  const r = js && js.chart && js.chart.result && js.chart.result[0];
  if (!r) return out;
  const m = r.meta || {};
  out.price = m.regularMarketPrice ?? null;
  const prev = m.chartPreviousClose ?? m.previousClose;
  const q = (r.indicators && r.indicators.quote && r.indicators.quote[0]) || {};
  (r.timestamp || []).forEach((ts, i) => {
    if (q.close[i] == null) return;
    out.bars.push({
      date: partsIn("America/New_York", new Date(ts * 1000)).date,
      open: q.open[i], high: q.high[i], low: q.low[i], close: q.close[i],
    });
  });
  // 마지막 봉의 종가가 비어 있으면(야후가 자주 그럼) 메타 정보로 채움
  if (m.regularMarketTime && out.price != null) {
    const d = partsIn("America/New_York", new Date(m.regularMarketTime * 1000)).date;
    if (!out.bars.some((b) => b.date === d)) {
      out.bars.push({ date: d, open: out.price, high: m.regularMarketDayHigh ?? out.price, low: m.regularMarketDayLow ?? out.price, close: out.price });
    }
  }
  if (out.bars.length >= 2 && out.price != null) {
    const p0 = out.bars[out.bars.length - 2].close;
    out.chgPct = ((out.price / p0) - 1) * 100;
  } else if (prev && out.price) out.chgPct = ((out.price / prev) - 1) * 100;
  return out;
}

// ---------- 판단 ----------
const BAND = 0.01; // ±1% 이내면 '보합'

function exitLabel(ret) {
  if (ret >= BAND) return { act: "익절 매도", tone: "win" };
  if (ret <= -BAND) return { act: "손절 매도", tone: "loss" };
  return { act: "보합 정리", tone: "flat" };
}

// lot: {date, entry, stop?}, q: 시세, hold: 보유 거래일 수, open: 오늘 장이 아직 안 끝났는지, today: 시장 날짜
function judge(lot, q, hold, cost, today, sessionOpen, stopPct) {
  const after = q.bars.filter((b) => b.date > lot.date);
  const price = q.price;
  const res = { price, chgPct: q.chgPct, ret: price ? price / lot.entry - 1 - cost : null, day: after.length, hold };
  const stop = lot.stop || (stopPct ? Math.round(lot.entry * (1 - stopPct)) : null);
  res.stop = stop;
  for (let k = 0; k < after.length; k++) {
    const b = after[k];
    const isToday = b.date === today;
    const live = isToday && sessionOpen;
    if (stop && b.open <= stop) {
      return { ...res, done: !live, exitDate: b.date, exitPrice: b.open, ret: b.open / lot.entry - 1 - cost, act: "손절(갭하락)", tone: "loss", day: k + 1 };
    }
    if (stop && b.low <= stop) {
      return { ...res, done: !live, exitDate: b.date, exitPrice: stop, ret: stop / lot.entry - 1 - cost, act: "손절 -" + Math.round(stopPct * 100) + "%", tone: "loss", day: k + 1 };
    }
    if (k + 1 >= hold) {
      const px = live ? price : b.close;
      const ret = px / lot.entry - 1 - cost;
      const lab = exitLabel(ret);
      return { ...res, done: !live, exitDate: b.date, exitPrice: px, ret, act: live ? "오늘 종가 " + lab.act : lab.act, tone: lab.tone, day: k + 1, sellToday: live };
    }
  }
  // 아직 보유
  const left = hold - after.length;
  let act, tone;
  if (after.length === 0) { act = "신규 편입"; tone = "new"; }
  else if (left === 1 && !sessionOpen) { act = "다음 거래일 종가 매도"; tone = "warn"; }
  else { act = `보유 (${after.length}/${hold}일)`; tone = res.ret >= BAND ? "hold-up" : res.ret <= -BAND ? "hold-down" : "hold"; }
  return { ...res, done: false, act, tone, left };
}

async function buildKR() {
  const kr = board.kr;
  const now = partsIn("Asia/Seoul");
  const today = now.date;
  const sessionOpen = !["Sat", "Sun"].includes(now.wd) && now.hm >= 9 * 60 && now.hm < 15 * 60 + 30;
  const codes = [...new Set(kr.lots.map((l) => l.code))];
  const since = kr.lots.reduce((m, l) => (l.date < m ? l.date : m), today);
  const qs = Object.fromEntries(await Promise.all(codes.map(async (c) => [c, await krQuote(c, since)])));
  const rows = kr.lots.map((l) => ({ ...l, ...judge(l, qs[l.code], kr.hold, kr.cost, today, sessionOpen, kr.stop_pct) }));
  return { ...kr, today, sessionOpen, rows };
}

async function buildUS() {
  const us = board.us;
  const now = partsIn("America/New_York");
  const today = now.date;
  const sessionOpen = !["Sat", "Sun"].includes(now.wd) && now.hm >= 9 * 60 + 30 && now.hm < 16 * 60;
  const syms = [...new Set(us.lots.map((l) => l.code))];
  const qs = Object.fromEntries(await Promise.all(syms.map(async (s) => [s, await usQuote(s)])));
  const rows = us.lots.map((l) => ({ ...l, ...judge(l, qs[l.code], l.hold || us.hold, us.cost, today, sessionOpen, null) }));
  // 같은 종목 여러 묶음(매일 새로 5종목) → 종목 단위 리딩
  const latest = us.asof;
  const picksToday = new Set(us.lots.filter((l) => l.date === latest).map((l) => l.code));
  const byCode = {};
  for (const r of rows) {
    (byCode[r.code] = byCode[r.code] || { code: r.code, name: r.name, lots: [], price: r.price, chgPct: r.chgPct }).lots.push(r);
  }
  const tickers = Object.values(byCode).map((t) => {
    const open = t.lots.filter((x) => !x.done);
    const selling = open.filter((x) => x.sellToday || x.act.startsWith("다음"));
    const keep = open.filter((x) => !x.sellToday);
    const avgRet = open.length ? open.reduce((s, x) => s + (x.ret || 0), 0) / open.length : null;
    let act, tone;
    if (!open.length) { act = "정리 완료"; tone = "done"; }
    else if (picksToday.has(t.code) && open.every((x) => x.act === "신규 편입")) { act = "신규 편입"; tone = "new"; }
    else if (picksToday.has(t.code)) { act = "계속 보유 (오늘도 상위 5)"; tone = "hold"; }
    else if (keep.length === 0 || selling.length === open.length) { const lab = exitLabel(avgRet || 0); act = lab.act + " (상위 5에서 빠짐)"; tone = lab.tone; }
    else { act = "보유 후 만료분부터 매도"; tone = "warn"; }
    return { ...t, openLots: open.length, avgRet, act, tone, inToday: picksToday.has(t.code) };
  });
  return { ...us, today, sessionOpen, rows, tickers };
}

module.exports = async (req, res) => {
  const [kr, us] = await Promise.all([buildKR(), buildUS()]);
  res.setHeader("Cache-Control", "s-maxage=60, stale-while-revalidate=300");
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify({ updated_at: board.updated_at, now: new Date().toISOString(), kr, us, evolve: board.evolve }));
};
