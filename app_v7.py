from datetime import datetime, timezone
import json
import time
import pandas as pd
import yfinance as yf

from app_v6 import app, CACHE_FILE, swing_score, trade_plan, market_live
from calibration import apply_calibration, calibrated_grade

LIVE_TTL_SECONDS = 120
_live_cache = {"at": 0.0, "payload": None}


def _latest_payload():
    if not CACHE_FILE.exists():
        return {"status": "pending", "results": [], "message": "자동 스캔 결과를 준비 중입니다."}
    return json.loads(CACHE_FILE.read_text(encoding="utf-8"))


def _live_refresh():
    base = _latest_payload()
    rows = base.get("results") or []
    symbols = [r.get("symbol") for r in rows if r.get("symbol")][:40]
    if not symbols:
        return base

    bulk = yf.download(
        " ".join(symbols), period="10mo", interval="1d", auto_adjust=False,
        group_by="ticker", threads=True, progress=False, timeout=20
    )
    old = {r.get("symbol"): r for r in rows}
    refreshed = []
    failures = []

    for symbol in symbols:
        try:
            d = bulk.copy() if len(symbols) == 1 else bulk[symbol].copy()
            d = d.dropna(subset=["Open", "High", "Low", "Close"])
            if len(d) < 120:
                raise ValueError("일봉 부족")
            sig = swing_score(d)
            plan = trade_plan(d)
            prev = old.get(symbol, {})
            raw=float(sig['score'])
            cal=apply_calibration(raw)
            sig.update({
                "symbol": symbol,
                "raw_score": round(raw,1),
                "score": cal['calibrated_score'],
                "grade": calibrated_grade(cal['calibrated_score']),
                "calibration": cal,
                "sparkline": [round(float(x), 2) for x in d["Close"].tail(35).tolist()],
                "trade_plan": plan,
                "history_stats": prev.get("history_stats", {}),
                "previous_score": prev.get("score"),
                "score_delta": round(float(cal['calibrated_score']) - float(prev.get("score", cal['calibrated_score'])), 1),
            })
            refreshed.append(sig)
        except Exception as exc:
            failures.append({"symbol": symbol, "reason": str(exc)})
            if symbol in old:
                refreshed.append(old[symbol])

    refreshed.sort(key=lambda x: x.get("score", 0), reverse=True)
    market = market_live()
    return {
        **base,
        "status": "ready",
        "version": "8.1",
        "market": market,
        "results": refreshed,
        "live_refreshed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "live_count": len(symbols),
        "live_failed": failures,
        "message": "전체 시장은 저장된 스캔을 사용하고 현재 후보만 최신 시세+보정점수로 재검증했습니다.",
    }


def index_v7():
    return app.send_static_file("v71.html")

app.view_functions["index"] = index_v7


@app.route("/api/live-refresh")
def live_refresh():
    now = time.time()
    if _live_cache["payload"] is not None and now - _live_cache["at"] < LIVE_TTL_SECONDS:
        payload = dict(_live_cache["payload"])
        payload["served_from_live_cache"] = True
        return payload
    try:
        payload = _live_refresh()
        _live_cache["at"] = now
        _live_cache["payload"] = payload
        return payload
    except Exception as exc:
        base = _latest_payload()
        base["live_error"] = str(exc)
        base["message"] = "실시간 재검증에 실패해 마지막 저장 결과를 보여줍니다."
        return base


@app.route("/api/version")
def version():
    return {"version": "8.1", "mode": "cached-full-scan + live-candidate-refresh + statistical-calibration", "ui": "v71.html"}
