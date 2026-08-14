from __future__ import annotations

from collections import defaultdict
import json
import math
from statistics import mean

import strategy_optimizer_v2 as opt


_BASE_EXECUTE = opt.execute_candidate


def _mark_factor(close, paid, friction, commission):
    if paid <= 0:
        return 1.0
    return max(0.0, opt.num(close) * (1.0 - friction) * (1.0 - commission) / paid)


def execute_candidate_mtm(c, pool, forced_profit_pct, hold_cap):
    """Attach daily close liquidation marks without changing the trade outcome rules."""
    row = _BASE_EXECUTE(c, pool, forced_profit_pct, hold_cap)
    if not row:
        return None

    path = c.get("path") or []
    if not path:
        return row
    costs = pool.get("costs") or {}
    commission = opt.num(costs.get("commission_pct_per_side"), 0.10) / 100.0
    friction = (
        opt.num(costs.get("slippage_bps"), 5.0)
        + opt.num(costs.get("half_spread_bps"), 2.5)
    ) / 10000.0

    entry_mode = c.get("entry_mode") or "next_open"
    if entry_mode == "intraday_trigger":
        raw_entry = opt.num(c.get("trigger"))
    else:
        raw_entry = opt.num(path[0][1])
    entry = raw_entry * (1.0 + friction)
    paid = entry * (1.0 + commission)
    exit_date = str(row.get("end_date") or "")

    marks = []
    for bar in path:
        d = str(bar[0])
        if exit_date and d > exit_date:
            break
        close = opt.num(bar[4], float("nan"))
        if math.isfinite(close) and close > 0:
            marks.append((d, _mark_factor(close, paid, friction, commission)))

    stop = opt.num(c.get("stop"))
    exit_mode = c.get("exit_mode") or "price_plan"
    hard_stop = 0.0 if exit_mode == "sma20_close" else stop
    if hard_stop > 0:
        stress_factor = _mark_factor(hard_stop, paid, friction, commission)
    else:
        stress_factor = max(0.0, 1.0 - max(0.001, opt.num(row.get("risk_fraction"))))

    row["marks"] = marks
    row["stress_factor"] = stress_factor
    row["mtm_entry_paid"] = paid
    return row


def _equity(cash, open_positions):
    return cash + sum(p["size"] * opt.num(p.get("mark"), 1.0) for p in open_positions.values())


def mtm_portfolio(rows, start, end, capacity, *, presorted=False):
    """Finite-account portfolio with end-of-day marks for every open position."""
    selected = [
        r for r in rows
        if start <= opt.parse_day(r["start_date"]) <= end and opt.parse_day(r["end_date"]) <= end
    ]
    if not presorted:
        selected.sort(key=lambda r: (r["start_date"], -opt.num(r.get("priority")), str(r.get("key") or "")))

    starts = defaultdict(list)
    ends = defaultdict(list)
    mark_updates = defaultdict(list)
    for seq, raw in enumerate(selected):
        row = dict(raw)
        row["_seq"] = seq
        starts[row["start_date"]].append(row)
        ends[row["end_date"]].append(row)
        for mark in row.get("marks") or ():
            if len(mark) < 2:
                continue
            day = str(mark[0])
            if day:
                mark_updates[day].append((seq, opt.num(mark[1], 1.0)))

    days = sorted(set(starts) | set(ends) | set(mark_updates))
    cash = opt.INITIAL_CAPITAL
    peak = cash
    max_drawdown = 0.0
    underwater = 0
    max_underwater = 0
    max_open = 0
    open_positions = {}
    open_symbols = set()
    changes = []
    reject_capacity = 0
    reject_duplicate = 0

    for day in days:
        incoming = sorted(
            starts.get(day, []),
            key=lambda r: (-opt.num(r.get("priority")), str(r.get("key") or ""), r["_seq"]),
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
            size = opt._size_for(total, cash, row.get("risk_fraction"))
            if size < 1:
                continue
            open_positions[row["_seq"]] = {"row": row, "size": size, "mark": 1.0}
            if symbol:
                open_symbols.add(symbol)
            cash -= size
            changes.append(opt.num(row.get("change")))
            max_open = max(max_open, len(open_positions))

        for row in sorted(ends.get(day, []), key=lambda r: r["_seq"]):
            pos = open_positions.get(row["_seq"])
            if not pos:
                continue
            cash += pos["size"] * (1.0 + opt.num(row.get("change")))
            symbol = pos["row"].get("symbol")
            if symbol:
                open_symbols.discard(symbol)
            del open_positions[row["_seq"]]

        for seq, factor in mark_updates.get(day, ()):
            pos = open_positions.get(seq)
            if pos:
                pos["mark"] = factor

        total = _equity(cash, open_positions)
        if total >= peak:
            peak = total
            underwater = 0
        else:
            underwater += 1
            max_underwater = max(max_underwater, underwater)
            if peak > 0:
                max_drawdown = min(max_drawdown, total / peak - 1.0)

    if open_positions:
        for pos in open_positions.values():
            cash += pos["size"] * (1.0 + opt.num(pos["row"].get("change")))

    wins = sum(1 for x in changes if x > 0)
    years = max((end - start).days / 365.25, 0.25)
    cagr = (cash / opt.INITIAL_CAPITAL) ** (1.0 / years) - 1.0 if cash > 0 else -1.0
    return {
        "ending": cash,
        "return": cash / opt.INITIAL_CAPITAL - 1.0,
        "cagr": cagr,
        "mdd": max_drawdown,
        "trades": len(changes),
        "win_rate": wins / len(changes) if changes else 0.0,
        "avg_trade": mean(changes) if changes else 0.0,
        "trades_per_year": len(changes) / years,
        "max_open": max_open,
        "reject_capacity": reject_capacity,
        "reject_duplicate": reject_duplicate,
        "underwater_days": max_underwater,
        "mtm": True,
    }


def _patch_result_metadata():
    data = json.loads(opt.OUT.read_text(encoding="utf-8"))
    data["version"] = 4
    data["risk_model"] = {
        "equity": "daily_close_mark_to_market",
        "mdd": "daily_close_mark_to_market",
        "mark_value": "estimated liquidation value after modeled sell friction and commission",
    }
    data["search_policy"] = {
        "primary_axes": ["strategy_combination", "capacity"],
        "fixed_profit_exit": "secondary_sensitivity_only",
        "forced_hold_cap": "secondary_sensitivity_only",
    }
    old_notes = list(data.get("notes") or [])
    data["notes"] = [
        "메인 자동탐색은 전략 1~5개 조합과 동시보유 1/3/5/7/10을 중심으로 비교합니다. 고정익절·강제 보유상한은 V3 결과에서 영향이 약하거나 OOS 안정성이 떨어져 2차 민감도 실험으로 내렸습니다.",
        "MDD는 열린 포지션을 매 거래일 종가의 예상 청산가치로 평가한 daily Mark-to-Market 기준입니다.",
    ] + [x for x in old_notes if not str(x).startswith("1~5개 전략 조합")]
    opt.OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    # V3 mapped the broad parameter space once. Scheduled research now spends its
    # budget on the axes that actually mattered: strategy family and capacity.
    opt.EXIT_PCTS = (None,)
    opt.HOLD_CAPS = (None,)
    opt.execute_candidate = execute_candidate_mtm
    opt.portfolio = mtm_portfolio
    opt.main()
    _patch_result_metadata()


if __name__ == "__main__":
    main()
