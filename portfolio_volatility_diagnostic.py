from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
from statistics import mean, median

import numpy as np
import pandas as pd

from market_data import indicators, load_price_history
import portfolio_walkforward_research as wf
import strategy_optimizer_runner as mtm
import strategy_optimizer_v2 as opt
import strategy_selection_research as selection

POOL = Path("static/replay_backtest_pool_v2.json")
OUT = Path("static/portfolio_volatility_diagnostic.json")
VOL_WINDOW = 20
VOL_RANK_WINDOW = 252
VOL_LOW_CUTOFF = 1.0 / 3.0
VOL_HIGH_CUTOFF = 2.0 / 3.0
MIN_COMPARABLE_TRADES = 5

STATE_ORDER = [
    "green_low_vol",
    "green_mid_vol",
    "green_high_vol",
    "mixed",
    "risk_off",
    "unknown",
]
STATE_LABELS = {
    "green_low_vol": "초록 · 저변동",
    "green_mid_vol": "초록 · 보통변동",
    "green_high_vol": "초록 · 고변동",
    "mixed": "혼조 · SPY/QQQ 장기추세 불일치",
    "risk_off": "하락 · SPY/QQQ 모두 200일선 아래",
    "unknown": "확인불가",
}


def classify_snapshot(spy_close, spy_sma200, qqq_close, qqq_sma200, spy_vol_pct) -> str:
    trend_vals = (spy_close, spy_sma200, qqq_close, qqq_sma200)
    if any(pd.isna(x) for x in trend_vals):
        return "unknown"
    spy_up = float(spy_close) > float(spy_sma200)
    qqq_up = float(qqq_close) > float(qqq_sma200)
    if not spy_up and not qqq_up:
        return "risk_off"
    if spy_up != qqq_up:
        return "mixed"
    if pd.isna(spy_vol_pct):
        return "unknown"
    p = float(spy_vol_pct)
    if p <= VOL_LOW_CUTOFF:
        return "green_low_vol"
    if p >= VOL_HIGH_CUTOFF:
        return "green_high_vol"
    return "green_mid_vol"


def trailing_percentile(series: pd.Series, window: int = VOL_RANK_WINDOW) -> pd.Series:
    """Percentile of today's value versus trailing history including today; no future rows."""
    def rank_last(x):
        s = pd.Series(x)
        return float(s.rank(pct=True).iloc[-1])
    return series.rolling(window, min_periods=100).apply(rank_last, raw=False)


def market_state_history() -> tuple[dict[str, dict], dict]:
    spy = load_price_history("SPY", "10y").copy()
    qqq = load_price_history("QQQ", "10y").copy()
    spy_ind = indicators(spy)
    qqq_ind = indicators(qqq)

    spy_close = spy_ind["close"].astype(float)
    spy_ret = spy_close.pct_change()
    spy_rv20 = spy_ret.rolling(VOL_WINDOW).std() * np.sqrt(252.0)
    spy_vol_pct = trailing_percentile(spy_rv20)

    frame = pd.DataFrame(
        {
            "spy_close": spy_ind["close"],
            "spy_sma200": spy_ind["sma200"],
            "spy_rv20": spy_rv20,
            "spy_vol_pct": spy_vol_pct,
        },
        index=spy_ind.index,
    ).join(
        pd.DataFrame(
            {"qqq_close": qqq_ind["close"], "qqq_sma200": qqq_ind["sma200"]},
            index=qqq_ind.index,
        ),
        how="outer",
    ).sort_index().ffill()

    mapping = {}
    for idx, r in frame.iterrows():
        day = str(pd.Timestamp(idx).date())
        mapping[day] = {
            "state": classify_snapshot(
                r.get("spy_close"), r.get("spy_sma200"), r.get("qqq_close"), r.get("qqq_sma200"), r.get("spy_vol_pct")
            ),
            "spy_rv20": None if pd.isna(r.get("spy_rv20")) else round(float(r["spy_rv20"]), 6),
            "spy_vol_pct": None if pd.isna(r.get("spy_vol_pct")) else round(float(r["spy_vol_pct"]), 6),
        }

    latest = {}
    if len(frame):
        r = frame.iloc[-1]
        latest = {
            "date": str(pd.Timestamp(frame.index[-1]).date()),
            "state": classify_snapshot(
                r.get("spy_close"), r.get("spy_sma200"), r.get("qqq_close"), r.get("qqq_sma200"), r.get("spy_vol_pct")
            ),
            "label": STATE_LABELS[classify_snapshot(
                r.get("spy_close"), r.get("spy_sma200"), r.get("qqq_close"), r.get("qqq_sma200"), r.get("spy_vol_pct")
            )],
            "spy_close": None if pd.isna(r.get("spy_close")) else round(float(r["spy_close"]), 4),
            "spy_sma200": None if pd.isna(r.get("spy_sma200")) else round(float(r["spy_sma200"]), 4),
            "qqq_close": None if pd.isna(r.get("qqq_close")) else round(float(r["qqq_close"]), 4),
            "qqq_sma200": None if pd.isna(r.get("qqq_sma200")) else round(float(r["qqq_sma200"]), 4),
            "spy_rv20_pct": None if pd.isna(r.get("spy_rv20")) else round(float(r["spy_rv20"]) * 100.0, 2),
            "spy_vol_percentile": None if pd.isna(r.get("spy_vol_pct")) else round(float(r["spy_vol_pct"]) * 100.0, 1),
        }
    return mapping, latest


def trade_stats(rows: list[dict]) -> dict:
    changes = [float(r.get("change") or 0.0) * 100.0 for r in rows]
    return {
        "signals": len(rows),
        "win_rate_pct": round(sum(1 for x in changes if x > 0) / len(changes) * 100.0, 2) if changes else 0.0,
        "avg_trade_pct": round(mean(changes), 3) if changes else 0.0,
        "median_trade_pct": round(median(changes), 3) if changes else 0.0,
    }


def metric(x: dict) -> dict:
    return wf.metric(x)


def choose_quality_intensity(family: dict, candidates: list[dict], fold: dict, executed):
    thresholds = wf.thresholds_for(candidates, family["strategies"], fold["train_start"], fold["train_end"])
    allowed = set(family["strategies"])
    pairs = []
    for c in candidates:
        if c.get("strategy_id") not in allowed:
            continue
        row = executed(c)
        if row:
            pairs.append((c, row))

    raw_rows = [row for _, row in pairs]
    raw_train = mtm.mtm_portfolio(raw_rows, fold["train_start"], fold["train_end"], family["capacity"])
    raw_train_trades = int(raw_train["trades"])

    train_objects = {}
    rows_by_intensity = {}
    pairs_by_intensity = {}
    for intensity, _, _ in selection.INTENSITIES:
        kept_pairs = []
        for c, row in pairs:
            threshold = thresholds[c["strategy_id"]][intensity]
            if threshold is None or c["_quality"] >= threshold:
                kept_pairs.append((c, row))
        kept_rows = [row for _, row in kept_pairs]
        rows_by_intensity[intensity] = kept_rows
        pairs_by_intensity[intensity] = kept_pairs
        train_objects[intensity] = mtm.mtm_portfolio(
            kept_rows, fold["train_start"], fold["train_end"], family["capacity"]
        )

    chosen = max(
        selection.INTENSITIES,
        key=lambda x: selection.train_pick_score(train_objects[x[0]], raw_train_trades),
    )[0]
    return chosen, thresholds, train_objects[chosen], rows_by_intensity[chosen], pairs_by_intensity[chosen]


def state_breakdown(
    pairs: list[tuple[dict, dict]],
    start: date,
    end: date,
    capacity: int,
) -> dict:
    out = {}
    for state in STATE_ORDER:
        rows = []
        for c, row in pairs:
            d = opt.parse_day(c.get("entry_date") or c.get("signal_date"))
            if start <= d <= end and c.get("_vol_state", "unknown") == state:
                rows.append(row)
        sleeve = mtm.mtm_portfolio(rows, start, end, capacity)
        out[state] = {
            "label": STATE_LABELS[state],
            "trade_stats": trade_stats(rows),
            "state_only_sleeve": metric(sleeve),
        }
    return out


def family_fold(family: dict, candidates: list[dict], fold: dict, executed) -> dict:
    chosen, thresholds, train, rows, pairs = choose_quality_intensity(family, candidates, fold, executed)
    full_test = mtm.mtm_portfolio(rows, fold["test_start"], fold["test_end"], family["capacity"])
    intensity_label = next(x[1] for x in selection.INTENSITIES if x[0] == chosen)
    return {
        "fold": fold["id"],
        "train_start": str(fold["train_start"]),
        "train_end": str(fold["train_end"]),
        "test_start": str(fold["test_start"]),
        "test_end": str(fold["test_end"]),
        "selected_intensity": chosen,
        "selected_intensity_label": intensity_label,
        "thresholds": {
            sid: None if thresholds[sid][chosen] is None else round(float(thresholds[sid][chosen]), 6)
            for sid in family["strategies"]
        },
        "train": metric(train),
        "test_full_no_market_filter": metric(full_test),
        "states": state_breakdown(pairs, fold["test_start"], fold["test_end"], family["capacity"]),
    }


def summarize_state(folds: list[dict], state: str) -> dict:
    points = [f["states"][state] for f in folds]
    avgs = [p["trade_stats"]["avg_trade_pct"] for p in points if p["trade_stats"]["signals"] > 0]
    sleeve_returns = [p["state_only_sleeve"]["return_pct"] for p in points]
    compound = 1.0
    for value in sleeve_returns:
        compound *= 1.0 + value / 100.0
    return {
        "label": STATE_LABELS[state],
        "folds_with_signals": sum(1 for p in points if p["trade_stats"]["signals"] > 0),
        "total_signals": sum(p["trade_stats"]["signals"] for p in points),
        "positive_avg_trade_folds": sum(1 for x in avgs if x > 0),
        "median_avg_trade_pct": round(median(avgs), 3) if avgs else 0.0,
        "mean_avg_trade_pct": round(mean(avgs), 3) if avgs else 0.0,
        "median_state_sleeve_return_pct": round(median(sleeve_returns), 2) if sleeve_returns else 0.0,
        "stitched_state_sleeve_return_pct": round((compound - 1.0) * 100.0, 2),
        "worst_state_sleeve_mdd_pct": round(
            min((p["state_only_sleeve"]["mdd_pct"] for p in points), default=0.0), 2
        ),
    }


def summarize(folds: list[dict]) -> dict:
    full_returns = [f["test_full_no_market_filter"]["return_pct"] for f in folds]
    full_compound = 1.0
    for value in full_returns:
        full_compound *= 1.0 + value / 100.0
    states = {state: summarize_state(folds, state) for state in STATE_ORDER}

    comparable = 0
    high_worse_low = 0
    high_worse_mid = 0
    for fold in folds:
        high = fold["states"]["green_high_vol"]["trade_stats"]
        mid = fold["states"]["green_mid_vol"]["trade_stats"]
        low = fold["states"]["green_low_vol"]["trade_stats"]
        if high["signals"] >= MIN_COMPARABLE_TRADES and low["signals"] >= MIN_COMPARABLE_TRADES:
            comparable += 1
            high_worse_low += int(high["avg_trade_pct"] < low["avg_trade_pct"])
        if high["signals"] >= MIN_COMPARABLE_TRADES and mid["signals"] >= MIN_COMPARABLE_TRADES:
            high_worse_mid += int(high["avg_trade_pct"] < mid["avg_trade_pct"])

    high_med = states["green_high_vol"]["median_avg_trade_pct"]
    low_med = states["green_low_vol"]["median_avg_trade_pct"]
    if comparable >= 3 and high_worse_low / comparable >= 0.67 and high_med < low_med:
        pattern = "strong"
    elif comparable >= 2 and high_worse_low / comparable >= 0.50 and high_med < low_med:
        pattern = "mixed"
    else:
        pattern = "weak"

    return {
        "fold_count": len(folds),
        "stitched_full_no_market_filter_return_pct": round((full_compound - 1.0) * 100.0, 2),
        "median_full_test_return_pct": round(median(full_returns), 2) if full_returns else 0.0,
        "states": states,
        "green_high_vs_low_comparable_folds": comparable,
        "green_high_worse_than_low_folds": high_worse_low,
        "green_high_worse_than_mid_folds": high_worse_mid,
        "green_high_vol_drag_pattern": pattern,
    }


def main() -> None:
    pool = json.loads(POOL.read_text(encoding="utf-8"))
    if not pool.get("ready") or int(pool.get("version") or 0) < 4:
        raise SystemExit("Replay pool V4 is required")

    candidates = list(pool.get("trades") or [])
    for c in candidates:
        c["_quality"] = selection.quality_score(c)

    state_map, latest = market_state_history()
    for c in candidates:
        signal_day = str(c.get("signal_date") or c.get("entry_date") or "")[:10]
        snap = state_map.get(signal_day) or {"state": "unknown"}
        c["_vol_state"] = snap.get("state", "unknown")
        c["_spy_vol_pct"] = snap.get("spy_vol_pct")

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

    counts = defaultdict(int)
    for c in candidates:
        counts[c.get("_vol_state", "unknown")] += 1

    payload = {
        "version": 1,
        "ready": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pool_generated_at": pool.get("generated_at"),
        "promotion_status": "research_only_diagnostic",
        "method": {
            "type": "rolling OOS volatility regime diagnosis",
            "trend_inputs": "SPY and QQQ close vs trailing SMA200 on signal day",
            "volatility_input": "SPY 20d realized volatility annualized",
            "volatility_rank": "signal-day realized volatility percentile versus trailing 252 observations only",
            "green_buckets": {
                "low": "percentile <= 33.3",
                "mid": "33.3 < percentile < 66.7",
                "high": "percentile >= 66.7",
            },
            "quality_selection": "each fold selects quality intensity using TRAIN only; no market state enters the selection score",
            "diagnosis": "TEST states are report-only. No state is excluded and no gate is promoted by this study.",
            "entry_timing": "signal-day close and realized-volatility state are known before next-session entry",
            "equity": "daily_close_mark_to_market",
            "state_only_sleeve": "counterfactual diagnostic portfolio that trades only signals from one state; not additive attribution of the full account",
        },
        "available_start": str(available_start),
        "available_end": str(available_end),
        "latest_market_state": latest,
        "candidate_state_counts": {state: int(counts.get(state, 0)) for state in STATE_ORDER},
        "families": families,
        "notes": [
            "이 단계는 2024처럼 장기추세가 초록이어도 전략이 약해지는 구간의 공통점을 찾는 진단입니다.",
            "변동성 구간을 보고 거래를 끄거나 켜지 않습니다. 먼저 여러 다음-해 TEST에서 같은 패턴이 반복되는지만 확인합니다.",
            "변동성 백분위는 매 신호일 당시까지의 SPY 데이터만 사용하므로 미래 변동성을 보지 않습니다.",
            "state-only sleeve는 상태별 성격을 비교하기 위한 반사실적 진단이며 전체 계좌 수익의 정확한 기여도 합계가 아닙니다.",
            "현재 종목 universe의 survivorship bias는 여전히 남아 있습니다.",
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for family in families:
        s = family["summary"]
        high = s["states"]["green_high_vol"]
        low = s["states"]["green_low_vol"]
        print(
            family["name"],
            s["green_high_vol_drag_pattern"],
            f"high median avg {high['median_avg_trade_pct']}%",
            f"low median avg {low['median_avg_trade_pct']}%",
            f"high worse low {s['green_high_worse_than_low_folds']}/{s['green_high_vs_low_comparable_folds']}",
        )


if __name__ == "__main__":
    main()
