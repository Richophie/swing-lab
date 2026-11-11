"""Forward shadow for the entry-feature rules that passed entry_feature_research.

Frozen on 2026-11-11 from the wide-universe pool:

- momentum_pullback: signal-day body / ATR in the top TRAIN tercile
- confirmed_pullback: planned reward/risk in the top TRAIN tercile

Each official close-confirmed recommendation from the freeze date on is tagged as
passing or failing its frozen rule, and the official journal outcome is reported
for both groups. Nothing is filtered in production; this only measures whether
the rule would have separated winners from losers going forward.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import yfinance as yf

from entry_feature_pool import feature_frame
from forward_diagnostics import metrics
from scanner import _extract_frame

ROOT = Path(__file__).parent
HISTORY = ROOT / 'static' / 'trade_history.json'
OUT = ROOT / 'static' / 'entry_rule_shadow.json'

CHALLENGER_ID = 'entry_rule_v1_2026-11-11'
FREEZE_DATE = '2026-11-11'
MIN_CLOSED_PER_GROUP = 30
# Thresholds are the TRAIN tercile cuts at freeze time and must not be re-fitted.
RULES = {
    'momentum_pullback': {'feature': 'body_atr', 'label': '신호일에 강한 양봉 (몸통이 ATR의 0.62배 이상)', 'min': 0.61702},
    'confirmed_pullback': {'feature': 'plan_reward_risk', 'label': '계획 손익비 2.81 이상', 'min': 2.80611},
}


def _num(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def plan_reward_risk(item: dict):
    low, high, target, stop = (_num(item.get(k)) for k in ('entry_low', 'entry_high', 'target', 'stop'))
    if None in (low, high, target, stop):
        return None
    entry = (low + high) / 2.0
    return (target - entry) / (entry - stop) if entry > stop else None


def shadow_items(history: dict) -> list[dict]:
    out = []
    for day in history.get('days') or []:
        for item in day.get('items') or []:
            market_date = str(item.get('market_date') or day.get('date') or '')[:10]
            if item.get('strategy_id') in RULES and not item.get('experimental') and market_date >= FREEZE_DATE:
                out.append(dict(item, _day=market_date))
    return sorted(out, key=lambda x: (x['_day'], str(x.get('symbol'))))


def feature_value(item: dict, frames: dict):
    rule = RULES[item['strategy_id']]
    if rule['feature'] == 'plan_reward_risk':
        return plan_reward_risk(item)
    frame = frames.get(item.get('symbol'))
    if frame is None or frame.empty:
        return None
    # Only bars up to the recommendation's market date may be used.
    known = frame[[idx.strftime('%Y-%m-%d') <= item['_day'] for idx in frame.index]]
    if known.empty or known.index[-1].strftime('%Y-%m-%d') != item['_day']:
        return None
    return _num(feature_frame(known)[rule['feature']].iloc[-1])


def build_report(history: dict, frames: dict, now_utc: datetime) -> dict:
    rows = []
    for item in shadow_items(history):
        value = feature_value(item, frames)
        rule = RULES[item['strategy_id']]
        rows.append({
            'symbol': item.get('symbol'), 'strategy_id': item['strategy_id'], 'signal_date': item['_day'],
            'feature_value': None if value is None else round(value, 4),
            'passes_rule': None if value is None else value >= rule['min'],
            'status_code': item.get('status_code'), 'outcome_return_pct': item.get('outcome_return_pct'),
        })
    strategies = {}
    for sid, rule in RULES.items():
        mine = [r for r in rows if r['strategy_id'] == sid]
        closed = [r for r in mine if r['status_code'] != 'OPEN' and _num(r['outcome_return_pct']) is not None]
        passing = metrics([r for r in closed if r['passes_rule'] is True])
        failing = metrics([r for r in closed if r['passes_rule'] is False])
        strategies[sid] = {
            'rule': rule, 'signals': len(mine), 'unscored': sum(1 for r in mine if r['passes_rule'] is None),
            'passing': passing, 'failing': failing,
            'sample_ready': min(passing.get('closed', 0), failing.get('closed', 0)) >= MIN_CLOSED_PER_GROUP,
        }
    return {
        'version': 1,
        'challenger_id': CHALLENGER_ID,
        'status': 'FORWARD_SHADOW',
        'freeze_date': FREEZE_DATE,
        'updated_at': now_utc.isoformat(timespec='seconds'),
        'live_trading_enabled': False,
        'production_mutation_enabled': False,
        'auto_retune': False,
        'minimum_closed_per_group': MIN_CLOSED_PER_GROUP,
        'strategies': strategies,
        'trades': rows,
    }


def download_frames(symbols: list[str]) -> dict:
    if not symbols:
        return {}
    bulk = yf.download(' '.join(symbols), period='6mo', interval='1d', auto_adjust=False, group_by='ticker', threads=True, progress=False, timeout=30)
    frames = {}
    for symbol in symbols:
        frame = _extract_frame(bulk, symbol, len(symbols))
        if frame is not None and not frame.empty:
            frames[symbol] = frame
    return frames


def main():
    history = json.loads(HISTORY.read_text(encoding='utf-8'))
    needs_prices = sorted({str(i['symbol']) for i in shadow_items(history) if RULES[i['strategy_id']]['feature'] != 'plan_reward_risk'})
    try:
        frames = download_frames(needs_prices)
    except Exception as exc:
        # A price outage must not break the market scan; the last snapshot stays in place.
        print(json.dumps({'skipped': 'price download failed', 'error': str(exc)}, ensure_ascii=False))
        return
    report = build_report(history, frames, datetime.now(timezone.utc))
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({sid: {'signals': s['signals'], 'ready': s['sample_ready']} for sid, s in report['strategies'].items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
