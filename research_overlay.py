from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

ROOT = Path(__file__).parent
STATIC = ROOT / "static"

OPT = STATIC / "strategy_optimizer_results.json"
SELECTION = STATIC / "strategy_selection_results.json"
WALKFORWARD = STATIC / "portfolio_walkforward_results.json"
REGIME = STATIC / "portfolio_regime_results.json"


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _grade_rank(value) -> int:
    return {"A": 3, "B": 2, "C": 1}.get(str(value or ""), 0)


def _best_family(data: dict, strategy_id: str) -> dict | None:
    rows = [x for x in data.get("families") or [] if strategy_id in (x.get("strategies") or [])]
    if not rows:
        return None
    return sorted(
        rows,
        key=lambda x: (
            _grade_rank((x.get("summary") or {}).get("grade")),
            _num((x.get("summary") or {}).get("positive_fold_ratio")),
            _num((x.get("summary") or {}).get("stitched_return_pct")),
        ),
        reverse=True,
    )[0]


def _selection_family(data: dict, strategy_id: str) -> dict | None:
    return next((x for x in data.get("families") or [] if strategy_id in (x.get("strategies") or [])), None)


def _optimizer_evidence(data: dict, strategy_id: str) -> dict:
    leaders = data.get("leaders") or {}
    categories = ("balanced", "return", "defensive", "turnover")
    hits = []
    for category in categories:
        for rank, row in enumerate((leaders.get(category) or [])[:5], start=1):
            if strategy_id not in (row.get("strategies") or []):
                continue
            if not row.get("validation_pass", False):
                continue
            hits.append((category, rank, row))
    if not hits:
        return {"hits": 0, "top_balanced": False, "grade": None, "oos_return_pct": None, "oos_mdd_pct": None}
    best = sorted(hits, key=lambda x: (x[1], -_grade_rank(x[2].get("grade"))))[0][2]
    top_balanced = bool(
        (leaders.get("balanced") or [])
        and strategy_id in ((leaders.get("balanced") or [{}])[0].get("strategies") or [])
        and (leaders.get("balanced") or [{}])[0].get("validation_pass", False)
    )
    return {
        "hits": len(hits),
        "top_balanced": top_balanced,
        "grade": best.get("grade"),
        "oos_return_pct": _num((best.get("oos") or {}).get("return_pct")),
        "oos_mdd_pct": _num((best.get("oos") or {}).get("mdd_pct")),
    }


def _profile(strategy_id: str, opt: dict, selection: dict, wf: dict, regime: dict) -> dict:
    optimizer = _optimizer_evidence(opt, strategy_id)
    wf_family = _best_family(wf, strategy_id)
    wf_summary = (wf_family or {}).get("summary") or {}
    selection_family = _selection_family(selection, strategy_id)
    selected_intensity = (selection_family or {}).get("train_selected_intensity")
    regime_family = _best_family(regime, strategy_id)
    regime_summary = (regime_family or {}).get("summary") or {}

    adjustment = 0.0
    reasons: list[str] = []

    if optimizer.get("top_balanced") and _num(optimizer.get("oos_return_pct")) > 0:
        adjustment += 1.25
        reasons.append("자동탐색 균형형 선두 · OOS 통과")
    elif optimizer.get("hits", 0) >= 2 and _num(optimizer.get("oos_return_pct")) > 0:
        adjustment += 0.75
        reasons.append("자동탐색 상위권 반복 · OOS 통과")
    elif optimizer.get("hits", 0):
        adjustment += 0.25
        reasons.append("자동탐색 검증 후보")

    wf_grade = wf_summary.get("grade")
    if wf_grade == "A":
        adjustment += 0.75
        reasons.append("Walk-forward A")
    elif wf_grade == "B":
        adjustment += 0.35
        reasons.append("Walk-forward B")
    elif wf_grade == "C":
        reasons.append("Walk-forward C · 관찰")

    stitched = _num(wf_summary.get("stitched_return_pct"))
    if wf_family and stitched < 0:
        adjustment -= 0.5
        reasons.append("이어붙인 OOS 음수")

    if selected_intensity:
        intensity_label = {
            "raw": "원신호 유지",
            "loose": "TRAIN 상위 50% 엄선",
            "normal": "TRAIN 상위 30% 엄선",
            "strong": "TRAIN 상위 15% 엄선",
        }.get(selected_intensity, selected_intensity)
        reasons.append(f"품질연구 {intensity_label}")

    regime_grade = regime_summary.get("grade")
    if regime_grade in {"A", "B"}:
        reasons.append(f"장세연구 {regime_grade}")
    elif regime_grade == "C":
        reasons.append("장세연구 C · 하드게이트 미적용")

    adjustment = round(max(-1.5, min(2.0, adjustment)), 2)
    if adjustment >= 1.25:
        label, tone = "연구 우세", "lead"
    elif adjustment >= 0.5:
        label, tone = "연구 지지", "support"
    elif optimizer.get("hits") or wf_family or selection_family:
        label, tone = "연구 관찰", "watch"
    else:
        label, tone = "연구 중립", "neutral"

    return {
        "strategy_id": strategy_id,
        "label": label,
        "tone": tone,
        "score_adjustment": adjustment,
        "optimizer_hits": int(optimizer.get("hits") or 0),
        "optimizer_top_balanced": bool(optimizer.get("top_balanced")),
        "optimizer_grade": optimizer.get("grade"),
        "optimizer_oos_return_pct": optimizer.get("oos_return_pct"),
        "optimizer_oos_mdd_pct": optimizer.get("oos_mdd_pct"),
        "walkforward_family": (wf_family or {}).get("name"),
        "walkforward_grade": wf_grade,
        "walkforward_positive_folds": int(_num(wf_summary.get("positive_folds"))),
        "walkforward_fold_count": int(_num(wf_summary.get("fold_count"))),
        "walkforward_stitched_return_pct": stitched if wf_family else None,
        "selection_intensity": selected_intensity,
        "regime_grade": regime_grade,
        "summary": " · ".join(reasons[:4]) if reasons else "아직 직접 연결된 자동연구 표본이 없습니다.",
        "policy": "soft_rank_only",
    }


@lru_cache(maxsize=1)
def research_profiles() -> dict:
    opt, selection, wf, regime = _load(OPT), _load(SELECTION), _load(WALKFORWARD), _load(REGIME)
    strategy_ids = set((opt.get("strategy_names") or {}).keys())
    for source in (selection, wf, regime):
        for family in source.get("families") or []:
            strategy_ids.update(family.get("strategies") or [])
    profiles = {sid: _profile(sid, opt, selection, wf, regime) for sid in sorted(strategy_ids)}
    return {
        "ready": any(x.get("ready") for x in (opt, selection, wf, regime)),
        "generated_at": max([str(x.get("generated_at") or "") for x in (opt, selection, wf, regime)] or [""]),
        "profiles": profiles,
        "policy": {
            "mode": "soft_rank_only",
            "max_score_adjustment": 2.0,
            "hard_gate_mutated": False,
            "buy_target_stop_mutated": False,
            "automatic_production_promotion": False,
        },
    }


def overlay_for_strategy(strategy_id: str, elite_score: float | int | None = None) -> dict:
    bundle = research_profiles()
    profile = dict((bundle.get("profiles") or {}).get(strategy_id) or {
        "strategy_id": strategy_id,
        "label": "연구 중립",
        "tone": "neutral",
        "score_adjustment": 0.0,
        "summary": "아직 직접 연결된 자동연구 표본이 없습니다.",
        "policy": "soft_rank_only",
    })
    base = _num(elite_score)
    profile["base_elite_score"] = round(base, 2)
    profile["research_rank_score"] = round(max(0.0, min(99.0, base + _num(profile.get("score_adjustment")))), 2)
    profile["research_generated_at"] = bundle.get("generated_at")
    return profile
