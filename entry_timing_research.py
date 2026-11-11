"""Entry-timing research: given the same signal, when and how should it be bought?

Exit, market-gate and ranking research could not lift the strategies' expectancy,
which leaves the entry. This module keeps every signal, stop, target and holding
period as they are and changes only the entry mechanics, using a small
pre-registered set. Chosen on TRAIN only; OOS is pass/fail.

Research only. Production entry rules are untouched.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path

from exit_policy_research import (
    FORWARD_START_DATE, MIN_OOS_TRADES, MIN_TRAIN_EDGE_PCT, MIN_TRAIN_TRADES, POLICIES, POOL,
    costs, execute, metrics, num, split_cutoff, split_of,
)
from strategy_optimizer_v2 import execute_candidate
from strategy_rules import ENTRY_GAP_ATR, ENTRY_GAP_PCT

OUT = Path('static/entry_timing_research.json')
# rsi2_trend_reversion is a research strategy now, but its entry is still worth testing.
STRATEGIES = ('confirmed_pullback', 'momentum_pullback', 'rsi2_trend_reversion')
WAIT_BARS = 3
DEEP_LIMIT_ATR = 1.0
MIN_FILL_RATE = 0.40

ENTRIES = {
    'next_open': {'label': '현재 규칙', 'note': '신호 다음 날 시가에 매수'},
    'delay_1d': {'label': '하루 늦게', 'note': '신호 이틀 뒤 시가에 매수'},
    'first_close': {'label': '다음 날 종가', 'note': '신호 다음 날 장 마감 가격에 매수'},
    'limit_buy_low': {'label': '눌림 지정가', 'note': f'진입구간 하단에 지정가를 걸고 {WAIT_BARS}일 기다림, 안 오면 포기'},
    'limit_deep': {'label': '깊은 눌림 지정가', 'note': f'신호일 종가 - {DEEP_LIMIT_ATR} ATR에 지정가, {WAIT_BARS}일 기다림'},
    'breakout_confirm': {'label': '반등 확인 후', 'note': f'신호 다음 날 고가를 넘어설 때 매수, {WAIT_BARS}일 안에 못 넘으면 포기'},
    'up_close_confirm': {'label': '양봉 확인 후', 'note': f'신호 뒤 처음으로 오르며 마감한 날의 다음 시가에 매수 ({WAIT_BARS}일 한도)'},
}


def _inside_gap_guard(candidate: dict, price: float) -> bool:
    gap = max(ENTRY_GAP_ATR * num(candidate.get('atr')), ENTRY_GAP_PCT * num(candidate.get('signal_close')))
    return num(candidate.get('buy_low')) - gap <= price <= num(candidate.get('buy_high')) + gap


def _limit_fill(path: list, limit: float):
    for i, bar in enumerate(path[:WAIT_BARS]):
        open_, low = num(bar[1]), num(bar[3])
        if open_ <= limit:
            return i, open_, {}
        if low <= limit:
            return i, limit, {'intraday_entry': True}
    return None


def entry_fill(candidate: dict, key: str):
    """(entry bar index, raw price, execute kwargs) or None when the entry never fills."""
    path = candidate.get('path') or []
    if not path:
        return None
    if key == 'next_open':
        price = num(path[0][1])
        return (0, price, {}) if _inside_gap_guard(candidate, price) else None
    if key == 'delay_1d':
        if len(path) < 2:
            return None
        price = num(path[1][1])
        return (1, price, {}) if _inside_gap_guard(candidate, price) else None
    if key == 'first_close':
        if len(path) < 2:
            return None
        price = num(path[0][4])
        # Bought at the close, so the next bar can still gap through the stop.
        return (1, price, {'gap_check_first_bar': True}) if _inside_gap_guard(candidate, price) else None
    if key == 'limit_buy_low':
        return _limit_fill(path, num(candidate.get('buy_low')))
    if key == 'limit_deep':
        return _limit_fill(path, num(candidate.get('signal_close')) - DEEP_LIMIT_ATR * num(candidate.get('atr')))
    if key == 'breakout_confirm':
        trigger = num(path[0][2])
        for i in range(1, min(len(path), WAIT_BARS + 1)):
            open_, high = num(path[i][1]), num(path[i][2])
            if open_ >= trigger:
                return i, open_, {}
            if high >= trigger:
                return i, trigger, {'intraday_entry': True}
        return None
    if key == 'up_close_confirm':
        for i in range(min(len(path) - 1, WAIT_BARS)):
            open_, close = num(path[i][1]), num(path[i][4])
            if close > open_ and close > num(candidate.get('signal_close')):
                return i + 1, num(path[i + 1][1]), {}
        return None
    raise ValueError(key)


def simulate(candidate: dict, key: str, commission: float, friction: float):
    fill = entry_fill(candidate, key)
    if fill is None:
        return None
    index, price, kwargs = fill
    shifted = dict(candidate, path=candidate['path'][index:])
    return execute(shifted, POLICIES['baseline'], commission, friction, opened=price, **kwargs)


def judge(row: dict, base: dict) -> tuple[bool, list[str]]:
    train, oos = row['train'], row['oos']
    if train.get('trades', 0) < MIN_TRAIN_TRADES or oos.get('trades', 0) < MIN_OOS_TRADES:
        return False, ['표본 부족']
    reasons = []
    if (row.get('fill_rate') or 0) < MIN_FILL_RATE:
        reasons.append('체결되는 신호가 너무 적음')
    if train['avg_return_pct'] - base['train']['avg_return_pct'] < MIN_TRAIN_EDGE_PCT:
        reasons.append('학습구간에서 현재 규칙보다 뚜렷하게 낫지 않음')
    if train['avg_return_pct'] <= 0:
        reasons.append('학습구간 평균 수익률이 0 이하')
    if oos['avg_return_pct'] <= 0 or (oos.get('profit_factor') or 0) <= 1:
        reasons.append('검증구간에서 이익이 아님')
    if oos['avg_return_pct'] <= base['oos'].get('avg_return_pct', 0):
        reasons.append('검증구간에서 현재 규칙보다 낫지 않음')
    return not reasons, reasons


def research_strategy(candidates: list[dict], cutoff: str, commission: float, friction: float) -> dict:
    developed = sum(1 for c in candidates if c['signal_date'] < FORWARD_START_DATE)
    table = {}
    for key, spec in ENTRIES.items():
        buckets = defaultdict(list)
        for candidate in candidates:
            trade = simulate(candidate, key, commission, friction)
            if trade:
                buckets[split_of(candidate['signal_date'], cutoff)].append(trade)
        filled = len(buckets['train']) + len(buckets['oos'])
        table[key] = {
            **spec, 'train': metrics(buckets['train']), 'oos': metrics(buckets['oos']), 'forward': metrics(buckets['forward']),
            'fill_rate': round(filled / developed, 3) if developed else None,
        }
    base = table['next_open']
    for key, row in table.items():
        row['passes_gate'], row['fail_reasons'] = (None, []) if key == 'next_open' else judge(row, base)
    eligible = [k for k in table if k != 'next_open' and table[k]['train'].get('trades', 0) >= MIN_TRAIN_TRADES
                and (table[k]['fill_rate'] or 0) >= MIN_FILL_RATE]
    pick = max(eligible, key=lambda k: table[k]['train']['avg_return_pct'], default=None)
    return {'entries': table, 'train_pick': pick, 'train_pick_passes_oos': bool(pick and table[pick]['passes_gate'])}


def signal_families(pool: dict, cutoff: str) -> dict:
    """Every signal family in the pool with its own entry and exit, as a map of where
    any edge has existed. Uses the shared replay executor so exit modes match."""
    buckets = defaultdict(lambda: defaultdict(list))
    for candidate in pool.get('trades') or []:
        trade = execute_candidate(candidate, pool, None, None)
        if not trade:
            continue
        held = max(1, (datetime.fromisoformat(trade['end_date']) - datetime.fromisoformat(trade['start_date'])).days)
        buckets[candidate['strategy_id']][split_of(candidate['signal_date'], cutoff)].append(
            {'return_pct': trade['change'] * 100.0, 'reason': 'n/a', 'held_bars': held, 'symbol': candidate['symbol']})
    names = pool.get('strategy_names') or {}
    out = {}
    for sid, rows in buckets.items():
        row = {'name': names.get(sid, sid), **{k: metrics(rows[k]) for k in ('train', 'oos', 'forward')}}
        for part in ('train', 'oos', 'forward'):
            # Calendar days here, not bars, and exit reasons are not comparable across families.
            row[part]['avg_held_days'] = row[part].pop('avg_held_bars', None)
            for key in ('return_per_bar_pct', 'target_hit_pct', 'stop_pct'):
                row[part].pop(key, None)
        out[sid] = row
    return out


def build_report(pool: dict | None = None) -> dict:
    pool = pool if pool is not None else json.loads(POOL.read_text(encoding='utf-8'))
    commission, friction = costs(pool)
    candidates = [c for c in pool.get('trades') or [] if c.get('strategy_id') in STRATEGIES]
    cutoff = split_cutoff(candidates)
    names = pool.get('strategy_names') or {}
    strategies = {}
    for sid in STRATEGIES:
        rows = [c for c in candidates if c['strategy_id'] == sid]
        strategies[sid] = {'name': names.get(sid, sid), 'signals': len(rows), **research_strategy(rows, cutoff, commission, friction)}
    return {
        'version': 1,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'status': 'ENTRY_TIMING_RESEARCH',
        'research_only': True,
        'production_rules_mutated': False,
        'pool_generated_at': pool.get('generated_at'),
        'train_end_exclusive': cutoff,
        'forward_start_date': FORWARD_START_DATE,
        'wait_bars': WAIT_BARS,
        'min_fill_rate': MIN_FILL_RATE,
        'strategies': strategies,
        'signal_families': signal_families(pool, cutoff),
        'limitations': [
            '지정가·돌파 매수는 일봉으로만 체결을 판정합니다. 체결된 날의 목표가 도달은 순서를 알 수 없어 인정하지 않습니다.',
            '체결되지 않은 신호는 평균에서 빠집니다. 체결률이 낮으면 같은 기간에 거래 기회가 줄어듭니다.',
            '현재 유동성 상위 종목을 과거로 되감은 풀이라 생존편향이 있습니다.',
        ],
    }


def write_report(out: Path = OUT, pool: dict | None = None) -> dict:
    report = build_report(pool)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    report = write_report()
    print(json.dumps({sid: [row['train_pick'], row['train_pick_passes_oos']] for sid, row in report['strategies'].items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
