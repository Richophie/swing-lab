from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

STATIC = Path(__file__).parent / "static"
FLOW_DIAG = STATIC / "portfolio_flow_selection_diagnostic.json"

def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)

def _clip(value, lo=0.0, hi=100.0):
    return max(lo, min(hi, float(value)))

def _load(path: Path) -> dict:
    try:
        data=json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data,dict) else {}
    except Exception:
        return {}

def score_live_flow(flow: dict | None) -> dict:
    """Research-only proxy for abnormal large-money participation.

    This deliberately does NOT claim to identify a named institution or buyer.
    It scores observable price/volume behavior already available to Swing Lab.
    """
    f=flow or {}
    rv=_num(f.get("relative_volume"),1)
    v5=_num(f.get("volume_5d_vs_20d"),1)
    rev=_num(f.get("reversal_volume"),0)
    ud=_num(f.get("up_down_volume_ratio"),1)
    dv=_num(f.get("avg_dollar_volume_20d"),0)

    participation=_clip(50 + (rv-1)*28 + (v5-1)*18)
    absorption=_clip(50 + (rev-1)*30 + (ud-1)*24)
    liquidity=_clip(25 + min(75, dv/1_000_000))

    score=round(_clip(participation*.45 + absorption*.35 + liquidity*.20),1)
    if score>=75:
        label,tone="큰돈 흔적 강함","strong"
    elif score>=62:
        label,tone="큰돈 흔적 관찰","watch"
    else:
        label,tone="특이 수급 약함","neutral"

    clues=[]
    if rv>=1.8: clues.append(f"상대거래량 {rv:.1f}배")
    if v5>=1.35: clues.append(f"5일 거래량이 20일 평균 대비 {v5:.1f}배")
    if rev>=1.15: clues.append("반전 구간 거래량 증가")
    if ud>=1.25: clues.append("상승일 거래량 우위")
    if dv>=50_000_000: clues.append("기관 참여가 가능한 유동성")

    return {
        "score":score,"label":label,"tone":tone,
        "components":{"participation":round(participation,1),"absorption":round(absorption,1),"liquidity":round(liquidity,1)},
        "clues":clues[:4],
        "interpretation":"공개 가격·거래량에서 비정상적 대형자금 참여 가능성을 보는 연구용 프록시입니다. 특정 기관의 실제 매수로 단정하지 않습니다.",
    }

def research_context() -> dict:
    d=_load(FLOW_DIAG)
    s=d.get("summary") or {}
    return {
        "ready":bool(d.get("ready")),
        "pattern":s.get("pattern"),
        "strong_minus_weak_mean_return_pp":s.get("strong_minus_weak_mean_return_pp"),
        "comparable_folds":s.get("comparable_folds"),
        "strong_beats_weak_folds":s.get("strong_beats_weak_folds"),
        "policy":"research_only_no_rank_mutation",
    }

def attach(row: dict) -> dict:
    row=dict(row)
    row["smart_money_flow"]=score_live_flow(row.get("flow"))
    row["smart_money_flow"]["research_context"]=research_context()
    return row
