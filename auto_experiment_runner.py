from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from statistics import mean, median

import portfolio_volatility_diagnostic as vol
import portfolio_walkforward_research as wf
import strategy_optimizer_runner as mtm
import strategy_optimizer_v2 as opt
import strategy_selection_research as selection

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
QUEUE = STATIC / "auto_experiment_queue.json"
OUT = STATIC / "auto_experiment_results.json"
POOL = STATIC / "replay_backtest_pool_v2.json"
REGIME = STATIC / "portfolio_regime_results.json"
PRIORITY = STATIC / "portfolio_priority_audit.json"
FLOW = STATIC / "portfolio_flow_selection_diagnostic.json"

MAX_RUNS = 8
RISK_MULTIPLIERS = (1.0, 0.75, 0.5, 0.0)


def load(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def family_by_id(data: dict, family_id: str) -> dict | None:
    return next((x for x in data.get("families") or [] if x.get("id") == family_id), None)


def metric(x: dict) -> dict:
    return wf.metric(x)


def compound_return(values: list[float]) -> float:
    x = 1.0
    for v in values:
        x *= 1.0 + num(v) / 100.0
    return round((x - 1.0) * 100.0, 2)


def adjusted_rows(pairs: list[tuple[dict, dict]], multiplier: float) -> list[dict]:
    rows = []
    for c, raw in pairs:
        state = c.get("_vol_state")
        if state == "green_high_vol" and multiplier <= 0:
            continue
        row = dict(raw)
        if state == "green_high_vol":
            row["risk_fraction"] = num(row.get("risk_fraction")) * multiplier
        rows.append(row)
    return rows


def adaptive_volatility_sizing(item: dict, pool: dict) -> dict:
    family = next((x for x in selection.FAMILIES if x.get("id") == item.get("family_id")), None)
    if not family:
        return {"status": "BLOCKED", "decision": "가족 정의를 찾지 못했습니다.", "evidence": {}}

    candidates = [dict(x) for x in pool.get("trades") or [] if x.get("strategy_id") in set(family["strategies"])]
    for c in candidates:
        c["_quality"] = selection.quality_score(c)

    state_map, latest = vol.market_state_history()
    for c in candidates:
        signal_day = str(c.get("signal_date") or c.get("entry_date") or "")[:10]
        c["_vol_state"] = (state_map.get(signal_day) or {}).get("state", "unknown")

    available_start = opt.parse_day(pool["available_start"])
    available_end = opt.parse_day(pool["available_end"])
    folds = wf.folds_for(available_start, available_end)
    cache = {}

    def executed(c):
        key = (c.get("symbol"), c.get("strategy_id"), c.get("signal_date"))
        if key not in cache:
            cache[key] = mtm.execute_candidate_mtm(c, pool, None, None)
        return cache[key]

    rows = []
    for fold in folds:
        chosen_quality, _, train_base, _, pairs = vol.choose_quality_intensity(family, candidates, fold, executed)
        raw_train_trades = int(train_base.get("trades") or 0)
        variants = {}
        for mult in RISK_MULTIPLIERS:
            adjusted = adjusted_rows(pairs, mult)
            train = mtm.mtm_portfolio(adjusted, fold["train_start"], fold["train_end"], family["capacity"])
            variants[mult] = {
                "score": selection.train_pick_score(train, raw_train_trades),
                "train": train,
                "rows": adjusted,
            }
        selected_mult = max(RISK_MULTIPLIERS, key=lambda m: variants[m]["score"])
        selected_test = mtm.mtm_portfolio(
            variants[selected_mult]["rows"], fold["test_start"], fold["test_end"], family["capacity"]
        )
        baseline_test = mtm.mtm_portfolio(
            variants[1.0]["rows"], fold["test_start"], fold["test_end"], family["capacity"]
        )
        sm, bm = metric(selected_test), metric(baseline_test)
        rows.append({
            "fold": fold["id"],
            "train_start": str(fold["train_start"]),
            "train_end": str(fold["train_end"]),
            "test_start": str(fold["test_start"]),
            "test_end": str(fold["test_end"]),
            "selected_quality_intensity": chosen_quality,
            "selected_high_vol_risk_multiplier": selected_mult,
            "train_scores": {str(m): round(num(variants[m]["score"]), 4) for m in RISK_MULTIPLIERS},
            "test_experiment": sm,
            "test_baseline": bm,
            "delta_return_pct": round(sm["return_pct"] - bm["return_pct"], 2),
            "delta_mdd_pct": round(sm["mdd_pct"] - bm["mdd_pct"], 2),
        })

    exp_returns = [x["test_experiment"]["return_pct"] for x in rows]
    base_returns = [x["test_baseline"]["return_pct"] for x in rows]
    deltas = [x["delta_return_pct"] for x in rows]
    exp_mdds = [x["test_experiment"]["mdd_pct"] for x in rows]
    base_mdds = [x["test_baseline"]["mdd_pct"] for x in rows]
    counts = Counter(str(x["selected_high_vol_risk_multiplier"]) for x in rows)
    fold_count = len(rows)
    beating = sum(1 for d in deltas if d > 0.01)
    non_baseline = sum(1 for x in rows if x["selected_high_vol_risk_multiplier"] < 0.999)
    exp_stitched = compound_return(exp_returns)
    base_stitched = compound_return(base_returns)
    summary = {
        "fold_count": fold_count,
        "folds_beating_baseline": beating,
        "non_baseline_selected_folds": non_baseline,
        "mean_delta_return_pct": round(mean(deltas), 2) if deltas else 0.0,
        "median_delta_return_pct": round(median(deltas), 2) if deltas else 0.0,
        "stitched_experiment_return_pct": exp_stitched,
        "stitched_baseline_return_pct": base_stitched,
        "stitched_delta_pct": round(exp_stitched - base_stitched, 2),
        "worst_experiment_mdd_pct": round(min(exp_mdds), 2) if exp_mdds else 0.0,
        "worst_baseline_mdd_pct": round(min(base_mdds), 2) if base_mdds else 0.0,
        "selected_multiplier_counts": dict(counts),
        "latest_market_state": latest,
    }

    mdd_damage = summary["worst_experiment_mdd_pct"] - summary["worst_baseline_mdd_pct"]
    strong = (
        fold_count >= 4
        and beating >= math.ceil(fold_count * 0.67)
        and non_baseline >= 2
        and summary["mean_delta_return_pct"] > 0.5
        and summary["stitched_delta_pct"] > 2.0
        and mdd_damage >= -2.0
    )
    watch = (
        non_baseline >= 2
        and (
            (beating >= math.ceil(fold_count * 0.5) and summary["mean_delta_return_pct"] > 0)
            or mdd_damage >= 3.0
        )
    )
    if strong:
        status = "CHALLENGER_CANDIDATE"
        decision = "TRAIN에서 고른 변동성 사이징이 여러 다음 구간에서 기준을 반복 개선했습니다. 별도 Frozen Challenger 후보로 검토할 가치가 있습니다."
    elif watch:
        status = "WATCH"
        decision = "일부 다음 구간에서 개선됐지만 반복성이 승격 기준에는 부족합니다. 후속 표본을 더 모읍니다."
    else:
        status = "DROP"
        decision = "고변동 사이징 조절이 다음 구간에서 안정적으로 기준을 이기지 못했습니다. 현재 가설은 폐기합니다."

    return {
        "status": status,
        "decision": decision,
        "evidence": summary,
        "folds": rows,
        "method": {
            "type": "rolling TRAIN-selected high-volatility risk sizing",
            "risk_multipliers": list(RISK_MULTIPLIERS),
            "quality_selection": "TRAIN only",
            "risk_multiplier_selection": "TRAIN only",
            "test": "next calendar year report only",
            "production_mutation": False,
        },
    }


def evidence_regime_gate(item: dict, data: dict) -> dict:
    family = family_by_id(data, item.get("family_id"))
    s = (family or {}).get("summary") or {}
    fold_count = int(num(s.get("fold_count")))
    helped = int(num(s.get("gate_helped_folds")))
    delta_stitched = num(s.get("stitched_gated_return_pct")) - num(s.get("stitched_no_gate_return_pct"))
    mean_delta = num(s.get("mean_gate_delta_return_pct"))
    mdd_delta = num(s.get("worst_gated_mdd_pct")) - num(s.get("worst_no_gate_mdd_pct"))
    grade = str(s.get("grade") or "C")
    if grade in {"A", "B"} and fold_count >= 4 and helped >= math.ceil(fold_count * 0.6) and delta_stitched > 2 and mdd_delta >= -2:
        status = "CHALLENGER_CANDIDATE"
        decision = "장세 gate가 TRAIN-only 선택 후 여러 OOS 구간에서 반복 개선됐습니다. Frozen Challenger 후보로 검토할 가치가 있습니다."
    elif helped >= 2 and mean_delta > 0:
        status = "WATCH"
        decision = "장세 gate가 일부 OOS 구간에서 도움됐지만 반복성 또는 등급이 충분하지 않습니다."
    else:
        status = "DROP"
        decision = "장세 gate의 OOS 개선이 반복되지 않아 현재 가설은 폐기합니다."
    return {"status": status, "decision": decision, "evidence": {
        "grade": grade,
        "fold_count": fold_count,
        "gate_helped_folds": helped,
        "mean_delta_return_pct": mean_delta,
        "stitched_delta_pct": round(delta_stitched, 2),
        "worst_mdd_delta_pct": round(mdd_delta, 2),
        "selected_gate_counts": s.get("selected_gate_counts") or {},
    }}


def evidence_priority_ranker(item: dict, data: dict) -> dict:
    family = family_by_id(data, item.get("family_id"))
    s = (family or {}).get("summary") or {}
    rules = s.get("rules") or {}
    rid = (item.get("params") or {}).get("ranker") or "quality_pct"
    alt = rules.get(rid) or {}
    cur = rules.get("current") or {}
    beats = int(num(alt.get("folds_beating_current")))
    delta = num(alt.get("mean_delta_vs_current_pct"))
    mdd_delta = num(alt.get("worst_test_mdd_pct")) - num(cur.get("worst_test_mdd_pct"))
    total = int(num(alt.get("total_test_trades")))
    if beats >= 4 and delta > 1.0 and mdd_delta >= -2.0 and total >= 50:
        status = "CHALLENGER_CANDIDATE"
        decision = "대안 priority가 여러 OOS fold에서 반복 개선됐고 MDD 훼손도 제한적입니다."
    elif beats >= 3 and delta > 0:
        status = "WATCH"
        decision = "대안 priority가 일부 구간에서 낫지만 승격하기엔 반복성이 부족합니다."
    else:
        status = "DROP"
        decision = "대안 priority가 현재 방식보다 안정적으로 우월하지 않아 폐기합니다."
    return {"status": status, "decision": decision, "evidence": {
        "ranker": rid,
        "folds_beating_current": beats,
        "mean_delta_vs_current_pct": delta,
        "worst_mdd_delta_pct": round(mdd_delta, 2),
        "total_test_trades": total,
        "current_stitched_return_pct": cur.get("stitched_test_return_pct"),
        "alternative_stitched_return_pct": alt.get("stitched_test_return_pct"),
    }}


def evidence_flow_selection(item: dict, data: dict) -> dict:
    s = data.get("summary") or {}
    pattern = str(s.get("pattern") or "insufficient")
    evidence = {
        "pattern": pattern,
        "strong_minus_weak_mean_return_pp": s.get("strong_minus_weak_mean_return_pp"),
        "strong_minus_weak_win_rate_pp": s.get("strong_minus_weak_win_rate_pp"),
        "comparable_folds": s.get("comparable_folds"),
        "strong_beats_weak_folds": s.get("strong_beats_weak_folds"),
        "spearman_flow_vs_trade_return": s.get("spearman_flow_vs_trade_return"),
    }
    if pattern == "not_supported":
        return {"status": "DROP", "decision": "Flow와 이후 거래 품질의 반복 관계가 지지되지 않아 현재 가설을 폐기합니다.", "evidence": evidence}
    if pattern == "insufficient":
        return {"status": "WATCH", "decision": "비교 가능한 표본이 부족합니다. 개발용 관찰만 유지합니다.", "evidence": evidence}
    return {
        "status": "WATCH",
        "decision": "Flow 방향성은 보이지만 현재 데이터는 개발증거라 Challenger 승격을 금지하고 WATCH로 유지합니다.",
        "evidence": evidence,
    }


def short_summary(result: dict) -> str:
    e = result.get("evidence") or {}
    if "folds_beating_baseline" in e:
        return f"{e.get('folds_beating_baseline')}/{e.get('fold_count')} fold 개선 · stitched Δ {num(e.get('stitched_delta_pct')):+.2f}%p"
    if "gate_helped_folds" in e:
        return f"gate 도움 {e.get('gate_helped_folds')}/{e.get('fold_count')} · stitched Δ {num(e.get('stitched_delta_pct')):+.2f}%p"
    if "folds_beating_current" in e:
        return f"현재 priority 우위 fold {e.get('folds_beating_current')} · 평균 Δ {num(e.get('mean_delta_vs_current_pct')):+.2f}%p"
    if "pattern" in e:
        return f"Flow {e.get('pattern')} · strong-weak {num(e.get('strong_minus_weak_mean_return_pp')):+.2f}%p"
    return result.get("decision") or "실험 완료"


def counts(items):
    out = {}
    for x in items:
        s = str(x.get("status") or "QUEUED")
        out[s] = out.get(s, 0) + 1
    return out


def main():
    queue = load(QUEUE)
    if not queue.get("ready"):
        raise SystemExit("auto experiment queue not ready")
    pool = load(POOL)
    regime, priority, flow = load(REGIME), load(PRIORITY), load(FLOW)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    completed = []

    runnable = [x for x in queue.get("items") or [] if x.get("status") in {"QUEUED", "RETEST"}][:MAX_RUNS]
    for item in runnable:
        runner = item.get("runner")
        try:
            if runner == "adaptive_volatility_sizing":
                result = adaptive_volatility_sizing(item, pool)
            elif runner == "evidence_regime_gate":
                result = evidence_regime_gate(item, regime)
            elif runner == "evidence_priority_ranker":
                result = evidence_priority_ranker(item, priority)
            elif runner == "evidence_flow_selection":
                result = evidence_flow_selection(item, flow)
            else:
                result = {"status": "BLOCKED", "decision": f"지원하지 않는 runner: {runner}", "evidence": {}}
        except Exception as exc:
            result = {"status": "BLOCKED", "decision": f"실험 실행 오류: {exc}", "evidence": {}}

        item["status"] = result["status"]
        item["decision"] = result.get("decision")
        item["result_summary"] = short_summary(result)
        item["evidence"] = result.get("evidence") or {}
        item["last_run_at"] = now
        item["attempts"] = int(num(item.get("attempts"))) + 1
        completed.append({
            "id": item.get("id"),
            "key": item.get("key"),
            "kind": item.get("kind"),
            "family_id": item.get("family_id"),
            "family_name": item.get("family_name"),
            "status": item.get("status"),
            "decision": item.get("decision"),
            "result_summary": item.get("result_summary"),
            "evidence": item.get("evidence"),
            "method": result.get("method"),
            "folds": result.get("folds"),
        })

    queue["updated_at"] = now
    queue["counts"] = counts(queue.get("items") or [])
    queue["last_runner"] = {
        "ran_at": now,
        "executed": len(completed),
        "max_runs": MAX_RUNS,
        "production_mutation": False,
        "automatic_forward_spawn": False,
    }
    QUEUE.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = {
        "version": 1,
        "ready": True,
        "generated_at": now,
        "executed": len(completed),
        "results": completed,
        "queue_counts": queue["counts"],
        "policy": {
            "train_only_selection": True,
            "oos_is_report_only": True,
            "production_rule_mutation": False,
            "automatic_forward_spawn": False,
            "automatic_production_promotion": False,
            "live_broker_orders": False,
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("auto experiment runner", len(completed), payload["queue_counts"])


if __name__ == "__main__":
    main()
