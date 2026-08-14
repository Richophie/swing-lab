from __future__ import annotations

from collections import defaultdict
from statistics import mean

import strategy_optimizer_v2 as opt


def memory_lean_portfolio(rows, start, end, capacity, *, presorted=False):
    selected = [
        r for r in rows
        if start <= opt.parse_day(r["start_date"]) <= end and opt.parse_day(r["end_date"]) <= end
    ]
    if not presorted:
        selected.sort(key=lambda r: (r["start_date"], -opt.num(r.get("priority")), str(r.get("key") or "")))

    starts = defaultdict(list)
    ends = defaultdict(list)
    for seq, raw in enumerate(selected):
        row = dict(raw)
        row["_seq"] = seq
        starts[row["start_date"]].append(row)
        ends[row["end_date"]].append(row)

    days = sorted(set(starts) | set(ends))
    cash = opt.INITIAL_CAPITAL
    peak = cash
    max_drawdown = 0.0
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
            total = opt._equity(cash, open_positions)
            size = opt._size_for(total, cash, row.get("risk_fraction"))
            if size < 1:
                continue
            open_positions[row["_seq"]] = {"row": row, "size": size}
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

        total = opt._equity(cash, open_positions)
        peak = max(peak, total)
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
    }


def main():
    opt.portfolio = memory_lean_portfolio
    opt.main()


if __name__ == "__main__":
    main()
