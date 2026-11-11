"""Forward shadow for the one exit policy that passed exit_policy_research.

Frozen on 2026-11-11: confirmed_pullback with a 2.5 ATR stop and a doubled hold.
Every official close-confirmed confirmed_pullback recommendation from the freeze
date on is replayed on real subsequent daily bars twice, once with the current
exit rule and once with the challenger, using the same next-open entry.

Shadow only. It reads the journal, never writes to it, places no orders and
cannot change production rules.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import yfinance as yf

from exit_policy_research import POLICIES, execute, metrics, num
from config import BACKTEST_COMMISSION_PCT, BACKTEST_HALF_SPREAD_BPS, BACKTEST_SLIPPAGE_BPS
from scanner import _extract_frame, _has_incomplete_daily_bar

ROOT = Path(__file__).parent
HISTORY = ROOT / 'static' / 'trade_history.json'
OUT = ROOT / 'static' / 'exit_challenger_shadow.json'

CHALLENGER_ID = 'exit_challenger_v1_confirmed_wide_stop_long_hold'
STRATEGY_ID = 'confirmed_pullback'
POLICY_KEY = 'wide_stop_long_hold'
FREEZE_DATE = '2026-11-11'
MIN_CLOSED_TRADES = 30
# strategy_rules.trade_levels_from_row: confirmed_pullback BUY zone is anchor -0.18 ATR .. +0.22 ATR.
BUY_ZONE_WIDTH_ATR = 0.40


def shadow_candidates(history: dict) -> list[dict]:
    """Official confirmed_pullback picks on or after the freeze date, as replay candidates."""
    out = []
    for day in history.get('days') or []:
        for item in day.get('items') or []:
            market_date = str(item.get('market_date') or day.get('date') or '')[:10]
            if item.get('strategy_id') != STRATEGY_ID or item.get('experimental') or market_date < FREEZE_DATE:
                continue
            low, high = num(item.get('entry_low')), num(item.get('entry_high'))
            atr = (high - low) / BUY_ZONE_WIDTH_ATR
            if low <= 0 or atr <= 0:
                continue
            spark = item.get('sparkline') or []
            out.append({
                'symbol': item.get('symbol'), 'strategy_id': STRATEGY_ID, 'signal_date': market_date,
                'signal_close': num(spark[-1]) if spark else (low + high) / 2.0,
                'buy_low': low, 'buy_high': high, 'atr': atr,
                'stop': num(item.get('stop')), 'target': num(item.get('target'), float('nan')),
                'max_hold': int(num(item.get('target_days_high'), 8)),
            })
    return sorted(out, key=lambda c: (c['signal_date'], str(c['symbol'])))


def completed_path(frame, signal_date: str, now_utc: datetime) -> list[list]:
    """Completed daily bars strictly after the signal date, in replay-pool path shape."""
    if frame is None or frame.empty:
        return []
    if _has_incomplete_daily_bar(frame, now_utc):
        frame = frame.iloc[:-1]
    return [
        [idx.strftime('%Y-%m-%d'), float(bar['Open']), float(bar['High']), float(bar['Low']), float(bar['Close'])]
        for idx, bar in frame.iterrows() if idx.strftime('%Y-%m-%d') > signal_date
    ]


def replay(candidate: dict, policy_key: str, commission: float, friction: float) -> dict:
    policy = POLICIES[policy_key]
    path = candidate.get('path') or []
    if not path:
        return {'status': 'WAITING_ENTRY'}
    trade = execute(candidate, policy, commission, friction)
    if trade is None:
        return {'status': 'REJECTED_ENTRY'}
    required = candidate['max_hold'] * int(policy.get('hold_multiple') or 1)
    if trade['reason'] == 'time' and len(path) < required:
        return {'status': 'OPEN', 'held_bars': len(path), 'mark_return_pct': round(trade['return_pct'], 3)}
    return {
        'status': 'CLOSED', 'reason': trade['reason'], 'held_bars': trade['held_bars'],
        'return_pct': round(trade['return_pct'], 3), 'exit_date': path[trade['held_bars'] - 1][0],
    }


def _summary(rows: list[dict], key: str) -> dict:
    closed = [{'return_pct': r[key]['return_pct'], 'reason': r[key]['reason'], 'held_bars': r[key]['held_bars'], 'symbol': r['symbol']}
              for r in rows if r[key]['status'] == 'CLOSED']
    return {'open': sum(1 for r in rows if r[key]['status'] == 'OPEN'), **metrics(closed)}


def download_frames(symbols: list[str]) -> dict:
    if not symbols:
        return {}
    bulk = yf.download(' '.join(symbols), period='3mo', interval='1d', auto_adjust=False, group_by='ticker', threads=True, progress=False, timeout=30)
    frames = {}
    for symbol in symbols:
        frame = _extract_frame(bulk, symbol, len(symbols))
        if frame is not None and not frame.empty:
            frames[symbol] = frame
    return frames


def build_report(history: dict, frames: dict, now_utc: datetime) -> dict:
    commission = BACKTEST_COMMISSION_PCT / 100.0
    friction = (BACKTEST_SLIPPAGE_BPS + BACKTEST_HALF_SPREAD_BPS) / 10000.0
    rows = []
    for candidate in shadow_candidates(history):
        candidate['path'] = completed_path(frames.get(candidate['symbol']), candidate['signal_date'], now_utc)
        rows.append({
            'symbol': candidate['symbol'], 'signal_date': candidate['signal_date'],
            'baseline': replay(candidate, 'baseline', commission, friction),
            'challenger': replay(candidate, POLICY_KEY, commission, friction),
        })
    baseline, challenger = _summary(rows, 'baseline'), _summary(rows, 'challenger')
    closed = min(baseline.get('trades', 0), challenger.get('trades', 0))
    return {
        'version': 1,
        'challenger_id': CHALLENGER_ID,
        'status': 'FORWARD_SHADOW',
        'strategy_id': STRATEGY_ID,
        'policy': {'key': POLICY_KEY, **POLICIES[POLICY_KEY]},
        'freeze_date': FREEZE_DATE,
        'updated_at': now_utc.isoformat(timespec='seconds'),
        'live_trading_enabled': False,
        'production_mutation_enabled': False,
        'auto_retune': False,
        'minimum_closed_trades_required': MIN_CLOSED_TRADES,
        'sample_ready': closed >= MIN_CLOSED_TRADES,
        'signals': len(rows),
        'baseline': baseline,
        'challenger': challenger,
        'trades': rows,
    }


def main():
    history = json.loads(HISTORY.read_text(encoding='utf-8'))
    symbols = sorted({str(c['symbol']) for c in shadow_candidates(history)})
    now = datetime.now(timezone.utc)
    try:
        frames = download_frames(symbols)
    except Exception as exc:
        # A price outage must not break the market scan; the last snapshot stays in place.
        print(json.dumps({'skipped': 'price download failed', 'error': str(exc)}, ensure_ascii=False))
        return
    report = build_report(history, frames, now)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'signals': report['signals'], 'baseline_closed': report['baseline'].get('trades', 0), 'challenger_closed': report['challenger'].get('trades', 0)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
