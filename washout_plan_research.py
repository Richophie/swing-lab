"""How to buy and when to sell the washout-rebound signals.

The signals are fixed (union of the rules that passed the evolution gates). This study
only varies the plan around them:

- entry: next open, or a next-day limit order below the signal close
- exit: a fixed number of days, a profit target, or the first sign of a bounce

Plans are compared as a five-slot account, because a plan that sells sooner frees money
for the next signal. The best plans on 2017-2022 are then shown 2023-2024 and 2025+ once.
Research only: nothing here changes a frozen rule or a recommendation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from config import BACKTEST_COMMISSION_PCT, BACKTEST_HALF_SPREAD_BPS, BACKTEST_SLIPPAGE_BPS
import strategy_evolution as se
from washout_risk_research import SEGMENTS, TRAIN, base_signals, stats

OUT = Path('static/washout_plan_research.json')
SLOTS = 5
FINALISTS = 3
ENTRIES = {'next_open': None, 'limit_0.5atr': 0.5, 'limit_1atr': 1.0}
# (kind, parameter, last day): the position is always closed at the close of `last day` at the latest.
EXITS = {
    'hold_3d': ('time', None, 3), 'hold_5d': ('time', None, 5), 'hold_7d': ('time', None, 7), 'hold_10d': ('time', None, 10),
    'target_1.5atr_7d': ('target', 1.5, 7), 'target_3atr_7d': ('target', 3.0, 7),
    'first_profit_close_7d': ('profit_close', None, 7), 'first_profit_close_10d': ('profit_close', None, 10),
    'close_above_sma5_7d': ('above_sma5', None, 7), 'close_above_sma5_10d': ('above_sma5', None, 10),
    'close_above_prev_high_7d': ('above_prev_high', None, 7),
}
BASE = ('next_open', 'hold_7d')
LABELS = {
    'next_open': '다음 날 시가에 매수', 'limit_0.5atr': '다음 날 신호일 종가보다 0.5 ATR 낮은 지정가로 매수',
    'limit_1atr': '다음 날 신호일 종가보다 1 ATR 낮은 지정가로 매수',
    'hold_3d': '3거래일 뒤 종가 매도', 'hold_5d': '5거래일 뒤 종가 매도', 'hold_7d': '7거래일 뒤 종가 매도', 'hold_10d': '10거래일 뒤 종가 매도',
    'target_1.5atr_7d': '1.5 ATR 오르면 매도, 아니면 7거래일 뒤', 'target_3atr_7d': '3 ATR 오르면 매도, 아니면 7거래일 뒤',
    'first_profit_close_7d': '산 가격보다 높게 마감한 첫날 매도, 늦어도 7거래일', 'first_profit_close_10d': '산 가격보다 높게 마감한 첫날 매도, 늦어도 10거래일',
    'close_above_sma5_7d': '5일 평균 위로 마감한 첫날 매도, 늦어도 7거래일', 'close_above_sma5_10d': '5일 평균 위로 마감한 첫날 매도, 늦어도 10거래일',
    'close_above_prev_high_7d': '전날 고가 위로 마감한 첫날 매도, 늦어도 7거래일',
}


def trades_for(panel: dict, sma5: np.ndarray, signals: np.ndarray, entry_mode: str, exit_mode: str) -> list[dict]:
    """One row per filled trade: signal day, symbol column, exit day and net % return."""
    o, h, l, c, atr = (panel[k] for k in ('open', 'high', 'low', 'close', 'atr'))
    commission = BACKTEST_COMMISSION_PCT / 100.0
    friction = (BACKTEST_SLIPPAGE_BPS + BACKTEST_HALF_SPREAD_BPS) / 10000.0
    discount = ENTRIES[entry_mode]
    kind, parameter, last = EXITS[exit_mode]
    rows = []
    for i, j in zip(*np.nonzero(signals)):
        e, final = i + 1, i + last
        # The whole window must exist, so every plan is judged on finished trades only.
        if final >= len(c) or not np.isfinite(c[e:final + 1, j]).all() or not np.isfinite(atr[i, j]) or atr[i, j] <= 0:
            continue
        if discount is None:
            entry = float(o[e, j])
        else:
            limit = float(c[i, j] - discount * atr[i, j])
            if not l[e, j] <= limit:
                continue
            entry = float(min(o[e, j], limit))
        exit_day, exit_price = final, float(c[final, j])
        for d in range(e, final + 1):
            if kind == 'target' and h[d, j] >= entry + parameter * atr[i, j]:
                exit_day, exit_price = d, float(entry + parameter * atr[i, j]); break
            if kind == 'profit_close' and c[d, j] > entry:
                exit_day, exit_price = d, float(c[d, j]); break
            if kind == 'above_sma5' and c[d, j] > sma5[d, j]:
                exit_day, exit_price = d, float(c[d, j]); break
            if kind == 'above_prev_high' and c[d, j] > h[d - 1, j]:
                exit_day, exit_price = d, float(c[d, j]); break
        paid = entry * (1 + friction) * (1 + commission)
        received = exit_price * (1 - friction) * (1 - commission)
        rows.append({'day': int(i), 'col': int(j), 'entry_day': int(e), 'exit_day': int(exit_day), 'return_pct': (received / paid - 1) * 100.0})
    return rows


def account(trades: list[dict], liquidity: np.ndarray, slots: int = SLOTS) -> dict:
    """Equal slots, most liquid signal first, a slot is reusable the day after its exit."""
    free_at = [0] * slots
    taken = []
    for t in sorted(trades, key=lambda t: (t['day'], -float(np.nan_to_num(liquidity[t['day'], t['col']])))):
        slot = next((k for k in range(slots) if free_at[k] <= t['entry_day']), None)
        if slot is None:
            continue
        free_at[slot] = t['exit_day'] + 1
        taken.append(t)
    equity = peak = 1.0
    max_drawdown = 0.0
    for t in sorted(taken, key=lambda t: t['exit_day']):
        equity *= 1.0 + t['return_pct'] / 100.0 / slots
        peak = max(peak, equity); max_drawdown = min(max_drawdown, equity / peak - 1.0)
    held = [t['exit_day'] - t['entry_day'] + 1 for t in taken]
    return {'trades_taken': len(taken), 'total_return_pct': round((equity - 1) * 100, 1), 'max_drawdown_pct': round(max_drawdown * 100, 1),
            'avg_days_held': round(float(np.mean(held)), 1) if held else None}


def evaluate(ctx: se.Context, trades: list[dict], signal_count: dict) -> dict:
    out = {}
    for name, span in SEGMENTS.items():
        rows = ctx.rows(*span)
        mine = [t for t in trades if rows[t['day']]]
        per_trade = stats(np.array([t['return_pct'] for t in mine]))
        out[name] = {**per_trade, **account(mine, ctx.features['dollar_volume_log']),
                     'fill_rate_pct': round(len(mine) / signal_count[name] * 100, 1) if signal_count[name] else None}
    return out


def choose(plans: dict, limit: int = FINALISTS) -> list[str]:
    """Plans whose worst TRAIN fold beats the base plan's worst fold without a deeper drawdown. Unseen periods are not consulted."""
    worst = lambda p: min(p[f]['total_return_pct'] for f in TRAIN)
    deepest = lambda p: min(p[f]['max_drawdown_pct'] for f in TRAIN)
    base = plans['|'.join(BASE)]
    better = [k for k, p in plans.items() if k != '|'.join(BASE) and worst(p) > worst(base) and deepest(p) >= deepest(base) - 3.0]
    return sorted(better, key=lambda k: worst(plans[k]), reverse=True)[:limit]


def judge(base: dict, plan: dict) -> dict:
    result = {}
    for name in ('validation', 'lockbox'):
        result[name] = {'total_return_change_pct': round(plan[name]['total_return_pct'] - base[name]['total_return_pct'], 1),
                        'max_drawdown_change_pct': round(plan[name]['max_drawdown_pct'] - base[name]['max_drawdown_pct'], 1)}
    result['survives'] = all(result[n]['total_return_change_pct'] > 0 and result[n]['max_drawdown_change_pct'] >= -2.0 for n in ('validation', 'lockbox'))
    return result


def build(ctx: se.Context, ledger: dict) -> dict:
    signals = base_signals(ctx, ledger)
    sma5 = pd.DataFrame(ctx.panel['close']).rolling(5).mean().to_numpy()
    signal_count = {name: int(signals[ctx.rows(*span)].sum()) for name, span in SEGMENTS.items()}
    plans = {}
    for entry_mode in ENTRIES:
        for exit_mode in EXITS:
            plans[f'{entry_mode}|{exit_mode}'] = evaluate(ctx, trades_for(ctx.panel, sma5, signals, entry_mode, exit_mode), signal_count)
    base = plans['|'.join(BASE)]
    finalists = [{'plan': key, 'entry': LABELS[key.split('|')[0]], 'exit': LABELS[key.split('|')[1]],
                  'unseen': judge(base, plans[key]), 'segments': plans[key]} for key in choose(plans)]
    return {
        'version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'status': 'RESEARCH_ONLY', 'production_rules_mutated': False, 'frozen_rules_mutated': False,
        'slots': SLOTS, 'base_plan': '|'.join(BASE), 'base': base, 'plans_tried': len(plans),
        'finalists': finalists, 'survivors': [f['plan'] for f in finalists if f['unseen']['survives']],
        'plans': plans, 'labels': LABELS,
        'limitations': [
            '지정가 매수는 저가가 지정가에 닿으면 체결된 것으로 봅니다. 실제로는 닿고도 체결되지 않을 수 있습니다.',
            '계좌 수익은 5칸에 똑같이 나눠 담고 청산일에 반영한 근사치입니다.',
            '33개 계획을 시험했으므로 우연히 좋아 보이는 것이 섞일 수 있습니다.',
            '가격이 남아 있지 않은 상장폐지 회사는 빠져 있습니다.',
        ],
    }


def main():
    ctx = se.Context(se.load_panel() if se.PANEL_CACHE.exists() else se.build_panel())
    report = build(ctx, json.loads(se.OUT.read_text(encoding='utf-8')))
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    short = lambda p: {s: (p[s]['trades'], p[s]['avg_return_pct'], p[s]['win_rate_pct'], p[s]['big_loss_share_pct'], p[s]['trades_taken'], p[s]['total_return_pct'], p[s]['max_drawdown_pct'], p[s]['avg_days_held']) for s in SEGMENTS}
    print('columns: trades, avg%, win%, bigloss%, taken, account%, mdd%, days')
    for key, plan in report['plans'].items():
        print(key, json.dumps(short(plan)))
    print('finalists', json.dumps([{k: f[k] for k in ('plan', 'unseen')} for f in report['finalists']], ensure_ascii=False))


if __name__ == '__main__':
    main()
