from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path

import strategy_optimizer_runner as mtm
import strategy_optimizer_v2 as opt

POOL = Path("static/replay_backtest_pool_v2.json")
OUT = Path("static/strategy_selection_results.json")

FAMILIES = [
    {
        "id": "donchian_core",
        "name": "Donchian 단독",
        "strategies": ["donchian_55"],
        "capacity": 10,
    },
    {
        "id": "donchian_momentum",
        "name": "Donchian + 모멘텀",
        "strategies": ["momentum_pullback", "donchian_55"],
        "capacity": 10,
    },
    {
        "id": "confirmed_sma_donchian",
        "name": "확인형 + SMA200·20 + Donchian",
        "strategies": ["confirmed_pullback", "sma200_20_squeeze", "donchian_55"],
        "capacity": 10,
    },
]

INTENSITIES = [
    ("raw", "원신호", 1.00),
    ("loose", "느슨한 엄선 · 상위 50%", 0.50),
    ("normal", "일반 엄선 · 상위 30%", 0.30),
    ("strong", "강한 엄선 · 상위 15%", 0.15),
]


def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, opt.num(v)))


def quality_score(c: dict) -> float:
    """Fixed ex-ante quality score. No future return or OOS metric is used."""
    sid = c.get("strategy_id")
    q = c.get("quality_features") or {}

    if sid in {"confirmed_pullback", "momentum_pullback", "rsi2_trend_reversion"}:
        elite = clamp((opt.num(c.get("elite_score")) - 70.0) / 25.0)
        rr = clamp((opt.num(c.get("net_risk_reward")) - 1.0) / 2.0)
        market = {"좋음": 1.0, "중립": 0.65, "조심": 0.25}.get(str(c.get("market_state")), 0.60)
        return 100.0 * (0.65 * elite + 0.25 * rr + 0.10 * market)

    if sid == "sma200_20_squeeze":
        body = clamp((opt.num(q.get("body_atr")) - 0.70) / 1.30)
        tight = 1.0 - clamp(opt.num(q.get("ma_spread_pct")) / 0.035)
        volume = clamp((opt.num(q.get("volume_ratio")) - 0.75) / 1.75)
        clearance = clamp(opt.num(q.get("ma_clearance_atr")) / 1.50)
        slope = clamp(opt.num(q.get("sma200_slope_20d_pct")) / 0.08)
        clean_crosses = 1.0 - clamp(opt.num(q.get("crosses_30")) / 2.0)
        return 100.0 * (
            0.25 * body + 0.20 * tight + 0.15 * volume
            + 0.15 * clearance + 0.15 * slope + 0.10 * clean_crosses
        )

    if sid in {"donchian_55", "breakout_20d", "volume_breakout"}:
        breakout = clamp(opt.num(q.get("breakout_atr")) / 1.50)
        volume = clamp((opt.num(q.get("volume_ratio")) - 0.70) / 2.30)
        close_pos = clamp((opt.num(q.get("close_position")) - 0.50) / 0.50)
        slope = clamp(opt.num(q.get("sma200_slope_20d_pct")) / 0.08)
        body = clamp(opt.num(q.get("body_atr")) / 1.50)
        return 100.0 * (0.30 * breakout + 0.20 * volume + 0.20 * close_pos + 0.15 * slope + 0.15 * body)

    elite = clamp((opt.num(c.get("elite_score")) - 70.0) / 25.0)
    rr = clamp((opt.num(c.get("net_risk_reward")) - 1.0) / 2.0)
    return 100.0 * (0.70 * elite + 0.30 * rr)


def quantile(values: list[float], q: float) -> float:
    if not values:
        return float("inf")
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = clamp(q) * (len(xs) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    w = pos - lo
    return xs[lo] * (1.0 - w) + xs[hi] * w


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


def train_pick_score(x: dict, raw_trades: int) -> float:
    if x["trades"] < max(18, int(raw_trades * 0.25)) or x["cagr"] <= 0:
        return -1e9
    # The filter is allowed to be chosen on TRAIN only. OOS never enters this score.
    coverage = x["trades"] / max(1, raw_trades)
    return x["cagr"] * 100.0 - abs(x["mdd"] * 100.0) * 0.55 + min(1.0, coverage) * 2.0


def main():
    pool = json.loads(POOL.read_text(encoding="utf-8"))
    if not pool.get("ready") or int(pool.get("version") or 0) < 4:
        raise SystemExit("Replay pool V4 with signal-day quality_features is required")

    candidates = list(pool.get("trades") or [])
    available_start = opt.parse_day(pool["available_start"])
    available_end = opt.parse_day(pool["available_end"])
    total_days = (available_end - available_start).days
    train_end = available_start.fromordinal(available_start.toordinal() + int(total_days * 0.70))
    oos_start = train_end.fromordinal(train_end.toordinal() + 1)
    recent_start = available_end.fromordinal(available_end.toordinal() - min(730, total_days))

    for c in candidates:
        c["_quality"] = quality_score(c)

    strategy_thresholds = {}
    for sid in sorted({c.get("strategy_id") for c in candidates if c.get("strategy_id")}):
        train_scores = [
            c["_quality"] for c in candidates
            if c.get("strategy_id") == sid and available_start <= opt.parse_day(c["entry_date"]) <= train_end
        ]
        strategy_thresholds[sid] = {
            intensity: None if keep >= 1 else round(quantile(train_scores, 1.0 - keep), 6)
            for intensity, _, keep in INTENSITIES
        }

    exec_cache = {}
    def executed(c):
        key = (c.get("symbol"), c.get("strategy_id"), c.get("signal_date"))
        if key not in exec_cache:
            exec_cache[key] = mtm.execute_candidate_mtm(c, pool, None, None)
        return exec_cache[key]

    family_results = []
    for family in FAMILIES:
        family_raw = [c for c in candidates if c.get("strategy_id") in set(family["strategies"])]
        variants = []
        raw_train_trades = 0
        train_objects = {}

        for intensity, label, keep in INTENSITIES:
            filtered = []
            for c in family_raw:
                threshold = strategy_thresholds[c["strategy_id"]][intensity]
                if threshold is None or c["_quality"] >= threshold:
                    row = executed(c)
                    if row:
                        filtered.append(row)

            train = mtm.mtm_portfolio(filtered, available_start, train_end, family["capacity"])
            oos = mtm.mtm_portfolio(filtered, oos_start, available_end, family["capacity"])
            recent = mtm.mtm_portfolio(filtered, recent_start, available_end, family["capacity"])
            full = mtm.mtm_portfolio(filtered, available_start, available_end, family["capacity"])
            if intensity == "raw":
                raw_train_trades = train["trades"]
            train_objects[intensity] = train
            variants.append({
                "intensity": intensity,
                "label": label,
                "keep_fraction": keep,
                "thresholds": {
                    sid: strategy_thresholds[sid][intensity] for sid in family["strategies"]
                },
                "train": metric(train),
                "oos": metric(oos),
                "recent": metric(recent),
                "full": metric(full),
            })

        picked = max(
            INTENSITIES,
            key=lambda item: train_pick_score(train_objects[item[0]], raw_train_trades),
        )[0]
        for variant in variants:
            variant["train_pick"] = variant["intensity"] == picked

        family_results.append({
            **family,
            "train_selected_intensity": picked,
            "variants": variants,
        })

    payload = {
        "version": 1,
        "ready": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pool_generated_at": pool.get("generated_at"),
        "promotion_status": "research_only",
        "method": {
            "quality_score": "fixed ex-ante strategy-specific formula; signal-day data only",
            "thresholds": "within-strategy percentiles calculated on TRAIN candidate distribution only",
            "intensities": [
                {"id": i, "label": label, "keep_fraction": keep}
                for i, label, keep in INTENSITIES
            ],
            "selection": "TRAIN-only risk-adjusted pick; OOS and recent are report-only validation and never rerank",
            "equity": "daily_close_mark_to_market",
        },
        "validation": {
            "available_start": str(available_start),
            "train_end": str(train_end),
            "oos_start": str(oos_start),
            "recent_start": str(recent_start),
            "available_end": str(available_end),
        },
        "families": family_results,
        "notes": [
            "엄선은 전략마다 다른 신호일 품질 feature를 사용하며 미래 수익률을 품질점수에 넣지 않습니다.",
            "상위 50/30/15% 임계값은 TRAIN의 신호 분포에서만 정하고 OOS에는 그대로 고정합니다.",
            "TRAIN 선택 결과가 OOS에서 나빠지면 엄선 가설을 폐기하거나 약화해야 하며 OOS에 맞춰 컷을 다시 조정하지 않습니다.",
            "현재 후보풀은 여전히 현재 유동성 종목을 과거로 되감아 survivorship bias가 남아 있습니다.",
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("families", len(family_results), "candidates", len(candidates), "executed", len(exec_cache))
    for f in family_results:
        picked = next(v for v in f["variants"] if v["train_pick"])
        print(f["id"], "train_pick", picked["intensity"], "OOS", picked["oos"]["return_pct"], "MDD", picked["oos"]["mdd_pct"])


if __name__ == "__main__":
    main()
