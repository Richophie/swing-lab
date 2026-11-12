"""Do officers and directors buying their own stock mark a good swing entry?

Uses the purchases extracted by insider_data.py (SEC Form 4, free). The signal day is the
first session on or after the day the filing became public; the stock is bought at the next
open and held seven trading days, with the usual costs.

Four ways of reading the filings are fixed in advance, so the bar is raised for four tries.
Research only: nothing here changes a frozen rule or a recommendation.
"""
from __future__ import annotations

from bisect import bisect_left
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

import strategy_evolution as se
from public_playbook_bench import fresh
from washout_risk_research import SEGMENTS, base_signals, stats

OUT = Path('static/insider_research.json')
BUYS = Path('static/insider_buys.json')
HOLD = 7
CLUSTER_WINDOW = 10
SETUPS = {
    'buy_100k': '임원·이사가 10만 달러 이상 매수 공시',
    'buy_1m': '임원·이사가 100만 달러 이상 매수 공시',
    'cluster_buy': '최근 10거래일 안에 2명 이상이 매수 공시',
    'buy_in_drawdown': '석 달 고점에서 15% 넘게 내려온 종목에 10만 달러 이상 매수 공시',
}


def filing_matrices(ctx: se.Context, buys: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Dollar value of purchases made public on each (day, symbol), and how many different insiders filed."""
    sessions = [str(d) for d in ctx.dates]
    column = {str(s): j for j, s in enumerate(ctx.symbols)}
    value = np.zeros(ctx.panel['close'].shape, dtype=np.float64)
    people: dict[tuple[int, int], set] = {}
    for row in buys:
        j = column.get(row['symbol'])
        i = bisect_left(sessions, row['filed'])
        if j is None or i >= len(sessions):
            continue
        value[i, j] += row['value_usd']
        people.setdefault((i, j), set()).add(row['owner'])
    count = np.zeros(value.shape, dtype=np.int32)
    for (i, j), owners in people.items():
        count[i, j] = len(owners)
    return value, count


def recent_insiders(ctx: se.Context, buys: list[dict], window: int = CLUSTER_WINDOW) -> np.ndarray:
    """Different insiders who filed a purchase in the last `window` sessions, today included."""
    sessions = [str(d) for d in ctx.dates]
    column = {str(s): j for j, s in enumerate(ctx.symbols)}
    by_symbol: dict[int, list[tuple[int, str]]] = {}
    for row in buys:
        j, i = column.get(row['symbol']), bisect_left(sessions, row['filed'])
        if j is not None and i < len(sessions):
            by_symbol.setdefault(j, []).append((i, row['owner']))
    out = np.zeros(ctx.panel['close'].shape, dtype=np.int32)
    for j, events in by_symbol.items():
        for i in sorted({i for i, _ in events}):
            out[i, j] = len({owner for day, owner in events if i - window < day <= i})
    return out


def study(ctx: se.Context, ledger: dict, buys: list[dict]) -> dict:
    value, count = filing_matrices(ctx, buys)
    cluster = recent_insiders(ctx, buys)
    with np.errstate(invalid='ignore'):
        masks = {
            'buy_100k': value >= 100_000,
            'buy_1m': value >= 1_000_000,
            'cluster_buy': (count >= 1) & (cluster >= 2),
            'buy_in_drawdown': (value >= 100_000) & (np.nan_to_num(ctx.features['drawdown_60d'], nan=0.0) <= -0.15),
        }
    week = se.trade_returns(ctx.panel, HOLD, None, None)
    month = se.trade_returns(ctx.panel, 20, None, None)
    everything = np.ones(len(ctx.symbols), dtype=bool)
    all_days = np.ones(len(ctx.dates), dtype=bool)
    bar = se.required_t(len(SETUPS))
    seg = lambda r, m, rows: se.segment_stats(r, m, rows, everything, se.Context.span_years(ctx.dates[rows]))
    setups = {}
    for name, mask in masks.items():
        signals = fresh(mask & ctx.tradable, HOLD)
        segments = {s: seg(week, signals, ctx.rows(*span)) for s, span in SEGMENTS.items()}
        whole = seg(week, signals, all_days)
        positive = all(segments[s].get('trades', 0) > 0 and segments[s]['avg_return_pct'] > 0 for s in SEGMENTS)
        setups[name] = {'label': SETUPS[name], 'all_years': whole, 'segments': segments, 'hold_20_days_reference': seg(month, signals, all_days),
                        'positive_in_every_period': positive, 'holds_up': bool(positive and whole.get('t_stat', 0) >= bar)}
    # Does a recent insider purchase make a washout signal better?
    washout = base_signals(ctx, ledger)
    lately = np.zeros_like(washout)
    seen = value > 0
    for lag in range(0, 21):
        lately[lag:] |= seen[:len(seen) - lag] if lag else seen
    taken = washout & np.isfinite(week)
    overlay = {s: {'with_insider_buy_in_last_20_days': stats(week[ctx.rows(*span)][(taken & lately)[ctx.rows(*span)]]),
                   'without': stats(week[ctx.rows(*span)][(taken & ~lately)[ctx.rows(*span)]])} for s, span in SEGMENTS.items()}
    return {'t_required': round(bar, 2), 'setups': setups, 'holding_up': [k for k, v in setups.items() if v['holds_up']],
            'washout_with_recent_insider_buy': overlay, 'filing_days_in_panel': int((value > 0).sum())}


def build(ctx: se.Context, ledger: dict, data: dict) -> dict:
    return {
        'version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'status': 'RESEARCH_ONLY', 'production_rules_mutated': False, 'frozen_rules_mutated': False,
        'source': data.get('source'), 'purchase_rows': data.get('rows'), 'symbols_with_buys': data.get('symbols_with_buys'), 'hold_days': HOLD,
        **study(ctx, ledger, data['buys']),
        'limitations': [
            '공시일 당일 종가 이후에 알았다고 보고 다음 날 시가에 삽니다. 장중에 공시된 경우 실제로는 더 일찍 알 수 있습니다.',
            '티커가 바뀐 회사의 옛 공시는 연결하지 못했습니다.',
            '대형주는 내부자 매수가 드물어 표본이 작습니다.',
            '가격이 남아 있지 않은 상장폐지 회사는 빠져 있습니다.',
        ],
    }


def main():
    ctx = se.Context(se.load_panel() if se.PANEL_CACHE.exists() else se.build_panel())
    report = build(ctx, json.loads(se.OUT.read_text(encoding='utf-8')), json.loads(BUYS.read_text(encoding='utf-8')))
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print('rows', report['purchase_rows'], 'symbols', report['symbols_with_buys'], 'filing days', report['filing_days_in_panel'], 't needed', report['t_required'])
    for name, r in report['setups'].items():
        a, m = r['all_years'], r['hold_20_days_reference']
        print(name, a.get('trades'), a.get('avg_return_pct'), a.get('win_rate_pct'), a.get('t_stat'), [(r['segments'][s].get('trades'), r['segments'][s].get('avg_return_pct')) for s in SEGMENTS],
              '| 20d', m.get('avg_return_pct'), m.get('t_stat'), r['holds_up'])
    for s, v in report['washout_with_recent_insider_buy'].items():
        print(s, {k: (x.get('trades'), x.get('avg_return_pct'), x.get('big_loss_share_pct')) for k, x in v.items()})


if __name__ == '__main__':
    main()
