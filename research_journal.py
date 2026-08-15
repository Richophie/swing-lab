from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
OUT = STATIC / "research_journal.json"
OPT = STATIC / "strategy_optimizer_results.json"
WF = STATIC / "portfolio_walkforward_results.json"
FR = STATIC / "forward_review.json"
SEOUL = ZoneInfo("Asia/Seoul")
MAX_HISTORY = 40


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


def grade_rank(value):
    return {"A": 3, "B": 2, "C": 1}.get(str(value or "C"), 0)


def best_walkforward(data: dict):
    rows = list(data.get("families") or [])
    if not rows:
        return None
    return sorted(
        rows,
        key=lambda row: (
            grade_rank((row.get("summary") or {}).get("grade")),
            num((row.get("summary") or {}).get("positive_fold_ratio")),
            num((row.get("summary") or {}).get("stitched_return_pct")),
        ),
        reverse=True,
    )[0]


def build_snapshot(opt: dict, wf: dict, fr: dict) -> dict:
    leader = ((opt.get("leaders") or {}).get("balanced") or [None])[0]
    best_wf = best_walkforward(wf)
    ws = (best_wf or {}).get("summary") or {}
    now = datetime.now(timezone.utc)
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "date_kst": now.astimezone(SEOUL).date().isoformat(),
        "optimizer": {
            "source_generated_at": opt.get("generated_at"),
            "tested": int(num(opt.get("tested_configurations"))),
            "validated": int(num(opt.get("validated_configurations"))),
            "leader_strategies": list((leader or {}).get("strategy_names") or []),
            "leader_strategy_ids": list((leader or {}).get("strategies") or []),
            "leader_grade": (leader or {}).get("grade"),
            "leader_oos_return_pct": round(num((leader or {}).get("oos", {}).get("return_pct")), 4),
            "leader_oos_cagr_pct": round(num((leader or {}).get("oos", {}).get("cagr_pct")), 4),
            "leader_oos_mdd_pct": round(num((leader or {}).get("oos", {}).get("mdd_pct")), 4),
            "leader_recent_cagr_pct": round(num((leader or {}).get("recent", {}).get("cagr_pct")), 4),
        },
        "walkforward": {
            "source_generated_at": wf.get("generated_at"),
            "best_family_id": (best_wf or {}).get("id"),
            "best_family_name": (best_wf or {}).get("name"),
            "grade": ws.get("grade"),
            "positive_folds": int(num(ws.get("positive_folds"))),
            "fold_count": int(num(ws.get("fold_count"))),
            "stitched_return_pct": round(num(ws.get("stitched_return_pct")), 4),
            "median_test_return_pct": round(num(ws.get("median_test_return_pct")), 4),
            "worst_fold_mdd_pct": round(num(ws.get("worst_fold_mdd_pct")), 4),
        },
        "forward": {
            "source_generated_at": fr.get("generated_at"),
            "gate": fr.get("gate"),
            "headline": fr.get("headline"),
            "minimum_closed_trades_observed": int(num(fr.get("minimum_closed_trades_observed"))),
            "minimum_closed_trades_required": int(num(fr.get("minimum_closed_trades_required"), 30)),
            "sample_progress_pct": round(num(fr.get("sample_progress_pct")), 2),
            "safety_pass": bool(fr.get("all_forward_safety_pass")),
            "automatic_promotion_enabled": bool(fr.get("automatic_promotion_enabled")),
            "live_order_submission_enabled": bool(fr.get("live_order_submission_enabled")),
            "next_action": fr.get("recommended_next_action"),
        },
    }


def pct_delta(now, prev):
    return round(num(now) - num(prev), 4)


def compare(previous: dict | None, current: dict) -> list[dict]:
    if not previous:
        return [{"kind": "baseline", "tone": "quiet", "text": "자동연구 일지의 첫 기준선을 저장했습니다."}]

    out = []
    po, co = previous.get("optimizer") or {}, current.get("optimizer") or {}
    pw, cw = previous.get("walkforward") or {}, current.get("walkforward") or {}
    pf, cf = previous.get("forward") or {}, current.get("forward") or {}

    if po.get("leader_strategy_ids") != co.get("leader_strategy_ids"):
        before = " + ".join(po.get("leader_strategies") or []) or "없음"
        after = " + ".join(co.get("leader_strategies") or []) or "없음"
        out.append({"kind": "leader", "tone": "change", "text": f"균형형 선두 조합이 {before} → {after}로 바뀌었습니다."})
    else:
        d = pct_delta(co.get("leader_oos_return_pct"), po.get("leader_oos_return_pct"))
        if abs(d) >= 0.05:
            out.append({"kind": "leader_oos", "tone": "up" if d > 0 else "down", "text": f"현재 선두의 OOS 누적수익이 이전 실행 대비 {d:+.2f}%p 변했습니다."})

    vd = int(num(co.get("validated"))) - int(num(po.get("validated")))
    if vd:
        out.append({"kind": "validated", "tone": "up" if vd > 0 else "down", "text": f"검증 통과 조합 수가 {vd:+d}개 변했습니다."})

    if pw.get("best_family_id") != cw.get("best_family_id"):
        out.append({"kind": "walkforward_family", "tone": "change", "text": f"Walk-forward 최상위 가족이 {pw.get('best_family_name') or '없음'} → {cw.get('best_family_name') or '없음'}로 바뀌었습니다."})
    if pw.get("grade") != cw.get("grade"):
        out.append({"kind": "walkforward_grade", "tone": "up" if grade_rank(cw.get("grade")) > grade_rank(pw.get("grade")) else "down", "text": f"Walk-forward 연구등급이 {pw.get('grade') or '—'} → {cw.get('grade') or '—'}로 변했습니다."})

    if pf.get("gate") != cf.get("gate"):
        out.append({"kind": "forward_gate", "tone": "change", "text": f"Forward 게이트가 {pf.get('gate') or '—'} → {cf.get('gate') or '—'}로 바뀌었습니다."})
    progress = pct_delta(cf.get("sample_progress_pct"), pf.get("sample_progress_pct"))
    if progress >= 1:
        out.append({"kind": "forward_progress", "tone": "up", "text": f"Forward 최소표본 진행률이 {progress:+.1f}%p 늘었습니다."})

    if not out:
        out.append({"kind": "stable", "tone": "quiet", "text": "지난 자동연구 실행 대비 핵심 선두·등급·Forward 게이트에 유의미한 변화가 없습니다."})
    return out


def judgement(snapshot: dict) -> dict:
    o = snapshot.get("optimizer") or {}
    w = snapshot.get("walkforward") or {}
    f = snapshot.get("forward") or {}
    gate = f.get("gate")
    grade = w.get("grade") or "C"

    if str(gate or "").startswith("BLOCKED"):
        return {
            "status": "BLOCKED",
            "headline": "성과 비교보다 안전조건 확인이 먼저입니다.",
            "next_action": f.get("next_action") or "안전조건을 복구하고 전략 규칙은 동결 유지",
        }
    if gate == "HUMAN_REVIEW_READY":
        return {
            "status": "HUMAN_REVIEW_READY",
            "headline": "미래 표본이 차서 사람 심사가 가능한 단계입니다.",
            "next_action": f.get("next_action") or "Forward 후보를 사람 검토로 비교",
        }
    if not o.get("leader_strategy_ids"):
        return {
            "status": "NO_CLEAR_LEADER",
            "headline": "검증 통과 선두가 뚜렷하지 않아 규칙을 바꾸지 않습니다.",
            "next_action": "자동연구를 계속하고 기존 실전 규칙은 동결 유지",
        }
    if grade == "C":
        return {
            "status": "REPRODUCIBILITY_WEAK",
            "headline": "백테스트 선두는 있지만 여러 다음 구간에서 재현성이 아직 약합니다.",
            "next_action": f.get("next_action") or "Forward 표본을 더 모으고 자동 승격 금지",
        }
    return {
        "status": "RESEARCH_PROMISING_FORWARD_WAIT",
        "headline": "과거·구간분할 결과는 후보 가치가 있지만 미래 표본을 더 기다립니다.",
        "next_action": f.get("next_action") or "Forward 표본 기준까지 규칙 변경 없이 관찰",
    }


def main():
    opt, wf, fr = load(OPT), load(WF), load(FR)
    if not opt.get("ready"):
        raise SystemExit("optimizer result not ready")
    if not wf.get("ready"):
        raise SystemExit("walk-forward result not ready")

    old = load(OUT, {})
    previous = old.get("current") if old else None
    current = build_snapshot(opt, wf, fr)
    changes = compare(previous, current)
    history = list(old.get("history") or [])
    if previous:
        history.append(previous)
    history = history[-MAX_HISTORY:]

    payload = {
        "version": 1,
        "generated_at": current["generated_at"],
        "current": current,
        "judgement": judgement(current),
        "changes": changes,
        "history": history,
        "policy": {
            "research_can_change": True,
            "production_auto_mutation": False,
            "automatic_promotion": False,
            "live_broker_orders": False,
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "date_kst": current["date_kst"],
        "status": payload["judgement"]["status"],
        "changes": [x["text"] for x in changes],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
