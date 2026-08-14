from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
from statistics import mean, median

import strategy_optimizer_runner as mtm
import strategy_optimizer_v2 as opt
import strategy_selection_research as selection

POOL = Path("static/replay_backtest_pool_v2.json")
OUT = Path("static/portfolio_walkforward_results.json")
TRAIN_YEARS = 4
FIRST_TEST_YEAR = 2021


def metric(x: dict) -> dict:
    return {
        "ending": round(x["ending"], 2),
        "return_pct": round(x["return"] * 100.0, 2),
        "cagr_pct": round(x["cagr"] * 100.0, 2),
        "mdd_pct": round(x["mdd"] * 100.0, 2),
        "trades": int(x["trades"]),
        "win_rate_pct": round(x["win_rate"] * 100.0, 2),
        "avg_trade_pct": round(x["avg_trade"] * 100.0, 3),
        "trades_per_year": round(x["trades_per_year"], 1),
        "max_open": int(x["max_open"]),
        "underwater_days": int(x.get("underwater_days", 0)),
    }


def folds_for(available_start: date, available_end: date) -> list[dict]:
    rows = []
    for test_year in range(max(FIRST_TEST_YEAR, available_start.year + 1), available_end.year + 1):
        test_start = max(date(test_year, 1, 1), available_start)
        test_end = min(date(test_year, 12, 31), available_end)
        train_end = date(test_year - 1, 12, 31)
        train_start = max(available_start, date(test_year - TRAIN_YEARS, 1, 1))
        if test_start > test_end or train_start > train_end:
            continue
        train_days = (train_end - train_start).days
        test_days = (test_end - test_start).days
        if train_days < 365 * 2 or test_days < 60:
            continue
        rows.append({
            "id": str(test_year),
            "train_start": train_start,
            "train_end": train_end,
            "test_start": test_start,
            "test_end": test_end,
        })
    return rows


def thresholds_for(candidates: list[dict], strategies: list[str], train_start: date, train_end: date) -> dict:
    out = {}
    for sid in strategies:
        values = [
            c["_quality"] for c in candidates
            if c.get("strategy_id") == sid
            and train_start <= opt.parse_day(c["entry_date"]) <= train_end
        ]
        out[sid] = {
            intensity: None if keep >= 1 else selection.quantile(values, 1.0 - keep)
            for intensity, _, keep in selection.INTENSITIES
        }
    return out


def filtered_rows(
    candidates: list[dict],
    strategies: list[str],
    thresholds: dict,
    intensity: str,
    executed,
) -> list[dict]:
    allowed = set(strategies)
    rows = []
    for c in candidates:
        sid = c.get("strategy_id")
        if sid not in allowed:
            continue
        threshold = thresholds[sid][intensity]
        if threshold is not None and c["_quality"] < threshold:
            continue
        row = executed(c)
        if row:
            rows.append(row)
    return rows


def family_fold(family: dict, candidates: list[dict], fold: dict, executed) -> dict:
    thresholds = thresholds_for(
        candidates,
        family["strategies"],
        fold["train_start"],
        fold["train_end"],
    )
    variants = {}
    raw_train_trades = 0
    for intensity, label, keep in selection.INTENSITIES:
        rows = filtered_rows(candidates, family["strategies"], thresholds, intensity, executed)
        train = mtm.mtm_portfolio(rows, fold["train_start"], fold["train_end"], family["capacity"])
        if intensity == "raw":
            raw_train_trades = train["trades"]
        variants[intensity] = {
            "label": label,
            "keep_fraction": keep,
            "rows": rows,
            "train": train,
        }

    chosen = max(
        selection.INTENSITIES,
        key=lambda x: selection.train_pick_score(variants[x[0]]["train"], raw_train_trades),
    )[0]
    selected = variants[chosen]
    test = mtm.mtm_portfolio(
        selected["rows"],
        fold["test_start"],
        fold["test_end"],
        family["capacity"],
    )
    return {
        "fold": fold["id"],
        "train_start": str(fold["train_start"]),
        "train_end": str(fold["train_end"]),
        "test_start": str(fold["test_start"]),
        "test_end": str(fold["test_end"]),
        "selected_intensity": chosen,
        "selected_label": selected["label"],
        "thresholds": {
            sid: None if thresholds[sid][chosen] is None else round(float(thresholds[sid][chosen]), 6)
            for sid in family["strategies"]
        },
        "train": metric(selected["train"]),
        "test": metric(test),
    }


def grade(summary: dict) -> str:
    if (
        summary["positive_fold_ratio"] >= 0.80
        and summary["median_test_return_pct"] > 0
        and summary["worst_fold_mdd_pct"] >= -25.0
        and summary["total_test_trades"] >= 80
    ):
        return "A"
    if (
        summary["positive_fold_ratio"] >= 0.67
        and summary["median_test_return_pct"] >= 0
        and summary["worst_fold_mdd_pct"] >= -30.0
        and summary["total_test_trades"] >= 50
    ):
        return "B"
    return "C"


def summarize(folds: list[dict]) -> dict:
    tests = [f["test"] for f in folds]
    returns = [x["return_pct"] for x in tests]
    mdds = [x["mdd_pct"] for x in tests]
    stitched = 1.0
    for value in returns:
        stitched *= 1.0 + value / 100.0
    counts = Counter(f["selected_intensity"] for f in folds)
    total_days = sum(
        max(1, (date.fromisoformat(f["test_end"]) - date.fromisoformat(f["test_start"])).days)
        for f in folds
    )
    years = max(total_days / 365.25, 0.25)
    stitched_cagr = stitched ** (1.0 / years) - 1.0 if stitched > 0 else -1.0
    summary = {
        "fold_count": len(folds),
        "positive_folds": sum(1 for x in returns if x > 0),
        "positive_fold_ratio": round(sum(1 for x in returns if x > 0) / len(folds), 3) if folds else 0.0,
        "mean_test_return_pct": round(mean(returns), 2) if returns else 0.0,
        "median_test_return_pct": round(median(returns), 2) if returns else 0.0,
        "worst_test_return_pct": round(min(returns), 2) if returns else 0.0,
        "best_test_return_pct": round(max(returns), 2) if returns else 0.0,
        "worst_fold_mdd_pct": round(min(mdds), 2) if mdds else 0.0,
        "total_test_trades": sum(x["trades"] for x in tests),
        "stitched_return_pct": round((stitched - 1.0) * 100.0, 2),
        "stitched_cagr_pct": round(stitched_cagr * 100.0, 2),
        "selected_intensity_counts": dict(counts),
    }
    summary["grade"] = grade(summary)
    return summary


def main() -> None:
    pool = json.loads(POOL.read_text(encoding="utf-8"))
    if not pool.get("ready") or int(pool.get("version") or 0) < 4:
        raise SystemExit("Replay pool V4 is required")

    candidates = list(pool.get("trades") or [])
    for c in candidates:
        c["_quality"] = selection.quality_score(c)

    available_start = opt.parse_day(pool["available_start"])
    available_end = opt.parse_day(pool["available_end"])
    folds = folds_for(available_start, available_end)
    if len(folds) < 3:
        raise SystemExit("Not enough history for rolling walk-forward")

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

    payload = {
        "version": 1,
        "ready": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pool_generated_at": pool.get("generated_at"),
        "promotion_status": "research_only",
        "method": {
            "type": "rolling walk-forward",
            "train_window": f"up to {TRAIN_YEARS} calendar years",
            "test_window": "next calendar year; final year may be partial",
            "family": "frozen challenger family and capacity",
            "selection": "each fold recalculates quality thresholds on that fold TRAIN only and selects raw/50/30/15% on TRAIN only",
            "test": "next-year test is report-only; no threshold or family changes after seeing it",
            "equity": "daily_close_mark_to_market",
        },
        "available_start": str(available_start),
        "available_end": str(available_end),
        "folds": [
            {k: str(v) for k, v in fold.items()}
            for fold in folds
        ],
        "families": families,
        "notes": [
            "여러 해의 다음 구간에서 반복적으로 살아남는지 보는 안정성 검사이며 실전 자동승격 기준이 아닙니다.",
            "각 fold의 엄선 강도와 임계값은 그 fold의 TRAIN에서만 결정합니다.",
            "테스트 연도의 결과를 보고 같은 fold의 조건을 다시 조정하지 않습니다.",
            "현재 종목 universe는 survivorship bias가 남아 있으므로 이 단계 통과 뒤 point-in-time universe 검증이 필요합니다.",
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for family in families:
        s = family["summary"]
        print(
            family["name"],
            s["grade"],
            f"positive {s['positive_folds']}/{s['fold_count']}",
            f"median {s['median_test_return_pct']}%",
            f"worst MDD {s['worst_fold_mdd_pct']}%",
        )


if __name__ == "__main__":
    main()
