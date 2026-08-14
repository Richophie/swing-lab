from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
from statistics import mean, median

import portfolio_walkforward_research as wf
import strategy_optimizer_runner as mtm
import strategy_optimizer_v2 as opt
import strategy_selection_research as selection

POOL = Path("static/replay_backtest_pool_v2.json")
OUT = Path("static/portfolio_priority_audit.json")

# Tiny, pre-registered ranking set. None of these uses future outcomes.
RANKERS = [
    ("current", "현재 priority", "기존 net RR / elite score 우선순위"),
    ("quality_pct", "전략별 품질 백분위", "TRAIN의 같은 전략 품질분포에서 계산한 백분위"),
    ("hybrid_50", "현재+품질 50:50", "TRAIN의 같은 전략 안에서 current priority와 품질 백분위를 50:50 혼합"),
]


def empirical_percentile(sorted_values: list[float], value: float) -> float:
    """Mid-rank percentile against TRAIN values only; ties receive the same percentile."""
    if not sorted_values:
        return 0.5
    x = float(value)
    lo = bisect_left(sorted_values, x)
    hi = bisect_right(sorted_values, x)
    return ((lo + hi) / 2.0) / len(sorted_values)


def corr(xs: list[float], ys: list[float]):
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    mx, my = mean(xs), mean(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 1e-15 or vy <= 1e-15:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(vx * vy)


def metric(x: dict) -> dict:
    return wf.metric(x)


def _audit_row(candidate: dict, row: dict) -> dict:
    out = dict(row)
    out["_audit_quality"] = float(candidate.get("_quality", 0.0))
    out["_audit_current_priority"] = float(row.get("priority") or 0.0)
    out["_audit_signal_date"] = str(candidate.get("signal_date") or "")[:10]
    return out


def choose_quality_intensity(family: dict, candidates: list[dict], fold: dict, executed):
    """Freeze the same strategy-quality strength using TRAIN only before auditing ranking."""
    thresholds = wf.thresholds_for(candidates, family["strategies"], fold["train_start"], fold["train_end"])
    allowed = set(family["strategies"])
    pairs = []
    for c in candidates:
        if c.get("strategy_id") not in allowed:
            continue
        row = executed(c)
        if row:
            pairs.append((c, _audit_row(c, row)))

    raw_rows = [row for _, row in pairs]
    raw_train = mtm.mtm_portfolio(raw_rows, fold["train_start"], fold["train_end"], family["capacity"])
    raw_train_trades = int(raw_train["trades"])

    train_objects = {}
    pairs_by_intensity = {}
    for intensity, _, _ in selection.INTENSITIES:
        kept = []
        for c, row in pairs:
            threshold = thresholds[c["strategy_id"]][intensity]
            if threshold is None or c["_quality"] >= threshold:
                kept.append((c, row))
        pairs_by_intensity[intensity] = kept
        train_objects[intensity] = mtm.mtm_portfolio(
            [row for _, row in kept], fold["train_start"], fold["train_end"], family["capacity"]
        )

    chosen = max(
        selection.INTENSITIES,
        key=lambda x: selection.train_pick_score(train_objects[x[0]], raw_train_trades),
    )[0]
    return chosen, thresholds, train_objects[chosen], pairs_by_intensity[chosen]


def train_distributions(pairs: list[tuple[dict, dict]], start: date, end: date) -> dict:
    by_strategy = defaultdict(lambda: {"quality": [], "priority": []})
    for c, row in pairs:
        d = opt.parse_day(row["start_date"])
        if not (start <= d <= end):
            continue
        sid = str(c.get("strategy_id") or row.get("strategy_id") or "")
        by_strategy[sid]["quality"].append(float(c.get("_quality", 0.0)))
        by_strategy[sid]["priority"].append(float(row.get("priority") or 0.0))
    for values in by_strategy.values():
        values["quality"].sort()
        values["priority"].sort()
    return dict(by_strategy)


def rank_value(ranker: str, c: dict, row: dict, distributions: dict) -> float:
    if ranker == "current":
        return float(row.get("_audit_current_priority", row.get("priority") or 0.0))
    sid = str(c.get("strategy_id") or row.get("strategy_id") or "")
    dist = distributions.get(sid) or {"quality": [], "priority": []}
    q = empirical_percentile(dist.get("quality") or [], float(c.get("_quality", 0.0)))
    if ranker == "quality_pct":
        return q
    p = empirical_percentile(
        dist.get("priority") or [], float(row.get("_audit_current_priority", row.get("priority") or 0.0))
    )
    if ranker == "hybrid_50":
        return 0.5 * q + 0.5 * p
    raise KeyError(ranker)


def rows_for_ranker(pairs: list[tuple[dict, dict]], ranker: str, distributions: dict) -> list[dict]:
    rows = []
    for c, row in pairs:
        x = dict(row)
        x["priority"] = rank_value(ranker, c, row, distributions)
        x["_audit_ranker"] = ranker
        rows.append(x)
    return rows


def decision_trace(rows: list[dict], start: date, end: date, capacity: int) -> dict:
    """Replay the exact MTM account ordering and keep accepted/capacity-rejected decisions."""
    selected = [
        dict(r) for r in rows
        if start <= opt.parse_day(r["start_date"]) <= end and opt.parse_day(r["end_date"]) <= end
    ]
    selected.sort(key=lambda r: (r["start_date"], -opt.num(r.get("priority")), str(r.get("key") or "")))

    starts = defaultdict(list)
    ends = defaultdict(list)
    mark_updates = defaultdict(list)
    for seq, row in enumerate(selected):
        row["_seq"] = seq
        starts[row["start_date"]].append(row)
        ends[row["end_date"]].append(row)
        for mark in row.get("marks") or ():
            if len(mark) >= 2 and str(mark[0]):
                mark_updates[str(mark[0])].append((seq, opt.num(mark[1], 1.0)))

    days = sorted(set(starts) | set(ends) | set(mark_updates))
    cash = opt.INITIAL_CAPITAL
    open_positions = {}
    open_symbols = set()
    accepted = []
    rejected_capacity = []
    rejected_duplicate = []

    for day in days:
        incoming = sorted(
            starts.get(day, []),
            key=lambda r: (-opt.num(r.get("priority")), str(r.get("key") or ""), r["_seq"]),
        )
        for row in incoming:
            symbol = row.get("symbol")
            if symbol and symbol in open_symbols:
                rejected_duplicate.append({**row, "decision_day": day})
                continue
            if len(open_positions) >= capacity:
                blocked = [
                    {
                        "symbol": p["row"].get("symbol"),
                        "strategy_id": p["row"].get("strategy_id"),
                        "priority": round(opt.num(p["row"].get("priority")), 6),
                    }
                    for p in open_positions.values()
                ]
                rejected_capacity.append({**row, "decision_day": day, "blocked_by": blocked})
                continue
            total = cash + sum(p["size"] * opt.num(p.get("mark"), 1.0) for p in open_positions.values())
            size = opt._size_for(total, cash, row.get("risk_fraction"))
            if size < 1:
                continue
            open_positions[row["_seq"]] = {"row": row, "size": size, "mark": 1.0}
            if symbol:
                open_symbols.add(symbol)
            cash -= size
            accepted.append({**row, "decision_day": day, "size": size})

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

    return {
        "accepted": accepted,
        "rejected_capacity": rejected_capacity,
        "rejected_duplicate": rejected_duplicate,
    }


def decision_stats(trace: dict) -> dict:
    accepted = trace["accepted"]
    rejected = trace["rejected_capacity"]

    def avg(rows, field):
        xs = [float(r.get(field) or 0.0) for r in rows]
        return mean(xs) if xs else 0.0

    missed = sorted(rejected, key=lambda r: float(r.get("change") or 0.0), reverse=True)
    examples = [
        {
            "date": str(r.get("decision_day") or r.get("start_date")),
            "symbol": r.get("symbol"),
            "strategy_id": r.get("strategy_id"),
            "hypothetical_return_pct": round(float(r.get("change") or 0.0) * 100.0, 2),
            "quality": round(float(r.get("_audit_quality") or 0.0), 2),
            "current_priority": round(float(r.get("_audit_current_priority") or 0.0), 4),
            "rank_priority": round(float(r.get("priority") or 0.0), 4),
        }
        for r in missed[:12]
    ]
    return {
        "accepted": len(accepted),
        "capacity_rejected": len(rejected),
        "duplicate_rejected": len(trace["rejected_duplicate"]),
        "accepted_avg_trade_pct": round(avg(accepted, "change") * 100.0, 3),
        "capacity_rejected_avg_trade_pct": round(avg(rejected, "change") * 100.0, 3),
        "accepted_avg_quality": round(avg(accepted, "_audit_quality"), 2),
        "capacity_rejected_avg_quality": round(avg(rejected, "_audit_quality"), 2),
        "capacity_rejected_winners": sum(1 for r in rejected if float(r.get("change") or 0.0) > 0),
        "capacity_rejected_plus5": sum(1 for r in rejected if float(r.get("change") or 0.0) >= 0.05),
        "capacity_rejected_plus10": sum(1 for r in rejected if float(r.get("change") or 0.0) >= 0.10),
        "top_rejected_examples": examples,
    }


def strategy_discrimination(pairs: list[tuple[dict, dict]], start: date, end: date) -> dict:
    groups = defaultdict(list)
    for c, row in pairs:
        d = opt.parse_day(row["start_date"])
        if start <= d <= end:
            groups[str(c.get("strategy_id"))].append((c, row))
    out = {}
    for sid, items in groups.items():
        current = [float(r.get("_audit_current_priority", r.get("priority") or 0.0)) for _, r in items]
        quality = [float(c.get("_quality", 0.0)) for c, _ in items]
        changes = [float(r.get("change") or 0.0) * 100.0 for _, r in items]
        out[sid] = {
            "signals": len(items),
            "unique_current_priorities": len(set(round(x, 8) for x in current)),
            "current_priority_min": round(min(current), 4) if current else None,
            "current_priority_max": round(max(current), 4) if current else None,
            "current_priority_return_corr": None if corr(current, changes) is None else round(corr(current, changes), 4),
            "quality_return_corr": None if corr(quality, changes) is None else round(corr(quality, changes), 4),
        }
    return out


def family_fold(family: dict, candidates: list[dict], fold: dict, executed) -> dict:
    chosen, thresholds, train_current, pairs = choose_quality_intensity(family, candidates, fold, executed)
    distributions = train_distributions(pairs, fold["train_start"], fold["train_end"])
    intensity_label = next(x[1] for x in selection.INTENSITIES if x[0] == chosen)

    rankers = {}
    traces = {}
    for rid, label, description in RANKERS:
        rows = rows_for_ranker(pairs, rid, distributions)
        train = mtm.mtm_portfolio(rows, fold["train_start"], fold["train_end"], family["capacity"])
        test = mtm.mtm_portfolio(rows, fold["test_start"], fold["test_end"], family["capacity"])
        trace = decision_trace(rows, fold["test_start"], fold["test_end"], family["capacity"])
        rankers[rid] = {
            "label": label,
            "description": description,
            "train": metric(train),
            "test": metric(test),
            "decision_audit": decision_stats(trace),
        }
        traces[rid] = trace

    return {
        "fold": fold["id"],
        "train_start": str(fold["train_start"]),
        "train_end": str(fold["train_end"]),
        "test_start": str(fold["test_start"]),
        "test_end": str(fold["test_end"]),
        "selected_intensity": chosen,
        "selected_intensity_label": intensity_label,
        "thresholds": {
            sid: None if thresholds[sid][chosen] is None else round(float(thresholds[sid][chosen]), 6)
            for sid in family["strategies"]
        },
        "rankers": rankers,
        "strategy_discrimination": strategy_discrimination(pairs, fold["test_start"], fold["test_end"]),
    }


def summarize_rule(folds: list[dict], rid: str) -> dict:
    tests = [f["rankers"][rid]["test"] for f in folds]
    returns = [x["return_pct"] for x in tests]
    compound = 1.0
    for x in returns:
        compound *= 1.0 + x / 100.0
    return {
        "stitched_test_return_pct": round((compound - 1.0) * 100.0, 2),
        "median_test_return_pct": round(median(returns), 2) if returns else 0.0,
        "positive_test_folds": sum(1 for x in returns if x > 0),
        "worst_test_mdd_pct": round(min((x["mdd_pct"] for x in tests), default=0.0), 2),
        "total_test_trades": sum(x["trades"] for x in tests),
    }


def summarize(folds: list[dict]) -> dict:
    rules = {rid: summarize_rule(folds, rid) for rid, _, _ in RANKERS}
    baseline = [f["rankers"]["current"]["test"]["return_pct"] for f in folds]
    for rid in ("quality_pct", "hybrid_50"):
        xs = [f["rankers"][rid]["test"]["return_pct"] for f in folds]
        rules[rid]["folds_beating_current"] = sum(1 for a, b in zip(xs, baseline) if a > b + 0.01)
        rules[rid]["mean_delta_vs_current_pct"] = round(mean(a - b for a, b in zip(xs, baseline)), 2)

    current_audits = [f["rankers"]["current"]["decision_audit"] for f in folds]
    rejected = sum(x["capacity_rejected"] for x in current_audits)
    plus5 = sum(x["capacity_rejected_plus5"] for x in current_audits)
    plus10 = sum(x["capacity_rejected_plus10"] for x in current_audits)
    current_summary = {
        "capacity_rejected": rejected,
        "capacity_rejected_plus5": plus5,
        "capacity_rejected_plus10": plus10,
        "plus5_share_of_rejects": round(plus5 / rejected, 3) if rejected else 0.0,
        "plus10_share_of_rejects": round(plus10 / rejected, 3) if rejected else 0.0,
    }

    fold_2024 = next((f for f in folds if f["fold"] == "2024"), None)
    return {
        "rules": rules,
        "current_slot_audit": current_summary,
        "test_2024": None if not fold_2024 else {
            rid: {
                "return_pct": fold_2024["rankers"][rid]["test"]["return_pct"],
                "mdd_pct": fold_2024["rankers"][rid]["test"]["mdd_pct"],
                "capacity_rejected": fold_2024["rankers"][rid]["decision_audit"]["capacity_rejected"],
                "rejected_plus5": fold_2024["rankers"][rid]["decision_audit"]["capacity_rejected_plus5"],
                "rejected_plus10": fold_2024["rankers"][rid]["decision_audit"]["capacity_rejected_plus10"],
            }
            for rid, _, _ in RANKERS
        },
    }


def main() -> None:
    pool = json.loads(POOL.read_text(encoding="utf-8"))
    if not pool.get("ready") or int(pool.get("version") or 0) < 4:
        raise SystemExit("Replay pool V4 is required")

    candidates = list(pool.get("trades") or [])
    for c in candidates:
        c["_quality"] = selection.quality_score(c)

    available_start = opt.parse_day(pool["available_start"])
    available_end = opt.parse_day(pool["available_end"])
    folds = wf.folds_for(available_start, available_end)
    if len(folds) < 3:
        raise SystemExit("Not enough history")

    cache = {}
    def executed(c):
        key = (c.get("symbol"), c.get("strategy_id"), c.get("signal_date"))
        if key not in cache:
            cache[key] = mtm.execute_candidate_mtm(c, pool, None, None)
        return cache[key]

    families = []
    for family in selection.FAMILIES:
        rows = [family_fold(family, candidates, fold, executed) for fold in folds]
        families.append({
            "id": family["id"],
            "name": family["name"],
            "strategies": family["strategies"],
            "capacity": family["capacity"],
            "summary": summarize(rows),
            "folds": rows,
        })

    donchian_priorities = sorted({
        round(float(c.get("net_risk_reward") or 0.0), 8)
        for c in candidates if c.get("strategy_id") == "donchian_55"
    })
    payload = {
        "version": 1,
        "ready": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pool_generated_at": pool.get("generated_at"),
        "promotion_status": "research_only_diagnostic",
        "method": {
            "type": "rolling OOS priority and capacity audit",
            "quality_selection": "quality intensity frozen on each fold TRAIN only using the existing current-priority process",
            "rankers": [
                {"id": rid, "label": label, "description": desc}
                for rid, label, desc in RANKERS
            ],
            "alternative_rank_inputs": "signal-day quality score and TRAIN-only within-strategy empirical percentiles",
            "test": "next calendar year report-only; no ranker is promoted by this study",
            "equity": "daily_close_mark_to_market",
            "rejected_outcome": "hypothetical standalone outcome of a capacity-rejected valid signal; not additive missed account P&L",
        },
        "available_start": str(available_start),
        "available_end": str(available_end),
        "donchian_current_priority_values": donchian_priorities,
        "families": families,
        "notes": [
            "현재 실행 priority는 net_risk_reward가 있으면 그것을 사용하고, 없을 때 elite_score/100을 사용합니다.",
            "현재 Donchian 후보 생성기는 net_risk_reward=2.0을 고정 저장하므로 Donchian끼리 current priority가 동률입니다.",
            "동률은 기존 엔진과 동일하게 key 순서로 결정되며, 이것이 슬롯 경쟁에서 품질과 무관한 선택을 만들 수 있는지 감사합니다.",
            "대안 priority는 미래수익을 사용하지 않습니다. 품질/priority 백분위 기준분포도 각 fold TRAIN에서만 만듭니다.",
            "슬롯 탈락 후보의 이후 수익은 반사실적 참고값이며, 그 후보를 실제로 샀다면 계좌수익이 그대로 그만큼 늘었다는 뜻이 아닙니다.",
            "이 결과는 RESEARCH ONLY이며 production 추천/주문 priority를 자동 변경하지 않습니다.",
            "현재 종목 universe의 survivorship bias는 여전히 남아 있습니다.",
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Donchian current priority values", donchian_priorities)
    for family in families:
        s = family["summary"]
        print(
            family["name"],
            "current", s["rules"]["current"]["stitched_test_return_pct"],
            "quality", s["rules"]["quality_pct"]["stitched_test_return_pct"],
            "hybrid", s["rules"]["hybrid_50"]["stitched_test_return_pct"],
            "rejects", s["current_slot_audit"]["capacity_rejected"],
        )


if __name__ == "__main__":
    main()
