from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean, median

import portfolio_walkforward_research as wf
import strategy_optimizer_runner as mtm
import strategy_optimizer_v2 as opt
import strategy_selection_research as selection
from smart_money_flow import score_live_flow

POOL=Path("static/replay_backtest_pool_v2.json")
OUT=Path("static/smart_money_flow_research.json")
WATCH_SCORE=62.0
STRONG_SCORE=75.0
VARIANTS=(("baseline",None),("watch_plus",WATCH_SCORE),("strong",STRONG_SCORE))


def metric(x: dict) -> dict:
    return wf.metric(x)


def _compound(values: list[float]) -> float:
    x=1.0
    for value in values:
        x*=1.0+float(value)/100.0
    return round((x-1.0)*100.0,2)


def _smart_score(c: dict) -> float:
    return float(score_live_flow(c.get("smart_money_flow") or {}).get("score") or 0.0)


def _rows_for(
    candidates: list[dict],
    strategies: list[str],
    thresholds: dict,
    intensity: str,
    executed,
) -> list[dict]:
    allowed=set(strategies)
    rows=[]
    for c in candidates:
        sid=c.get("strategy_id")
        if sid not in allowed:
            continue
        threshold=thresholds[sid][intensity]
        if threshold is not None and c["_quality"] < threshold:
            continue
        row=executed(c)
        if not row:
            continue
        row=dict(row)
        row["_smart_money_score"]=c["_smart_money_score"]
        rows.append(row)
    return rows


def _pick_quality(family: dict,candidates: list[dict],fold: dict,executed):
    thresholds=wf.thresholds_for(candidates,family["strategies"],fold["train_start"],fold["train_end"])
    variants={}
    raw_train_trades=0
    for intensity,label,keep in selection.INTENSITIES:
        rows=_rows_for(candidates,family["strategies"],thresholds,intensity,executed)
        train=mtm.mtm_portfolio(rows,fold["train_start"],fold["train_end"],family["capacity"])
        if intensity=="raw":
            raw_train_trades=train["trades"]
        variants[intensity]={"rows":rows,"train":train,"label":label,"keep":keep}
    chosen=max(
        selection.INTENSITIES,
        key=lambda x: selection.train_pick_score(variants[x[0]]["train"],raw_train_trades),
    )[0]
    return chosen,thresholds,variants[chosen]["rows"]


def _filtered(rows: list[dict],minimum: float | None) -> list[dict]:
    if minimum is None:
        return list(rows)
    return [r for r in rows if float(r.get("_smart_money_score") or 0)>=minimum]


def family_fold(family: dict,candidates: list[dict],fold: dict,executed) -> dict:
    chosen,thresholds,rows=_pick_quality(family,candidates,fold,executed)
    out={
        "fold":fold["id"],
        "train_start":str(fold["train_start"]),
        "train_end":str(fold["train_end"]),
        "test_start":str(fold["test_start"]),
        "test_end":str(fold["test_end"]),
        "selected_quality_intensity":chosen,
        "quality_thresholds":{
            sid:None if thresholds[sid][chosen] is None else round(float(thresholds[sid][chosen]),6)
            for sid in family["strategies"]
        },
        "variants":{},
    }
    for name,minimum in VARIANTS:
        test=mtm.mtm_portfolio(
            _filtered(rows,minimum),
            fold["test_start"],fold["test_end"],family["capacity"],
        )
        out["variants"][name]=metric(test)

    base=out["variants"]["baseline"]
    for name in ("watch_plus","strong"):
        v=out["variants"][name]
        v["delta_return_vs_baseline_pct"]=round(v["return_pct"]-base["return_pct"],2)
        v["delta_mdd_vs_baseline_pct"]=round(v["mdd_pct"]-base["mdd_pct"],2)
    return out


def _variant_summary(folds: list[dict],name: str) -> dict:
    rows=[f["variants"][name] for f in folds]
    returns=[x["return_pct"] for x in rows]
    mdds=[x["mdd_pct"] for x in rows]
    return {
        "fold_count":len(rows),
        "positive_folds":sum(x>0 for x in returns),
        "mean_test_return_pct":round(mean(returns),2) if returns else 0.0,
        "median_test_return_pct":round(median(returns),2) if returns else 0.0,
        "stitched_test_return_pct":_compound(returns),
        "worst_test_mdd_pct":round(min(mdds),2) if mdds else 0.0,
        "total_test_trades":sum(x["trades"] for x in rows),
        "mean_win_rate_pct":round(mean(x["win_rate_pct"] for x in rows),2) if rows else 0.0,
    }


def summarize(folds: list[dict]) -> dict:
    base=_variant_summary(folds,"baseline")
    variants={"baseline":base}
    for name in ("watch_plus","strong"):
        s=_variant_summary(folds,name)
        deltas=[f["variants"][name]["delta_return_vs_baseline_pct"] for f in folds]
        mdd_deltas=[f["variants"][name]["delta_mdd_vs_baseline_pct"] for f in folds]
        s.update({
            "folds_beating_baseline":sum(x>0.01 for x in deltas),
            "mean_delta_return_vs_baseline_pct":round(mean(deltas),2) if deltas else 0.0,
            "median_delta_return_vs_baseline_pct":round(median(deltas),2) if deltas else 0.0,
            "stitched_delta_vs_baseline_pct":round(s["stitched_test_return_pct"]-base["stitched_test_return_pct"],2),
            "worst_mdd_delta_vs_baseline_pct":round(min(mdd_deltas),2) if mdd_deltas else 0.0,
        })
        variants[name]=s

    fold_count=len(folds)
    viable=[]
    for name in ("watch_plus","strong"):
        s=variants[name]
        if (
            fold_count>=4
            and s["total_test_trades"]>=40
            and s["folds_beating_baseline"]>=max(2,(fold_count+1)//2)
            and s["mean_delta_return_vs_baseline_pct"]>0
            and s["stitched_delta_vs_baseline_pct"]>0
            and s["worst_mdd_delta_vs_baseline_pct"]>=-3.0
        ):
            viable.append(name)
    if viable:
        best=max(viable,key=lambda n:(variants[n]["stitched_delta_vs_baseline_pct"],variants[n]["mean_delta_return_vs_baseline_pct"]))
        pattern="supported_development_only"
    else:
        best=max(("watch_plus","strong"),key=lambda n:variants[n]["stitched_delta_vs_baseline_pct"])
        if variants[best]["total_test_trades"]<25:
            pattern="insufficient"
        elif variants[best]["stitched_delta_vs_baseline_pct"]>0 and variants[best]["folds_beating_baseline"]>=2:
            pattern="mixed_positive"
        else:
            pattern="not_supported"

    return {
        "pattern":pattern,
        "best_fixed_filter":best,
        "variants":variants,
        "selected_quality_intensity_counts":dict(Counter(f["selected_quality_intensity"] for f in folds)),
    }


def main() -> None:
    pool=json.loads(POOL.read_text(encoding="utf-8"))
    if not pool.get("ready") or int(pool.get("version") or 0)<4:
        raise SystemExit("Replay pool V4 is required")
    if int(pool.get("smart_money_features_version") or 0)<1:
        raise SystemExit("Replay pool with signal-day smart_money_flow features is required")

    candidates=[dict(x) for x in pool.get("trades") or []]
    for c in candidates:
        c["_quality"]=selection.quality_score(c)
        c["_smart_money_score"]=_smart_score(c)

    start=opt.parse_day(pool["available_start"])
    end=opt.parse_day(pool["available_end"])
    folds=wf.folds_for(start,end)
    if len(folds)<3:
        raise SystemExit("Not enough history for Smart Money rolling OOS")

    cache={}
    def executed(c):
        key=(c.get("symbol"),c.get("strategy_id"),c.get("signal_date"))
        if key not in cache:
            cache[key]=mtm.execute_candidate_mtm(c,pool,None,None)
        return cache[key]

    families=[]
    for family in selection.FAMILIES:
        fold_rows=[family_fold(family,candidates,fold,executed) for fold in folds]
        families.append({
            "id":family["id"],"name":family["name"],"strategies":family["strategies"],
            "capacity":family["capacity"],"summary":summarize(fold_rows),"folds":fold_rows,
        })

    payload={
        "version":1,"ready":True,
        "generated_at":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pool_generated_at":pool.get("generated_at"),
        "promotion_status":"development_only_no_main_picker_mutation",
        "method":{
            "type":"rolling OOS fixed-threshold Smart Money Flow diagnostic",
            "quality_selection":"existing strategy quality intensity is selected on each fold TRAIN only",
            "smart_money_thresholds":{"watch_plus_gte":WATCH_SCORE,"strong_gte":STRONG_SCORE},
            "smart_money_threshold_selection":"frozen before TEST; thresholds are not optimized on returns",
            "smart_money_formula":"same participation/absorption/liquidity score used by live Smart Money Flow Radar V1",
            "timing":"all Smart Money features use signal-day close/volume or earlier only",
            "test":"next calendar year is report-only",
            "production_main_picker_mutated":False,
            "buy_target_stop_mutated":False,
            "live_orders_mutated":False,
            "automatic_promotion":False,
            "development_warning":"current-universe replay retains survivorship bias and project history has informed hypotheses; this is development evidence, not pristine final proof",
        },
        "available_start":str(start),"available_end":str(end),
        "families":families,
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    for f in families:
        s=f["summary"]
        b=s["variants"][s["best_fixed_filter"]]
        print(f["id"],s["pattern"],s["best_fixed_filter"],"fold wins",b.get("folds_beating_baseline"),"stitched delta",b.get("stitched_delta_vs_baseline_pct"))


if __name__=="__main__":
    main()
