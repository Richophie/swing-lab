from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean, median

import portfolio_walkforward_research as wf
import strategy_optimizer_runner as mtm
import strategy_optimizer_v2 as opt
import strategy_selection_research as selection
from smart_money_flow import score_live_flow

POOL = Path("static/replay_backtest_pool_v2.json")
OUT = Path("static/smart_money_component_diagnostic.json")
COMPONENTS = ("participation", "absorption", "liquidity")
QUANTILE = 0.75
STRONG_SCORE = 75.0


def metric(x: dict) -> dict:
    return wf.metric(x)


def compound(values: list[float]) -> float:
    x = 1.0
    for value in values:
        x *= 1.0 + float(value) / 100.0
    return round((x - 1.0) * 100.0, 2)


def percentile(values: list[float], q: float) -> float | None:
    clean = sorted(float(x) for x in values)
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    pos = max(0.0, min(1.0, q)) * (len(clean) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(clean) - 1)
    frac = pos - lo
    return clean[lo] * (1.0 - frac) + clean[hi] * frac


def concentration(rows: list[dict], start, end) -> dict:
    eligible = [
        r for r in rows
        if start <= opt.parse_day(r["start_date"]) <= end
        and opt.parse_day(r["end_date"]) <= end
    ]
    counts = Counter(str(r.get("symbol") or "?") for r in eligible)
    total = sum(counts.values())
    top = counts.most_common(5)
    hhi = sum((n / total) ** 2 for n in counts.values()) if total else 0.0
    by_symbol = defaultdict(list)
    for row in eligible:
        by_symbol[str(row.get("symbol") or "?")].append(float(row.get("change") or 0.0) * 100.0)
    leaders = []
    for symbol, n in top:
        vals = by_symbol[symbol]
        leaders.append({
            "symbol": symbol,
            "signals": n,
            "share_pct": round(n / total * 100.0, 2) if total else 0.0,
            "mean_trade_pct": round(mean(vals), 3) if vals else 0.0,
        })
    changes = [float(r.get("change") or 0.0) * 100.0 for r in eligible]
    return {
        "eligible_signals": total,
        "unique_symbols": len(counts),
        "top_symbol_share_pct": round(top[0][1] / total * 100.0, 2) if total and top else 0.0,
        "top5_symbol_share_pct": round(sum(n for _, n in top) / total * 100.0, 2) if total else 0.0,
        "symbol_hhi": round(hhi, 4),
        "mean_trade_pct": round(mean(changes), 3) if changes else 0.0,
        "win_rate_pct": round(sum(x > 0 for x in changes) / len(changes) * 100.0, 2) if changes else 0.0,
        "top_symbols": leaders,
    }


def rows_for_family(candidates: list[dict], family: dict, thresholds: dict, intensity: str, executed):
    allowed = set(family["strategies"])
    rows = []
    for c in candidates:
        sid = c.get("strategy_id")
        if sid not in allowed:
            continue
        threshold = thresholds[sid][intensity]
        if threshold is not None and c["_quality"] < threshold:
            continue
        raw = executed(c)
        if not raw:
            continue
        row = dict(raw)
        row["_smart_money_score"] = c["_smart_money_score"]
        row["_smart_money_components"] = dict(c["_smart_money_components"])
        rows.append(row)
    return rows


def pick_quality(family: dict, candidates: list[dict], fold: dict, executed):
    thresholds = wf.thresholds_for(candidates, family["strategies"], fold["train_start"], fold["train_end"])
    variants = {}
    raw_train_trades = 0
    for intensity, label, keep in selection.INTENSITIES:
        rows = rows_for_family(candidates, family, thresholds, intensity, executed)
        train = mtm.mtm_portfolio(rows, fold["train_start"], fold["train_end"], family["capacity"])
        if intensity == "raw":
            raw_train_trades = train["trades"]
        variants[intensity] = {"rows": rows, "train": train, "label": label, "keep": keep}
    chosen = max(
        selection.INTENSITIES,
        key=lambda x: selection.train_pick_score(variants[x[0]]["train"], raw_train_trades),
    )[0]
    return chosen, thresholds, variants[chosen]["rows"]


def train_component_thresholds(rows: list[dict], fold: dict) -> dict:
    train_rows = [
        r for r in rows
        if fold["train_start"] <= opt.parse_day(r["start_date"]) <= fold["train_end"]
        and opt.parse_day(r["end_date"]) <= fold["train_end"]
    ]
    out = {}
    for component in COMPONENTS:
        vals = [float((r.get("_smart_money_components") or {}).get(component) or 0.0) for r in train_rows]
        out[component] = percentile(vals, QUANTILE)
    return out


def filter_rows(rows: list[dict], variant: str, thresholds: dict) -> list[dict]:
    if variant == "baseline":
        return list(rows)
    if variant == "total_strong":
        return [r for r in rows if float(r.get("_smart_money_score") or 0.0) >= STRONG_SCORE]
    if variant.endswith("_q75"):
        component = variant[:-4]
        threshold = thresholds.get(component)
        if threshold is None:
            return []
        return [
            r for r in rows
            if float((r.get("_smart_money_components") or {}).get(component) or 0.0) >= float(threshold)
        ]
    if variant == "participation_absorption_joint":
        p = thresholds.get("participation")
        a = thresholds.get("absorption")
        if p is None or a is None:
            return []
        return [
            r for r in rows
            if float((r.get("_smart_money_components") or {}).get("participation") or 0.0) >= float(p)
            and float((r.get("_smart_money_components") or {}).get("absorption") or 0.0) >= float(a)
        ]
    raise ValueError(f"unknown variant: {variant}")


VARIANTS = (
    "baseline",
    "total_strong",
    "participation_q75",
    "absorption_q75",
    "liquidity_q75",
    "participation_absorption_joint",
)


def family_fold(family: dict, candidates: list[dict], fold: dict, executed) -> dict:
    chosen, quality_thresholds, rows = pick_quality(family, candidates, fold, executed)
    component_thresholds = train_component_thresholds(rows, fold)
    out = {
        "fold": fold["id"],
        "train_start": str(fold["train_start"]),
        "train_end": str(fold["train_end"]),
        "test_start": str(fold["test_start"]),
        "test_end": str(fold["test_end"]),
        "selected_quality_intensity": chosen,
        "quality_thresholds": {
            sid: None if quality_thresholds[sid][chosen] is None else round(float(quality_thresholds[sid][chosen]), 6)
            for sid in family["strategies"]
        },
        "component_q75_thresholds": {
            k: None if v is None else round(float(v), 3) for k, v in component_thresholds.items()
        },
        "variants": {},
    }
    for variant in VARIANTS:
        kept = filter_rows(rows, variant, component_thresholds)
        test = mtm.mtm_portfolio(kept, fold["test_start"], fold["test_end"], family["capacity"])
        out["variants"][variant] = {
            **metric(test),
            "concentration": concentration(kept, fold["test_start"], fold["test_end"]),
        }

    base = out["variants"]["baseline"]
    for variant in VARIANTS[1:]:
        v = out["variants"][variant]
        v["delta_return_vs_baseline_pct"] = round(v["return_pct"] - base["return_pct"], 2)
        v["delta_mdd_vs_baseline_pct"] = round(v["mdd_pct"] - base["mdd_pct"], 2)
    return out


def summarize_variant(folds: list[dict], variant: str) -> dict:
    rows = [f["variants"][variant] for f in folds]
    returns = [x["return_pct"] for x in rows]
    mdds = [x["mdd_pct"] for x in rows]
    concentrations = [x["concentration"]["top_symbol_share_pct"] for x in rows if x["concentration"]["eligible_signals"]]
    out = {
        "fold_count": len(rows),
        "positive_folds": sum(x > 0 for x in returns),
        "stitched_test_return_pct": compound(returns),
        "median_test_return_pct": round(median(returns), 2) if returns else 0.0,
        "worst_test_mdd_pct": round(min(mdds), 2) if mdds else 0.0,
        "total_test_trades": sum(x["trades"] for x in rows),
        "median_top_symbol_share_pct": round(median(concentrations), 2) if concentrations else 0.0,
        "max_top_symbol_share_pct": round(max(concentrations), 2) if concentrations else 0.0,
    }
    if variant != "baseline":
        deltas = [f["variants"][variant]["delta_return_vs_baseline_pct"] for f in folds]
        mdd_deltas = [f["variants"][variant]["delta_mdd_vs_baseline_pct"] for f in folds]
        out.update({
            "folds_beating_baseline": sum(x > 0.01 for x in deltas),
            "mean_delta_return_vs_baseline_pct": round(mean(deltas), 2) if deltas else 0.0,
            "median_delta_return_vs_baseline_pct": round(median(deltas), 2) if deltas else 0.0,
            "worst_mdd_delta_vs_baseline_pct": round(min(mdd_deltas), 2) if mdd_deltas else 0.0,
        })
    return out


def summarize(folds: list[dict]) -> dict:
    variants = {name: summarize_variant(folds, name) for name in VARIANTS}
    base_stitched = variants["baseline"]["stitched_test_return_pct"]
    for name in VARIANTS[1:]:
        variants[name]["stitched_delta_vs_baseline_pct"] = round(
            variants[name]["stitched_test_return_pct"] - base_stitched, 2
        )

    components = ["participation_q75", "absorption_q75", "liquidity_q75"]
    dominant = max(
        components,
        key=lambda name: (
            variants[name].get("folds_beating_baseline", 0),
            variants[name].get("stitched_delta_vs_baseline_pct", -999),
            variants[name].get("mean_delta_return_vs_baseline_pct", -999),
        ),
    )
    ds = variants[dominant]
    if (
        ds.get("folds_beating_baseline", 0) >= 4
        and ds.get("stitched_delta_vs_baseline_pct", 0) > 5
        and ds.get("total_test_trades", 0) >= 80
        and ds.get("max_top_symbol_share_pct", 100) <= 35
    ):
        pattern = "component_repeats_development_only"
    elif ds.get("folds_beating_baseline", 0) >= 3 and ds.get("stitched_delta_vs_baseline_pct", 0) > 0:
        pattern = "mixed_component_signal"
    else:
        pattern = "no_repeating_component"

    recent = {}
    for fold in folds:
        if str(fold["fold"]) in {"2024", "2025", "2026"}:
            recent[str(fold["fold"])] = {
                name: {
                    "return_pct": fold["variants"][name]["return_pct"],
                    "delta_return_vs_baseline_pct": fold["variants"][name].get("delta_return_vs_baseline_pct"),
                    "trades": fold["variants"][name]["trades"],
                    "top_symbol_share_pct": fold["variants"][name]["concentration"]["top_symbol_share_pct"],
                    "top_symbols": fold["variants"][name]["concentration"]["top_symbols"][:3],
                }
                for name in VARIANTS
            }

    return {
        "pattern": pattern,
        "dominant_component_variant": dominant,
        "variants": variants,
        "recent_2024_2026": recent,
        "selected_quality_intensity_counts": dict(Counter(f["selected_quality_intensity"] for f in folds)),
    }


def main() -> None:
    pool = json.loads(POOL.read_text(encoding="utf-8"))
    if not pool.get("ready") or int(pool.get("version") or 0) < 4:
        raise SystemExit("Replay pool V4 is required")
    if int(pool.get("smart_money_features_version") or 0) < 1:
        raise SystemExit("signal-day Smart Money features are required")

    candidates = [dict(x) for x in pool.get("trades") or []]
    for c in candidates:
        c["_quality"] = selection.quality_score(c)
        scored = score_live_flow(c.get("smart_money_flow") or {})
        c["_smart_money_score"] = float(scored.get("score") or 0.0)
        c["_smart_money_components"] = {
            k: float((scored.get("components") or {}).get(k) or 0.0) for k in COMPONENTS
        }

    start = opt.parse_day(pool["available_start"])
    end = opt.parse_day(pool["available_end"])
    folds = wf.folds_for(start, end)
    if len(folds) < 3:
        raise SystemExit("not enough folds")

    cache = {}
    def executed(c):
        key = (c.get("symbol"), c.get("strategy_id"), c.get("signal_date"))
        if key not in cache:
            cache[key] = mtm.execute_candidate_mtm(c, pool, None, None)
        return cache[key]

    families = []
    for family in selection.FAMILIES:
        fold_rows = [family_fold(family, candidates, fold, executed) for fold in folds]
        families.append({
            "id": family["id"],
            "name": family["name"],
            "strategies": family["strategies"],
            "capacity": family["capacity"],
            "summary": summarize(fold_rows),
            "folds": fold_rows,
        })

    payload = {
        "version": 1,
        "ready": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pool_generated_at": pool.get("generated_at"),
        "promotion_status": "diagnostic_only_no_rank_mutation",
        "method": {
            "type": "rolling OOS Smart Money component attribution diagnostic",
            "component_thresholds": "75th percentile of each component distribution on each fold TRAIN only",
            "component_threshold_uses_returns": False,
            "total_strong_threshold": STRONG_SCORE,
            "quality_selection": "existing quality intensity selected on TRAIN only",
            "test": "next calendar year report only",
            "concentration": "pre-capacity eligible signal concentration; diagnostic, not exact portfolio attribution",
            "production_main_picker_mutated": False,
            "buy_target_stop_mutated": False,
            "automatic_promotion": False,
            "warning": "current-universe survivorship bias remains; this is development attribution evidence",
        },
        "available_start": str(start),
        "available_end": str(end),
        "families": families,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for family in families:
        s = family["summary"]
        d = s["variants"][s["dominant_component_variant"]]
        print(
            family["id"],
            s["pattern"],
            s["dominant_component_variant"],
            "fold wins", d.get("folds_beating_baseline"),
            "stitched delta", d.get("stitched_delta_vs_baseline_pct"),
        )


if __name__ == "__main__":
    main()
