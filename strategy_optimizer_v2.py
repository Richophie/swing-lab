from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from itertools import combinations
import json
import math
from pathlib import Path
from statistics import mean

POOL = Path("static/replay_backtest_pool_v2.json")
OUT = Path("static/strategy_optimizer_results.json")
INITIAL_CAPITAL = 3_000_000.0
EXIT_PCTS = (None, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0)
HOLD_CAPS = (None, 3, 5, 10)
CAPACITIES = (1, 3, 5)
MAX_STRATEGIES_PER_COMBO = 2
RISK_BUDGET = 0.01
MAX_SHARE = 0.40
MIN_TRAIN_TRADES = 18
MIN_OOS_TRADES = 8


def num(v, default=0.0):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def parse_day(v: str) -> date:
    return date.fromisoformat(str(v)[:10])


def execute_candidate(c: dict, pool: dict, forced_profit_pct: float | None, hold_cap: int | None) -> dict | None:
    path = c.get("path") or []
    if not path:
        return None
    costs = pool.get("costs") or {}
    commission = num(costs.get("commission_pct_per_side"), 0.10) / 100.0
    friction = (num(costs.get("slippage_bps"), 5.0) + num(costs.get("half_spread_bps"), 2.5)) / 10000.0
    atr = num(c.get("atr"))
    signal_close = num(c.get("signal_close"))
    entry_mode = c.get("entry_mode") or "next_open"

    if entry_mode == "intraday_trigger":
        trigger = num(c.get("trigger"), float("nan"))
        high = num(path[0][2], float("nan"))
        if not math.isfinite(trigger) or not math.isfinite(high) or high < trigger:
            return None
        raw_entry = trigger
    else:
        raw_entry = num(path[0][1])
        gap = max(0.75 * atr, 0.01 * signal_close)
        buy_low = num(c.get("buy_low"))
        buy_high = num(c.get("buy_high"))
        if raw_entry <= 0 or raw_entry < buy_low - gap or raw_entry > buy_high + gap:
            return None

    entry = raw_entry * (1.0 + friction)
    stop = num(c.get("stop"))
    exit_mode = c.get("exit_mode") or "price_plan"
    hard_stop = 0.0 if exit_mode == "sma20_close" else stop
    original_target = num(c.get("target"), float("nan"))
    target = entry * (1.0 + forced_profit_pct / 100.0) if forced_profit_pct else original_target
    no_target_ok = exit_mode in {"sma20_close", "donchian20_close", "day_close"}
    if (hard_stop > 0 and entry <= hard_stop) or (
        not forced_profit_pct and not no_target_ok and (not math.isfinite(original_target) or original_target <= entry)
    ):
        return None

    max_hold = max(1, int(num(c.get("max_hold"), len(path))))
    if hold_cap is not None:
        max_hold = min(max_hold, int(hold_cap))
    hold = max(1, min(len(path), max_hold))
    last = path[hold - 1]
    raw_exit = num(last[4])
    exit_date = str(last[0])
    reason = "기간종료"

    for i in range(hold):
        bar = path[i]
        d = str(bar[0])
        o, h, l, cl = map(num, bar[1:5])
        s20 = num(bar[5], float("nan")) if len(bar) > 5 else float("nan")
        dc20 = num(bar[7], float("nan")) if len(bar) > 7 else float("nan")
        has_target = math.isfinite(target) and target > entry
        if hard_stop > 0 and o <= hard_stop:
            raw_exit, exit_date, reason = o, d, "손절 · 갭"
            break
        if hard_stop > 0 and l <= hard_stop and has_target and h >= target:
            raw_exit, exit_date, reason = hard_stop, d, "손절 · 동시터치"
            break
        if hard_stop > 0 and l <= hard_stop:
            raw_exit, exit_date = hard_stop, d
            reason = "손절 · 장중순서 보수판정" if entry_mode == "intraday_trigger" and i == 0 else "손절"
            break
        if has_target and (o >= target or h >= target):
            raw_exit, exit_date = target, d
            reason = f"+{forced_profit_pct:.2f}% 강제익절" if forced_profit_pct else "목표가"
            break
        if exit_mode == "day_close":
            raw_exit, exit_date, reason = cl, d, "당일 종가 청산"
            break
        if exit_mode == "sma20_close" and math.isfinite(s20) and cl < s20:
            raw_exit, exit_date, reason = cl, d, "20일선 종가 이탈"
            break
        if exit_mode == "donchian20_close" and math.isfinite(dc20) and cl < dc20:
            raw_exit, exit_date, reason = cl, d, "Donchian 20일 하단 이탈"
            break
        if i == hold - 1:
            raw_exit, exit_date = cl, d
            reason = "보유기간 상한" if hold_cap is not None else ("최대보유 종료" if exit_mode in {"sma20_close", "donchian20_close"} else "기간종료")

    paid = entry * (1.0 + commission)
    received = raw_exit * (1.0 - friction) * (1.0 - commission)
    change = received / paid - 1.0
    risk_fraction = max(0.001, (entry - stop) / entry) if entry > 0 else 0.001
    return {
        "start_date": str(c.get("entry_date")),
        "end_date": exit_date,
        "change": change,
        "risk_fraction": risk_fraction,
        "priority": num(c.get("net_risk_reward"), num(c.get("elite_score")) / 100.0),
        "key": f"{c.get('symbol')}|{c.get('strategy_id')}|{c.get('signal_date')}",
        "symbol": c.get("symbol"),
        "strategy_id": c.get("strategy_id"),
        "strategy_name": c.get("strategy_name") or c.get("strategy_id"),
        "reason": reason,
    }


def _equity(cash: float, open_positions: dict) -> float:
    return cash + sum(p["size"] for p in open_positions.values())


def _size_for(total: float, cash: float, risk: float) -> float:
    budget = total * RISK_BUDGET
    rf = max(num(risk), 0.001)
    by_risk = budget / rf
    cap = total * MAX_SHARE
    return max(0.0, min(cash, by_risk, cap))


def portfolio(rows: list[dict], start: date, end: date, capacity: int) -> dict:
    selected = [r for r in rows if start <= parse_day(r["start_date"]) <= end and parse_day(r["end_date"]) <= end]
    selected.sort(key=lambda r: (r["start_date"], -num(r.get("priority")), str(r.get("key") or "")))
    starts = defaultdict(list)
    ends = defaultdict(list)
    for seq, raw in enumerate(selected):
        row = dict(raw)
        row["_seq"] = seq
        starts[row["start_date"]].append(row)
        ends[row["end_date"]].append(row)
    days = sorted(set(starts) | set(ends))
    cash = INITIAL_CAPITAL
    peak = cash
    max_drawdown = 0.0
    max_open = 0
    open_positions = {}
    open_symbols = set()
    accepted = []
    reject_capacity = 0
    reject_duplicate = 0

    for day in days:
        incoming = sorted(
            starts.get(day, []),
            key=lambda r: (-num(r.get("priority")), str(r.get("key") or ""), r["_seq"]),
        )
        for row in incoming:
            symbol = row.get("symbol")
            if symbol and symbol in open_symbols:
                reject_duplicate += 1
                continue
            if len(open_positions) >= capacity:
                reject_capacity += 1
                continue
            total = _equity(cash, open_positions)
            size = _size_for(total, cash, row.get("risk_fraction"))
            if size < 1:
                continue
            open_positions[row["_seq"]] = {"row": row, "size": size}
            if symbol:
                open_symbols.add(symbol)
            cash -= size
            accepted.append(row)
            max_open = max(max_open, len(open_positions))

        for row in sorted(ends.get(day, []), key=lambda r: r["_seq"]):
            pos = open_positions.get(row["_seq"])
            if not pos:
                continue
            cash += pos["size"] * (1.0 + num(row.get("change")))
            symbol = pos["row"].get("symbol")
            if symbol:
                open_symbols.discard(symbol)
            del open_positions[row["_seq"]]

        total = _equity(cash, open_positions)
        peak = max(peak, total)
        if peak > 0:
            max_drawdown = min(max_drawdown, total / peak - 1.0)

    if open_positions:
        for pos in open_positions.values():
            cash += pos["size"] * (1.0 + num(pos["row"].get("change")))
    changes = [num(r.get("change")) for r in accepted]
    wins = sum(1 for x in changes if x > 0)
    years = max((end - start).days / 365.25, 0.25)
    cagr = (cash / INITIAL_CAPITAL) ** (1.0 / years) - 1.0 if cash > 0 else -1.0
    return {
        "ending": cash,
        "return": cash / INITIAL_CAPITAL - 1.0,
        "cagr": cagr,
        "mdd": max_drawdown,
        "trades": len(accepted),
        "win_rate": wins / len(changes) if changes else 0.0,
        "avg_trade": mean(changes) if changes else 0.0,
        "trades_per_year": len(accepted) / years,
        "max_open": max_open,
        "reject_capacity": reject_capacity,
        "reject_duplicate": reject_duplicate,
    }


def _cap(v: float, low: float, high: float) -> float:
    return max(low, min(high, v))


def train_score(train: dict) -> float:
    """Rank configurations using training data only."""
    if train["trades"] < MIN_TRAIN_TRADES or train["cagr"] <= 0:
        return -999.0
    cagr = _cap(train["cagr"], 0.0, 0.60)
    drawdown = abs(_cap(train["mdd"], -0.35, 0.0))
    win = _cap(train["win_rate"], 0.35, 0.65)
    avg_trade = _cap(train["avg_trade"], -0.02, 0.03)
    activity = _cap(train["trades_per_year"], 0.0, 50.0)
    score = (
        50.0
        + 25.0 * (cagr / 0.60)
        - 20.0 * (drawdown / 0.35)
        + 8.0 * ((win - 0.50) / 0.15)
        + 5.0 * (avg_trade / 0.03)
        + 3.0 * (activity / 50.0)
    )
    return round(score, 2)


def validation_pass(oos: dict, recent: dict) -> bool:
    return bool(
        oos["trades"] >= MIN_OOS_TRADES
        and recent["trades"] >= 5
        and oos["cagr"] > 0
        and recent["cagr"] >= 0
        and oos["mdd"] >= -0.20
        and recent["mdd"] >= -0.20
    )


def grade(train: dict, oos: dict, recent: dict) -> str:
    if not validation_pass(oos, recent):
        return "C"
    if (
        oos["cagr"] >= 0.08
        and recent["cagr"] >= 0.05
        and oos["mdd"] >= -0.12
        and recent["mdd"] >= -0.12
        and oos["trades"] >= 15
    ):
        return "A"
    return "B"


def _round_metrics(m: dict) -> dict:
    return {
        "return_pct": round(m["return"] * 100, 2),
        "cagr_pct": round(m["cagr"] * 100, 2),
        "mdd_pct": round(m["mdd"] * 100, 2),
        "trades": int(m["trades"]),
        "win_rate_pct": round(m["win_rate"] * 100, 2),
        "avg_trade_pct": round(m["avg_trade"] * 100, 3),
        "trades_per_year": round(m["trades_per_year"], 1),
        "max_open": int(m["max_open"]),
    }


def _category_value(item: dict, category: str) -> float:
    train = item["train_raw"]
    if category == "balanced":
        return item["score"]
    if category == "return":
        return train["cagr"] - 0.25 * abs(train["mdd"])
    if category == "defensive":
        return train["cagr"] - 1.50 * abs(train["mdd"])
    if category == "turnover":
        return train["trades_per_year"] * max(0.0, train["avg_trade"])
    raise ValueError(category)


def main() -> None:
    if not POOL.exists():
        raise SystemExit(f"missing {POOL}")
    pool = json.loads(POOL.read_text(encoding="utf-8"))
    if not pool.get("ready") or int(pool.get("version") or 0) < 2:
        raise SystemExit("replay V2/V3 pool is not ready")
    candidates = pool.get("trades") or []
    strategy_names = pool.get("strategy_names") or {}
    strategies = [s for s in (pool.get("strategies") or []) if any(c.get("strategy_id") == s for c in candidates)]
    if not strategies or not candidates:
        raise SystemExit("no strategies/candidates")

    dates = sorted(parse_day(c["entry_date"]) for c in candidates if c.get("entry_date"))
    start = dates[0]
    end = dates[-1]
    split = dates[min(len(dates) - 1, int(len(dates) * 0.70))]
    oos_start = split
    train_end = date.fromordinal(split.toordinal() - 1) if split > start else split
    recent_start = max(oos_start, date.fromordinal(end.toordinal() - 730))

    strategy_sets = [(s,) for s in strategies]
    if MAX_STRATEGIES_PER_COMBO >= 2:
        strategy_sets.extend(combinations(strategies, 2))

    cache = {}
    for exit_pct in EXIT_PCTS:
        for hold_cap in HOLD_CAPS:
            by_strategy = defaultdict(list)
            for c in candidates:
                row = execute_candidate(c, pool, exit_pct, hold_cap)
                if row:
                    by_strategy[row["strategy_id"]].append(row)
            for rows in by_strategy.values():
                rows.sort(key=lambda r: (r["start_date"], -num(r.get("priority")), str(r.get("key") or "")))
            cache[(exit_pct, hold_cap)] = by_strategy

    def rows_for(item: dict) -> list[dict]:
        by_strategy = cache[(item["forced_profit_pct"], item["hold_cap_days"])]
        rows = []
        for sid in item["strategies"]:
            rows.extend(by_strategy.get(sid, []))
        return rows

    train_results = []
    tested = 0
    for strategy_set in strategy_sets:
        for exit_pct in EXIT_PCTS:
            for hold_cap in HOLD_CAPS:
                by_strategy = cache[(exit_pct, hold_cap)]
                rows = []
                for sid in strategy_set:
                    rows.extend(by_strategy.get(sid, []))
                if not rows:
                    continue
                for capacity in CAPACITIES:
                    tested += 1
                    train = portfolio(rows, start, train_end, capacity)
                    score = train_score(train)
                    if score <= -900:
                        continue
                    train_results.append({
                        "score": score,
                        "strategies": list(strategy_set),
                        "strategy_names": [strategy_names.get(s, s) for s in strategy_set],
                        "forced_profit_pct": exit_pct,
                        "hold_cap_days": hold_cap,
                        "capacity": capacity,
                        "train_raw": train,
                    })

    SHORTLIST = 100
    shortlists = {}
    union = {}
    for category in ("balanced", "return", "defensive", "turnover"):
        ranked = sorted(train_results, key=lambda x: _category_value(x, category), reverse=True)[:SHORTLIST]
        shortlists[category] = ranked
        for item in ranked:
            key = (tuple(item["strategies"]), item["forced_profit_pct"], item["hold_cap_days"], item["capacity"])
            union[key] = item

    validated_by_key = {}
    for key, item in union.items():
        rows = rows_for(item)
        oos = portfolio(rows, oos_start, end, item["capacity"])
        recent = portfolio(rows, recent_start, end, item["capacity"])
        passed = validation_pass(oos, recent)
        validated_by_key[key] = {
            **item,
            "validation_pass": passed,
            "grade": grade(item["train_raw"], oos, recent),
            "oos_raw": oos,
            "recent_raw": recent,
        }

    def public(item: dict) -> dict:
        return {
            "score": item["score"],
            "grade": item["grade"],
            "validation_pass": item["validation_pass"],
            "strategies": item["strategies"],
            "strategy_names": item["strategy_names"],
            "forced_profit_pct": item["forced_profit_pct"],
            "hold_cap_days": item["hold_cap_days"],
            "capacity": item["capacity"],
            "train": _round_metrics(item["train_raw"]),
            "oos": _round_metrics(item["oos_raw"]),
            "recent": _round_metrics(item["recent_raw"]),
        }

    leaders = {}
    for category, ranked in shortlists.items():
        passed = []
        for item in ranked:
            key = (tuple(item["strategies"]), item["forced_profit_pct"], item["hold_cap_days"], item["capacity"])
            v = validated_by_key.get(key)
            if v and v["validation_pass"]:
                passed.append(public(v))
            if len(passed) >= 10:
                break
        leaders[category] = passed

    payload = {
        "version": 2,
        "ready": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pool_generated_at": pool.get("generated_at"),
        "promotion_status": "research_only",
        "tested_configurations": tested,
        "train_eligible_configurations": len(train_results),
        "shortlisted_configurations": len(union),
        "validated_configurations": sum(1 for x in validated_by_key.values() if x["validation_pass"]),
        "strategy_count": len(strategies),
        "strategy_names": strategy_names,
        "parameter_grid": {
            "forced_profit_pct": list(EXIT_PCTS),
            "hold_cap_days": list(HOLD_CAPS),
            "capacity": list(CAPACITIES),
            "strategy_combo_size": [1, 2],
        },
        "validation": {
            "available_start": start.isoformat(),
            "train_end": train_end.isoformat(),
            "oos_start": oos_start.isoformat(),
            "available_end": end.isoformat(),
            "recent_start": recent_start.isoformat(),
            "method": "chronological 70/30: rank on train only; OOS is pass/fail validation; recent window is a second stability gate",
            "shortlist_per_category": SHORTLIST,
            "min_train_trades": MIN_TRAIN_TRADES,
            "min_oos_trades": MIN_OOS_TRADES,
        },
        "leaders": leaders,
        "notes": [
            "파라미터와 전략 조합 순위는 학습 70% 데이터만 사용해 고정합니다.",
            "뒤 30% OOS와 최근 구간은 순위를 다시 맞추는 데 쓰지 않고 통과/탈락 검증에만 사용합니다.",
            "학습구간 CAGR이 0 이하인 조합은 최적화 후보에서 제외합니다.",
            "실험 결과는 연구용이며 생산 추천이나 자동주문 전략을 자동 변경하지 않습니다.",
            "현재 유동성 종목을 과거로 되감는 후보풀이라 survivorship bias가 남아 있습니다.",
            "후보풀의 일봉 OHLC 한계상 같은 날 STOP/TARGET 동시 터치는 보수적으로 손절 우선 처리합니다.",
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    best = leaders.get("balanced") or []
    print("tested", tested, "train_eligible", len(train_results), "shortlisted", len(union), "validated", payload["validated_configurations"], "best", best[0]["score"] if best else None)


if __name__ == "__main__":
    main()
