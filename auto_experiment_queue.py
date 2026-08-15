from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
OUT = STATIC / "auto_experiment_queue.json"
WF = STATIC / "portfolio_walkforward_results.json"
REGIME = STATIC / "portfolio_regime_results.json"
VOL = STATIC / "portfolio_volatility_diagnostic.json"
PRIORITY = STATIC / "portfolio_priority_audit.json"
FLOW = STATIC / "portfolio_flow_selection_diagnostic.json"

MAX_ACTIVE = 12
MAX_HISTORY = 80
TERMINAL = {"DROP", "WATCH", "CHALLENGER_CANDIDATE", "BLOCKED"}


def load(path: Path, default=None):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except Exception:
        return {} if default is None else default


def num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def stamp(*parts) -> str:
    raw = "|".join(str(x or "") for x in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def family_map(data: dict) -> dict:
    return {str(x.get("id")): x for x in data.get("families") or [] if x.get("id")}


def proposal(kind: str, runner: str, family: dict | None, priority: int, hypothesis: str, why_now: str, test_plan: str, source_fingerprint: str, params=None) -> dict:
    family = family or {}
    family_id = family.get("id")
    key = f"{kind}:{family_id or 'global'}"
    return {
        "key": key,
        "id": f"exp-{stamp(key)}",
        "kind": kind,
        "runner": runner,
        "family_id": family_id,
        "family_name": family.get("name"),
        "strategies": list(family.get("strategies") or []),
        "priority": int(max(0, min(100, priority))),
        "hypothesis": hypothesis,
        "why_now": why_now,
        "test_plan": test_plan,
        "params": dict(params or {}),
        "source_fingerprint": source_fingerprint,
        "status": "QUEUED",
        "decision": None,
        "result_summary": None,
    }


def generate(walkforward: dict, regime: dict, volatility: dict, priority: dict, flow: dict) -> list[dict]:
    out = []
    wf_map = family_map(walkforward)
    reg_map = family_map(regime)
    vol_map = family_map(volatility)
    pri_map = family_map(priority)

    for family_id, family in wf_map.items():
        s = family.get("summary") or {}
        grade = str(s.get("grade") or "C")
        vf = vol_map.get(family_id) or {}
        vs = vf.get("summary") or {}
        pattern = str(vs.get("green_high_vol_drag_pattern") or "weak")
        if grade != "C" and pattern == "weak":
            continue
        bump = {"strong": 12, "mixed": 7, "weak": 0}.get(pattern, 0)
        priority_score = 82 + bump + (5 if grade == "C" else 0)
        fp = stamp(walkforward.get("generated_at"), volatility.get("generated_at"), family_id, grade, pattern)
        out.append(proposal(
            "adaptive_volatility_sizing",
            "adaptive_volatility_sizing",
            family,
            priority_score,
            f"{family.get('name')}의 고변동 구간 노출을 TRAIN에서만 조절하면 다음 구간 재현성이 개선되는가?",
            f"Walk-forward {grade}등급 · 플러스 구간 {int(num(s.get('positive_folds')))}/{int(num(s.get('fold_count')))} · 고변동 drag 패턴 {pattern}.",
            "각 rolling fold의 TRAIN에서 고변동 risk 배수 1.0/0.75/0.5/0.0 중 하나를 선택하고, 고정한 배수를 다음 해 TEST에 그대로 적용해 기존 1.0과 비교합니다.",
            fp,
            {"risk_multipliers": [1.0, 0.75, 0.5, 0.0], "trigger_grade": grade, "vol_pattern": pattern},
        ))

    for family_id, family in reg_map.items():
        s = family.get("summary") or {}
        fold_count = int(num(s.get("fold_count")))
        helped = int(num(s.get("gate_helped_folds")))
        mean_delta = num(s.get("mean_gate_delta_return_pct"))
        if fold_count <= 0:
            continue
        priority_score = 62 + min(15, helped * 3) + (8 if mean_delta > 0 else 0)
        fp = stamp(regime.get("generated_at"), family_id, s.get("grade"), helped, mean_delta)
        out.append(proposal(
            "regime_gate_review",
            "evidence_regime_gate",
            family,
            priority_score,
            f"{family.get('name')}에서 시장 장세 gate를 켜는 것이 항상 켜기보다 OOS 성과를 반복 개선하는가?",
            f"TRAIN-only gate가 TEST {helped}/{fold_count}구간에서 기준보다 나았고 평균 수익 차이는 {mean_delta:+.2f}%p입니다.",
            "이미 계산된 rolling OOS regime 연구를 자동 판독합니다. TEST를 보고 같은 fold의 gate를 다시 조정하지 않습니다.",
            fp,
        ))

    for family_id, family in pri_map.items():
        s = family.get("summary") or {}
        rules = s.get("rules") or {}
        alts = []
        for rid in ("quality_pct", "hybrid_50"):
            r = rules.get(rid) or {}
            alts.append((rid, num(r.get("mean_delta_vs_current_pct")), int(num(r.get("folds_beating_current")))))
        rid, delta, beats = max(alts, key=lambda x: (x[1], x[2])) if alts else ("quality_pct", 0.0, 0)
        slot = s.get("current_slot_audit") or {}
        rejected5 = int(num(slot.get("capacity_rejected_plus5")))
        if abs(delta) < 0.15 and rejected5 == 0:
            continue
        priority_score = 55 + min(18, max(0, beats) * 3) + min(10, rejected5)
        fp = stamp(priority.get("generated_at"), family_id, rid, delta, beats, rejected5)
        out.append(proposal(
            "priority_ranker_review",
            "evidence_priority_ranker",
            family,
            priority_score,
            f"{family.get('name')}의 동시신호 경쟁에서 {rid} 우선순위가 현재 priority보다 다음 구간 성과를 개선하는가?",
            f"대안 ranker의 평균 TEST 차이 {delta:+.2f}%p · 현재보다 우수한 fold {beats}회 · 슬롯 탈락 후 +5% 후보 {rejected5}건.",
            "TRAIN 분포로 만든 품질 백분위/혼합 ranker의 rolling OOS 결과를 현재 priority와 비교하고, 반복성·MDD·표본을 함께 판정합니다.",
            fp,
            {"ranker": rid},
        ))

    fs = flow.get("summary") or {}
    if flow.get("ready"):
        pattern = str(fs.get("pattern") or "insufficient")
        delta = num(fs.get("strong_minus_weak_mean_return_pp"))
        comparable = int(num(fs.get("comparable_folds")))
        beats = int(num(fs.get("strong_beats_weak_folds")))
        family = flow.get("family") or {}
        priority_score = 45 + (12 if pattern == "repeats_but_development_only" else 5 if pattern == "mixed_positive" else 0)
        fp = stamp(flow.get("generated_at"), pattern, delta, comparable, beats)
        out.append(proposal(
            "flow_selection_review",
            "evidence_flow_selection",
            family,
            priority_score,
            "신호일의 섹터 Flow가 강한 후보를 우선하는 것이 이후 거래 품질과 반복적으로 연결되는가?",
            f"Flow 패턴 {pattern} · strong-weak 평균수익 차이 {delta:+.2f}%p · 비교가능 fold {comparable}개 중 strong 우위 {beats}개.",
            "Flow는 현재 개발증거이므로 결과가 좋아도 자동 Challenger 승격은 금지하고 WATCH까지만 허용합니다.",
            fp,
        ))

    return sorted(out, key=lambda x: (-x["priority"], x["key"]))[:MAX_ACTIVE]


def merge_previous(proposals: list[dict], old: dict, now: str) -> tuple[list[dict], list[dict]]:
    previous = {x.get("key"): x for x in old.get("items") or [] if x.get("key")}
    active = []
    seen = set()
    for item in proposals:
        seen.add(item["key"])
        prev = previous.get(item["key"]) or {}
        item["created_at"] = prev.get("created_at") or now
        item["updated_at"] = now
        item["attempts"] = int(num(prev.get("attempts")))
        if prev and prev.get("source_fingerprint") == item.get("source_fingerprint") and prev.get("status") in TERMINAL:
            for key in ("status", "decision", "result_summary", "last_run_at", "attempts", "evidence"):
                if key in prev:
                    item[key] = prev.get(key)
        elif prev:
            item["status"] = "RETEST"
        active.append(item)

    history = list(old.get("history") or [])
    for key, prev in previous.items():
        if key in seen:
            continue
        retired = dict(prev)
        retired["retired_at"] = now
        retired["retired_reason"] = "현재 진단에서 더 이상 실험 트리거가 유지되지 않음"
        history.append(retired)
    return active, history[-MAX_HISTORY:]


def counts(items: list[dict]) -> dict:
    states = {}
    for x in items:
        s = str(x.get("status") or "QUEUED")
        states[s] = states.get(s, 0) + 1
    return states


def main():
    sources = {
        "walkforward": load(WF),
        "regime": load(REGIME),
        "volatility": load(VOL),
        "priority": load(PRIORITY),
        "flow": load(FLOW),
    }
    if not sources["walkforward"].get("ready"):
        raise SystemExit("walk-forward result not ready")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    old = load(OUT, {})
    proposals = generate(**sources)
    items, history = merge_previous(proposals, old, now)
    payload = {
        "version": 1,
        "ready": True,
        "generated_at": now,
        "items": items,
        "counts": counts(items),
        "history": history,
        "source_generated_at": {k: v.get("generated_at") for k, v in sources.items()},
        "policy": {
            "automatic_hypothesis_generation": True,
            "max_active_experiments": MAX_ACTIVE,
            "production_rule_mutation": False,
            "buy_target_stop_mutation": False,
            "automatic_forward_spawn": False,
            "automatic_production_promotion": False,
            "live_broker_orders": False,
            "terminal_states": sorted(TERMINAL),
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("auto experiment queue", payload["counts"], "active", len(items))


if __name__ == "__main__":
    main()
