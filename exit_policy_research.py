"""Exit-policy research for the three public strategies.

Forward diagnostics showed canonical targets are rarely reached inside the holding
window. This module replays the same canonical signals from the replay pool under a
small, pre-registered set of exit structures and reports TRAIN / OOS / FORWARD
separately. A policy is chosen on TRAIN only; OOS is a pass/fail check.

Research only: nothing here changes production rules or any forward state.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from statistics import mean, median

from strategy_rules import ENTRY_GAP_ATR, ENTRY_GAP_PCT

POOL = Path('static/replay_backtest_pool_v2.json')
OUT = Path('static/exit_policy_research.json')

PUBLIC_STRATEGIES = ('confirmed_pullback', 'rsi2_trend_reversion', 'momentum_pullback')
FORWARD_START_DATE = '2026-08-14'
TRAIN_FRACTION = 0.70
WIDE_STOP_ATR = 2.5
LONG_HOLD_MULTIPLE = 2

# Promotion-to-shadow gate, declared before looking at OOS.
MIN_TRAIN_TRADES = 60
MIN_OOS_TRADES = 30
MIN_TRAIN_EDGE_PCT = 0.10

# Coarse mechanisms, one idea each. This is not a parameter grid.
POLICIES = {
    'baseline': {'label': '현재 규칙', 'note': '지금 추천에 쓰는 목표가·손절가·보유기간'},
    'reach_target': {'label': '닿는 목표가', 'note': '목표가를 과거에 실제로 닿았던 폭(학습구간 중앙값)으로 낮춤', 'target': 'train_median_mfe'},
    'wide_stop': {'label': '넓은 손절', 'note': f'손절을 진입가 - {WIDE_STOP_ATR} ATR로 넓힘', 'stop_atr': WIDE_STOP_ATR},
    'long_hold': {'label': '긴 보유', 'note': f'보유기간을 {LONG_HOLD_MULTIPLE}배로 늘림', 'hold_multiple': LONG_HOLD_MULTIPLE},
    'time_exit': {'label': '기간 청산', 'note': '목표가 없이 보유기간이 끝나는 날 종가에 정리', 'target': None},
    'first_profit_close': {'label': '첫 수익 종가', 'note': '진입가보다 높게 마감한 첫날 종가에 정리', 'first_profit_close': True},
    'reach_target_wide_stop': {'label': '닿는 목표가 + 넓은 손절', 'note': '두 가지를 함께 적용', 'target': 'train_median_mfe', 'stop_atr': WIDE_STOP_ATR},
    'wide_stop_long_hold': {'label': '넓은 손절 + 긴 보유', 'note': '두 가지를 함께 적용', 'stop_atr': WIDE_STOP_ATR, 'hold_multiple': LONG_HOLD_MULTIPLE},
}


def num(value, default=0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def costs(pool: dict) -> tuple[float, float]:
    c = pool.get('costs') or {}
    commission = num(c.get('commission_pct_per_side'), 0.10) / 100.0
    friction = (num(c.get('slippage_bps'), 5.0) + num(c.get('half_spread_bps'), 2.5)) / 10000.0
    return commission, friction


def raw_entry(candidate: dict):
    """Next-session open, or None when the canonical gap guard rejects the entry."""
    path = candidate.get('path') or []
    if not path:
        return None
    entry = num(path[0][1])
    gap = max(ENTRY_GAP_ATR * num(candidate.get('atr')), ENTRY_GAP_PCT * num(candidate.get('signal_close')))
    if entry <= 0 or entry < num(candidate.get('buy_low')) - gap or entry > num(candidate.get('buy_high')) + gap:
        return None
    return entry


def mfe_atr(candidate: dict):
    """Best high inside the canonical hold, in ATR units from the entry open."""
    entry, atr = raw_entry(candidate), num(candidate.get('atr'))
    if entry is None or atr <= 0:
        return None
    hold = max(1, int(num(candidate.get('max_hold'), 1)))
    highs = [num(bar[2]) for bar in (candidate.get('path') or [])[:hold]]
    return (max(highs) - entry) / atr if highs else None


def execute(candidate: dict, policy: dict, commission: float, friction: float, reach_atr: float | None = None):
    """Replay one signal. Same-bar target and stop resolves stop-first."""
    path = candidate.get('path') or []
    opened = raw_entry(candidate)
    atr = num(candidate.get('atr'))
    if opened is None or atr <= 0:
        return None
    entry = opened * (1.0 + friction)

    stop = num(candidate.get('stop'))
    if policy.get('stop_atr'):
        stop = min(stop, opened - policy['stop_atr'] * atr)
    target = num(candidate.get('target'), float('nan'))
    if 'target' in policy:
        if policy['target'] is None:
            target = float('nan')
        elif reach_atr is not None and reach_atr > 0:
            target = opened + reach_atr * atr
    has_target = math.isfinite(target)
    if entry <= stop or (has_target and target <= entry):
        return None

    hold = max(1, int(num(candidate.get('max_hold'), 1))) * int(policy.get('hold_multiple') or 1)
    hold = min(hold, len(path))
    raw_exit, reason, held = num(path[hold - 1][4]), 'time', hold
    for i, bar in enumerate(path[:hold]):
        open_, high, low, close = (num(x) for x in bar[1:5])
        if i > 0 and open_ <= stop:
            raw_exit, reason, held = open_, 'stop_gap', i + 1
            break
        if low <= stop:
            raw_exit, reason, held = stop, 'stop', i + 1
            break
        if has_target and high >= target:
            # A gap above target is filled at target, not at the better open.
            raw_exit, reason, held = target, 'target', i + 1
            break
        if policy.get('first_profit_close') and close > entry:
            raw_exit, reason, held = close, 'profit_close', i + 1
            break

    paid = entry * (1.0 + commission)
    received = raw_exit * (1.0 - friction) * (1.0 - commission)
    return {
        'symbol': candidate.get('symbol'), 'strategy_id': candidate.get('strategy_id'),
        'signal_date': candidate.get('signal_date'), 'return_pct': (received / paid - 1.0) * 100.0,
        'reason': reason, 'held_bars': held,
    }


def metrics(trades: list[dict]) -> dict:
    returns = [t['return_pct'] for t in trades]
    if not returns:
        return {'trades': 0}
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    held = mean(t['held_bars'] for t in trades)
    reasons = [t['reason'] for t in trades]
    by_symbol = defaultdict(float)
    for t in trades:
        by_symbol[t['symbol']] += t['return_pct']
    top_symbol = max(by_symbol.values()) if by_symbol else 0.0
    total = sum(returns)
    return {
        'trades': len(returns),
        'avg_return_pct': round(mean(returns), 3),
        'median_return_pct': round(median(returns), 3),
        'win_rate_pct': round(len(wins) / len(returns) * 100.0, 1),
        'profit_factor': round(sum(wins) / -sum(losses), 3) if losses else None,
        'target_hit_pct': round(reasons.count('target') / len(reasons) * 100.0, 1),
        'stop_pct': round(sum(1 for r in reasons if r.startswith('stop')) / len(reasons) * 100.0, 1),
        'avg_held_bars': round(held, 2),
        'return_per_bar_pct': round(mean(returns) / held, 4) if held > 0 else None,
        'worst_trade_pct': round(min(returns), 2),
        'top_symbol_share_pct': round(top_symbol / total * 100.0, 1) if total > 0 else None,
    }


def split_cutoff(candidates: list[dict]) -> str:
    """Chronological TRAIN/OOS boundary over the pre-forward development data."""
    dates = sorted(c['signal_date'] for c in candidates if c['signal_date'] < FORWARD_START_DATE)
    return dates[min(len(dates) - 1, int(len(dates) * TRAIN_FRACTION))] if dates else FORWARD_START_DATE


def split_of(signal_date: str, cutoff: str) -> str:
    if signal_date >= FORWARD_START_DATE:
        return 'forward'
    return 'train' if signal_date < cutoff else 'oos'


def passes(base: dict, train: dict, oos: dict, base_oos: dict) -> tuple[bool, list[str]]:
    reasons = []
    if train.get('trades', 0) < MIN_TRAIN_TRADES or oos.get('trades', 0) < MIN_OOS_TRADES:
        reasons.append('표본 부족')
        return False, reasons
    if train['avg_return_pct'] - base['avg_return_pct'] < MIN_TRAIN_EDGE_PCT:
        reasons.append('학습구간에서 현재 규칙보다 뚜렷하게 낫지 않음')
    if oos['avg_return_pct'] <= 0:
        reasons.append('검증구간 평균 수익률이 0 이하')
    if (oos.get('profit_factor') or 0) <= 1:
        reasons.append('검증구간 PF가 1 이하')
    if oos['avg_return_pct'] <= base_oos.get('avg_return_pct', 0):
        reasons.append('검증구간에서 현재 규칙보다 낫지 않음')
    return not reasons, reasons


def research_strategy(candidates: list[dict], cutoff: str, commission: float, friction: float) -> dict:
    train_mfe = [m for m in (mfe_atr(c) for c in candidates if split_of(c['signal_date'], cutoff) == 'train') if m is not None]
    reach_atr = round(median(train_mfe), 4) if train_mfe else None
    table = {}
    for key, policy in POLICIES.items():
        buckets = defaultdict(list)
        for candidate in candidates:
            trade = execute(candidate, policy, commission, friction, reach_atr)
            if trade:
                buckets[split_of(candidate['signal_date'], cutoff)].append(trade)
        table[key] = {
            'label': policy['label'], 'note': policy['note'],
            'train': metrics(buckets['train']), 'oos': metrics(buckets['oos']), 'forward': metrics(buckets['forward']),
        }

    base = table['baseline']
    for key, row in table.items():
        if key == 'baseline':
            row['passes_gate'], row['fail_reasons'] = None, []
            continue
        ok, reasons = passes(base['train'], row['train'], row['oos'], base['oos'])
        row['passes_gate'], row['fail_reasons'] = ok, reasons

    # The pick uses TRAIN only. OOS can veto it but never re-rank it.
    challengers = [k for k in table if k != 'baseline' and table[k]['train'].get('trades', 0) >= MIN_TRAIN_TRADES]
    train_pick = max(challengers, key=lambda k: table[k]['train']['avg_return_pct'], default=None)
    return {
        'train_median_mfe_atr': reach_atr,
        'policies': table,
        'train_pick': train_pick,
        'train_pick_passes_oos': bool(train_pick and table[train_pick]['passes_gate']),
    }


def build_report(pool: dict | None = None) -> dict:
    pool = pool if pool is not None else json.loads(POOL.read_text(encoding='utf-8'))
    commission, friction = costs(pool)
    candidates = [c for c in pool.get('trades') or [] if c.get('strategy_id') in PUBLIC_STRATEGIES]
    cutoff = split_cutoff(candidates)
    names = pool.get('strategy_names') or {}
    strategies = {}
    for sid in PUBLIC_STRATEGIES:
        rows = [c for c in candidates if c['strategy_id'] == sid]
        strategies[sid] = {'name': names.get(sid, sid), 'signals': len(rows), **research_strategy(rows, cutoff, commission, friction)}
    return {
        'version': 1,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'status': 'EXIT_POLICY_RESEARCH',
        'research_only': True,
        'production_rules_mutated': False,
        'source': str(POOL).replace('\\', '/'),
        'pool_generated_at': pool.get('generated_at'),
        'train_end_exclusive': cutoff,
        'forward_start_date': FORWARD_START_DATE,
        'costs': {'commission_pct_per_side': commission * 100.0, 'friction_bps_per_side': friction * 10000.0},
        'gate': {
            'min_train_trades': MIN_TRAIN_TRADES, 'min_oos_trades': MIN_OOS_TRADES,
            'min_train_edge_pct': MIN_TRAIN_EDGE_PCT,
            'rule': 'TRAIN에서 고르고 OOS는 통과/탈락만 판정',
        },
        'strategies': strategies,
        'limitations': [
            '현재 유동성 상위 종목을 과거로 되감은 후보풀이라 생존편향이 있습니다.',
            '한 건씩 따로 계산한 결과이며 계좌 현금·동시보유 제한은 반영하지 않았습니다.',
            '일봉만 사용하므로 같은 날 목표가와 손절가를 모두 건드리면 손절로 처리합니다.',
            '검증구간은 이미 다른 연구에서 본 기간이라 완전히 새로운 시험지는 아닙니다. 최종 판단은 Forward 기록으로 합니다.',
        ],
    }


def write_report(out: Path = OUT, pool: dict | None = None) -> dict:
    report = build_report(pool)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    report = write_report()
    print(json.dumps({
        sid: {'train_pick': row['train_pick'], 'passes_oos': row['train_pick_passes_oos']}
        for sid, row in report['strategies'].items()
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
