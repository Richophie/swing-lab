from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import json
from pathlib import Path
from statistics import mean, median

import pandas as pd

from market_data import indicators, load_price_history
import portfolio_walkforward_research as wf
import strategy_optimizer_runner as mtm
import strategy_optimizer_v2 as opt
import strategy_selection_research as selection

POOL = Path("static/replay_backtest_pool_v2.json")
OUT = Path("static/portfolio_regime_results.json")

# Intentionally tiny, interpretable gate search space. The test year never chooses a gate.
GATES = [
    ("all", "항상 켜기", {"risk_on", "mixed", "risk_off"}, 0.00),
    ("avoid_risk_off", "빨간장만 끄기", {"risk_on", "mixed"}, 0.15),
    ("risk_on_only", "초록장만 켜기", {"risk_on"}, 0.30),
]
REGIME_LABELS = {
    "risk_on": "초록 · SPY/QQQ 모두 200일선 위",
    "mixed": "노랑 · 둘 중 하나만 200일선 위",
    "risk_off": "빨강 · SPY/QQQ 모두 200일선 아래",
    "unknown": "확인불가",
}


def classify_snapshot(spy_close, spy_sma200, qqq_close, qqq_sma200) -> str:
    vals = (spy_close, spy_sma200, qqq_close, qqq_sma200)
    if any(pd.isna(x) for x in vals):
        return "unknown"
    spy_up = float(spy_close) > float(spy_sma200)
    qqq_up = float(qqq_close) > float(qqq_sma200)
    if spy_up and qqq_up:
        return "risk_on"
    if (not spy_up) and (not qqq_up):
        return "risk_off"
    return "mixed"


def gate_accepts(gate_id: str, regime: str) -> bool:
    for gid, _, allowed, _ in GATES:
        if gid == gate_id:
            return regime in allowed
    raise KeyError(gate_id)


def regime_history() -> tuple[dict[str, str], dict]:
    frames = {}
    latest = {}
    for symbol in ("SPY", "QQQ"):
        d = load_price_history(symbol, "10y").copy()
        ind = indicators(d)
        frames[symbol] = pd.DataFrame(
            {f"{symbol.lower()}_close": ind["close"], f"{symbol.lower()}_sma200": ind["sma200"]},
            index=ind.index,
        )
    joined = frames["SPY"].join(frames["QQQ"], how="outer").sort_index().ffill()
    mapping = {}
    for idx, r in joined.iterrows():
        mapping[str(pd.Timestamp(idx).date())] = classify_snapshot(
            r.get("spy_close"), r.get("spy_sma200"), r.get("qqq_close"), r.get("qqq_sma200")
        )
    if len(joined):
        r = joined.iloc[-1]
        latest = {
            "date": str(pd.Timestamp(joined.index[-1]).date()),
            "regime": classify_snapshot(r.get("spy_close"), r.get("spy_sma200"), r.get("qqq_close"), r.get("qqq_sma200")),
            "spy_close": round(float(r["spy_close"]), 4) if pd.notna(r["spy_close"]) else None,
            "spy_sma200": round(float(r["spy_sma200"]), 4) if pd.notna(r["spy_sma200"]) else None,
            "qqq_close": round(float(r["qqq_close"]), 4) if pd.notna(r["qqq_close"]) else None,
            "qqq_sma200": round(float(r["qqq_sma200"]), 4) if pd.notna(r["qqq_sma200"]) else None,
        }
    return mapping, latest


def gate_score(train: dict, raw_train_trades: int, complexity_penalty: float) -> float:
    base = selection.train_pick_score(train, raw_train_trades)
    if base <= -1e8:
        return base
    # Prefer the simpler always-on model when results are effectively tied.
    return base - complexity_penalty


def trade_outcome_stats(items: list[tuple[dict, dict]], start: date, end: date) -> dict:
    groups = defaultdict(list)
    for candidate, row in items:
        d = opt.parse_day(candidate.get("entry_date") or candidate.get("signal_date"))
        if not (start <= d <= end):
            continue
        groups[candidate.get("_regime", "unknown")].append(float(row.get("change") or 0.0) * 100.0)
    out = {}
    for regime in ("risk_on", "mixed", "risk_off", "unknown"):
        xs = groups.get(regime, [])
        out[regime] = {
            "label": REGIME_LABELS[regime],
            "trades": len(xs),
            "win_rate_pct": round(sum(1 for x in xs if x > 0) / len(xs) * 100.0, 2) if xs else 0.0,
            "avg_trade_pct": round(mean(xs), 3) if xs else 0.0,
        }
    return out


def family_fold(family: dict, candidates: list[dict], fold: dict, executed) -> dict:
    thresholds = wf.thresholds_for(candidates, family["strategies"], fold["train_start"], fold["train_end"])
    allowed_strategies = set(family["strategies"])

    executed_pairs = []
    for c in candidates:
        if c.get("strategy_id") not in allowed_strategies:
            continue
        row = executed(c)
        if row:
            executed_pairs.append((c, row))

    raw_rows = [row for c, row in executed_pairs]
    raw_train = mtm.mtm_portfolio(raw_rows, fold["train_start"], fold["train_end"], family["capacity"])
    raw_train_trades = int(raw_train["trades"])

    variants = []
    train_objects = {}
    rows_by_key = {}
    for intensity, intensity_label, keep in selection.INTENSITIES:
        for gate_id, gate_label, _, complexity in GATES:
            rows = []
            for c, row in executed_pairs:
                threshold = thresholds[c["strategy_id"]][intensity]
                if threshold is not None and c["_quality"] < threshold:
                    continue
                if not gate_accepts(gate_id, c.get("_regime", "unknown")):
                    continue
                rows.append(row)
            train = mtm.mtm_portfolio(rows, fold["train_start"], fold["train_end"], family["capacity"])
            key = (intensity, gate_id)
            train_objects[key] = train
            rows_by_key[key] = rows
            variants.append({
                "intensity": intensity,
                "intensity_label": intensity_label,
                "gate": gate_id,
                "gate_label": gate_label,
                "keep_fraction": keep,
                "train_score": round(gate_score(train, raw_train_trades, complexity), 6),
            })

    chosen = max(
        train_objects,
        key=lambda key: gate_score(
            train_objects[key],
            raw_train_trades,
            next(x[3] for x in GATES if x[0] == key[1]),
        ),
    )
    chosen_intensity, chosen_gate = chosen
    selected_rows = rows_by_key[chosen]

    # Fair comparator: same TRAIN-selected quality intensity, but no regime gate.
    baseline_rows = rows_by_key[(chosen_intensity, "all")]
    train_selected = train_objects[chosen]
    test_selected = mtm.mtm_portfolio(selected_rows, fold["test_start"], fold["test_end"], family["capacity"])
    test_baseline = mtm.mtm_portfolio(baseline_rows, fold["test_start"], fold["test_end"], family["capacity"])

    quality_pairs = []
    for c, row in executed_pairs:
        threshold = thresholds[c["strategy_id"]][chosen_intensity]
        if threshold is None or c["_quality"] >= threshold:
            quality_pairs.append((c, row))

    gate_label = next(x[1] for x in GATES if x[0] == chosen_gate)
    intensity_label = next(x[1] for x in selection.INTENSITIES if x[0] == chosen_intensity)
    return {
        "fold": fold["id"],
        "train_start": str(fold["train_start"]),
        "train_end": str(fold["train_end"]),
        "test_start": str(fold["test_start"]),
        "test_end": str(fold["test_end"]),
        "selected_intensity": chosen_intensity,
        "selected_intensity_label": intensity_label,
        "selected_gate": chosen_gate,
        "selected_gate_label": gate_label,
        "thresholds": {
            sid: None if thresholds[sid][chosen_intensity] is None else round(float(thresholds[sid][chosen_intensity]), 6)
            for sid in family["strategies"]
        },
        "train": wf.metric(train_selected),
        "test_gated": wf.metric(test_selected),
        "test_same_quality_no_gate": wf.metric(test_baseline),
        "test_delta_return_pct": round((test_selected["return"] - test_baseline["return"]) * 100.0, 2),
        "test_delta_mdd_pct": round((test_selected["mdd"] - test_baseline["mdd"]) * 100.0, 2),
        "test_regime_trade_diagnosis": trade_outcome_stats(quality_pairs, fold["test_start"], fold["test_end"]),
        "train_variant_count": len(variants),
    }


def summarize(folds: list[dict]) -> dict:
    gated = [f["test_gated"] for f in folds]
    base = [f["test_same_quality_no_gate"] for f in folds]
    gated_returns = [x["return_pct"] for x in gated]
    base_returns = [x["return_pct"] for x in base]
    deltas = [g - b for g, b in zip(gated_returns, base_returns)]
    gated_compound = 1.0
    base_compound = 1.0
    for g, b in zip(gated_returns, base_returns):
        gated_compound *= 1.0 + g / 100.0
        base_compound *= 1.0 + b / 100.0
    gate_counts = Counter(f["selected_gate"] for f in folds)
    intensity_counts = Counter(f["selected_intensity"] for f in folds)
    summary = {
        "fold_count": len(folds),
        "positive_gated_folds": sum(1 for x in gated_returns if x > 0),
        "positive_gated_fold_ratio": round(sum(1 for x in gated_returns if x > 0) / len(folds), 3) if folds else 0.0,
        "gate_helped_folds": sum(1 for x in deltas if x > 0.01),
        "median_gated_test_return_pct": round(median(gated_returns), 2) if gated_returns else 0.0,
        "median_no_gate_test_return_pct": round(median(base_returns), 2) if base_returns else 0.0,
        "mean_gate_delta_return_pct": round(mean(deltas), 2) if deltas else 0.0,
        "stitched_gated_return_pct": round((gated_compound - 1.0) * 100.0, 2),
        "stitched_no_gate_return_pct": round((base_compound - 1.0) * 100.0, 2),
        "worst_gated_mdd_pct": round(min((x["mdd_pct"] for x in gated), default=0.0), 2),
        "worst_no_gate_mdd_pct": round(min((x["mdd_pct"] for x in base), default=0.0), 2),
        "total_gated_test_trades": sum(x["trades"] for x in gated),
        "selected_gate_counts": dict(gate_counts),
        "selected_intensity_counts": dict(intensity_counts),
    }
    # This grade describes robustness of the gating idea, not live readiness.
    if (
        summary["positive_gated_fold_ratio"] >= 0.67
        and summary["gate_helped_folds"] >= max(3, len(folds) - 2)
        and summary["stitched_gated_return_pct"] > summary["stitched_no_gate_return_pct"]
        and summary["worst_gated_mdd_pct"] >= summary["worst_no_gate_mdd_pct"] - 2.0
    ):
        grade = "A"
    elif (
        summary["positive_gated_fold_ratio"] >= 0.50
        and summary["gate_helped_folds"] >= 3
        and summary["stitched_gated_return_pct"] > summary["stitched_no_gate_return_pct"]
        and summary["worst_gated_mdd_pct"] >= summary["worst_no_gate_mdd_pct"] - 5.0
    ):
        grade = "B"
    else:
        grade = "C"
    summary["grade"] = grade
    return summary


def main() -> None:
    pool = json.loads(POOL.read_text(encoding="utf-8"))
    if not pool.get("ready") or int(pool.get("version") or 0) < 4:
        raise SystemExit("Replay pool V4 is required")

    candidates = list(pool.get("trades") or [])
    for c in candidates:
        c["_quality"] = selection.quality_score(c)

    regime_map, latest_regime = regime_history()
    for c in candidates:
        signal_day = str(c.get("signal_date") or c.get("entry_date") or "")[:10]
        c["_regime"] = regime_map.get(signal_day, "unknown")

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

    regime_counts = Counter(c.get("_regime", "unknown") for c in candidates)
    payload = {
        "version": 1,
        "ready": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pool_generated_at": pool.get("generated_at"),
        "promotion_status": "research_only",
        "method": {
            "type": "rolling walk-forward regime gate",
            "market_inputs": "SPY and QQQ close vs trailing SMA200 on signal day only",
            "regimes": REGIME_LABELS,
            "gate_candidates": [
                {"id": gid, "label": label, "allowed_regimes": sorted(allowed)}
                for gid, label, allowed, _ in GATES
            ],
            "selection": "quality intensity and regime gate are jointly selected on each fold TRAIN only",
            "test": "next calendar year is report-only; no retune after seeing test",
            "entry_timing": "signal-day close regime is known before the strategy's next-session entry",
            "equity": "daily_close_mark_to_market",
        },
        "available_start": str(available_start),
        "available_end": str(available_end),
        "latest_market_regime": latest_regime,
        "candidate_regime_counts": dict(regime_counts),
        "families": families,
        "notes": [
            "이 연구는 최근 상승장 편향을 줄일 수 있는 단순한 시장 스위치가 존재하는지 확인하는 단계입니다.",
            "2022/2024 같은 특정 연도를 사람이 직접 제외하지 않습니다. SPY/QQQ 200일선 상태만 사용합니다.",
            "각 fold에서 엄선 강도와 시장 게이트를 TRAIN에서만 선택하고 다음 해에는 그대로 고정합니다.",
            "같은 엄선 강도에서 게이트를 쓰지 않은 결과를 함께 저장해 시장 게이트의 순수한 OOS 기여를 비교합니다.",
            "현재 종목 universe의 survivorship bias는 여전히 남아 있습니다.",
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for f in families:
        s = f["summary"]
        print(
            f["name"], s["grade"],
            f"gated {s['stitched_gated_return_pct']}% vs no-gate {s['stitched_no_gate_return_pct']}%",
            f"helped {s['gate_helped_folds']}/{s['fold_count']}",
        )


if __name__ == "__main__":
    main()
