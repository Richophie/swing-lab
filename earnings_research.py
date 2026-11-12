"""Does knowing the earnings calendar help?

Uses the reaction days built by earnings_calendar.py (SEC filings, free). Three questions:

A. Skip washout signals whose seven-day hold contains an earnings release?
B. Do washouts right after an earnings release behave differently from the others?
C. Does the well-known drift after an earnings surprise work as a rule of its own?
   (buy the next open after a big earnings-day move, hold seven days)

Past dates stand in for the calendar a trader would have had: companies announce the day in
advance, so "earnings fall inside the hold" was knowable on the signal day.
Research only: nothing here changes a frozen rule or a recommendation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

import strategy_evolution as se
from washout_risk_research import SEGMENTS, TRAIN, base_signals, judge, stats

OUT = Path('static/earnings_research.json')
CALENDAR = Path('static/earnings_dates.json')
HOLD = 7
BIG_MOVE = 0.05
# name: (label, test on the reaction-day features)
EARNINGS_SETUPS = {
    'jump_then_drift': ('실적 발표일 5% 이상 상승 뒤 매수', lambda move, strong: move >= BIG_MOVE),
    'strong_jump_then_drift': ('실적 발표일 8% 이상 상승하고 고가 근처 마감 뒤 매수', lambda move, strong: (move >= 0.08) & strong),
    'drop_then_rebound': ('실적 발표일 5% 이상 하락 뒤 매수', lambda move, strong: move <= -BIG_MOVE),
}


def reaction_matrix(ctx: se.Context, calendar: dict) -> tuple[np.ndarray, np.ndarray]:
    """True on each symbol's reaction days, and which symbols have a calendar at all."""
    day_index = {str(d): i for i, d in enumerate(ctx.dates)}
    matrix = np.zeros(ctx.panel['close'].shape, dtype=bool)
    known = np.zeros(len(ctx.symbols), dtype=bool)
    for j, symbol in enumerate(ctx.symbols):
        days = calendar.get(str(symbol)) or []
        rows = [day_index[d] for d in days if d in day_index]
        if rows:
            matrix[rows, j] = True
            known[j] = True
    return matrix, known


def days_until_next(matrix: np.ndarray) -> np.ndarray:
    """Trading days from each day to the next reaction day (0 on the day itself, large when none is known)."""
    out = np.full(matrix.shape, 10_000, dtype=np.int32)
    for i in range(len(matrix) - 1, -1, -1):
        if i + 1 < len(matrix):
            out[i] = np.minimum(out[i + 1] + 1, 10_000)
        out[i][matrix[i]] = 0
    return out


def days_since_last(matrix: np.ndarray) -> np.ndarray:
    out = np.full(matrix.shape, 10_000, dtype=np.int32)
    for i in range(len(matrix)):
        if i > 0:
            out[i] = np.minimum(out[i - 1] + 1, 10_000)
        out[i][matrix[i]] = 0
    return out


def by_segment(ctx: se.Context, returns: np.ndarray, mask: np.ndarray) -> dict:
    taken = mask & np.isfinite(returns)
    return {name: stats(returns[ctx.rows(*span)][taken[ctx.rows(*span)]]) for name, span in SEGMENTS.items()}


def washout_study(ctx: se.Context, ledger: dict, matrix: np.ndarray, known: np.ndarray) -> dict:
    signals = base_signals(ctx, ledger) & known[None, :]
    returns = se.trade_returns(ctx.panel, HOLD, None, None)
    ahead, behind = days_until_next(matrix), days_since_last(matrix)
    inside = (ahead >= 1) & (ahead <= HOLD)          # an earnings release lands between the buy day and the sell day
    fresh_news = behind <= 3                          # the washout happened within three days after a release
    base = by_segment(ctx, returns, signals)
    kept = by_segment(ctx, returns, signals & ~inside)
    train_ok = all(kept[f]['trades'] and kept[f]['avg_return_pct'] >= base[f]['avg_return_pct'] and kept[f]['big_loss_share_pct'] <= base[f]['big_loss_share_pct'] for f in TRAIN)
    return {
        'signals_with_calendar': int(signals.sum()), 'base': base,
        'earnings_inside_hold': by_segment(ctx, returns, signals & inside), 'no_earnings_inside_hold': kept,
        'skip_rule': {'train_helped_in_every_fold': bool(train_ok), 'unseen': judge(base, kept)},
        'right_after_earnings': by_segment(ctx, returns, signals & fresh_news), 'not_right_after_earnings': by_segment(ctx, returns, signals & ~fresh_news),
    }


def drift_study(ctx: se.Context, matrix: np.ndarray) -> dict:
    close = ctx.panel['close'].astype(np.float64)
    move = np.full(close.shape, np.nan)
    move[1:] = close[1:] / close[:-1] - 1
    strong = np.nan_to_num(ctx.features['close_in_range'], nan=0.0) >= 0.7
    returns = se.trade_returns(ctx.panel, HOLD, None, None)
    everything = np.ones(len(ctx.symbols), dtype=bool)
    bar = se.required_t(len(EARNINGS_SETUPS))
    out = {}
    for name, (label, test) in EARNINGS_SETUPS.items():
        with np.errstate(invalid='ignore'):
            signals = matrix & ctx.tradable & np.nan_to_num(test(move, strong), nan=0).astype(bool)
        segments = {s: se.segment_stats(returns, signals, ctx.rows(*span), everything, se.Context.span_years(ctx.dates[ctx.rows(*span)])) for s, span in SEGMENTS.items()}
        whole = se.segment_stats(returns, signals, np.ones(len(ctx.dates), dtype=bool), everything, se.Context.span_years(ctx.dates))
        positive = all((segments[s].get('avg_return_pct') or -1) > 0 for s in SEGMENTS)
        out[name] = {'label': label, 'all_years': whole, 'segments': segments, 'positive_in_every_period': positive,
                     'holds_up': bool(positive and whole.get('t_stat', 0) >= bar)}
    return {'t_required': round(bar, 2), 'setups': out, 'holding_up': [k for k, v in out.items() if v['holds_up']]}


def build(ctx: se.Context, ledger: dict, calendar_file: dict) -> dict:
    matrix, known = reaction_matrix(ctx, calendar_file['dates'])
    return {
        'version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'status': 'RESEARCH_ONLY', 'production_rules_mutated': False, 'frozen_rules_mutated': False,
        'calendar_source': calendar_file.get('source'), 'symbols_with_calendar': int(known.sum()), 'symbols': int(len(known)),
        'reaction_days': int(matrix.sum()), 'hold_days': HOLD,
        'washout': washout_study(ctx, ledger, matrix, known), 'drift': drift_study(ctx, matrix),
        'limitations': [
            '실적 공시(8-K 2.02항) 접수 시각으로 반응일을 정했습니다. 잠정 실적이나 다른 내용이 같은 항목으로 접수된 경우가 섞여 있을 수 있습니다.',
            '실적 수치가 예상보다 좋았는지는 모릅니다. 발표일 주가 움직임을 대신 썼습니다.',
            'SEC에서 찾지 못한 회사(이름·티커가 바뀐 회사 등)는 빠져 있습니다.',
            '가격이 남아 있지 않은 상장폐지 회사는 빠져 있습니다.',
        ],
    }


def main():
    ctx = se.Context(se.load_panel() if se.PANEL_CACHE.exists() else se.build_panel())
    report = build(ctx, json.loads(se.OUT.read_text(encoding='utf-8')), json.loads(CALENDAR.read_text(encoding='utf-8')))
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print('calendar', report['symbols_with_calendar'], '/', report['symbols'], 'reaction days', report['reaction_days'])
    w = report['washout']
    brief = lambda p: {s: (p[s].get('trades'), p[s].get('avg_return_pct'), p[s].get('win_rate_pct'), p[s].get('big_loss_share_pct')) for s in SEGMENTS}
    for key in ('base', 'earnings_inside_hold', 'no_earnings_inside_hold', 'right_after_earnings', 'not_right_after_earnings'):
        print(key, brief(w[key]))
    print('skip rule', w['skip_rule'])
    for name, r in report['drift']['setups'].items():
        a = r['all_years']
        print(name, a.get('trades'), a.get('avg_return_pct'), a.get('win_rate_pct'), a.get('t_stat'), [r['segments'][s].get('avg_return_pct') for s in SEGMENTS], r['holds_up'])
    print('t needed', report['drift']['t_required'])


if __name__ == '__main__':
    main()
