"""What a small account would have earned per year following the passing rules.

Earlier studies judged a rule by its average trade. A person cares about the year: how much
the whole account grew and how deep it fell on the way. This replays the signals day by day,
marking every open position to that day's close, and compares ways of running the account:

- how many equal slots (3, 5, 8)
- what idle slots hold (cash, or the S&P 500 ETF)
- how to buy (next open, or a limit 0.5 ATR below the signal close)

Research only: nothing here changes a frozen rule or a recommendation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

from config import BACKTEST_COMMISSION_PCT, BACKTEST_HALF_SPREAD_BPS, BACKTEST_SLIPPAGE_BPS
import strategy_evolution as se
from washout_risk_research import base_signals

OUT = Path('static/annual_return_research.json')
HOLD = 7
PERIODS = {'2017-11~2022 (탐색 구간)': (se.TRAIN_FOLDS[0][0], se.TRAIN_FOLDS[-1][1]), '2023~2024 (검증)': se.VALIDATION, '2025~ (최종 시험)': se.LOCKBOX}
SIDE_COST = BACKTEST_COMMISSION_PCT / 100.0 + (BACKTEST_SLIPPAGE_BPS + BACKTEST_HALF_SPREAD_BPS) / 10000.0
# The index ETF trades with almost no spread, so moving a slot in or out of it costs the commission only.
IDLE_SWITCH_COST = BACKTEST_COMMISSION_PCT / 100.0


def planned_trades(panel: dict, signals: np.ndarray, hold: int = HOLD, limit_atr: float | None = None) -> list[dict]:
    """Entry day, entry price and exit day of every signal that would have been filled."""
    o, l, c, atr = panel['open'], panel['low'], panel['close'], panel['atr']
    rows = []
    for i, j in zip(*np.nonzero(signals)):
        e, last = i + 1, i + hold
        if last >= len(c) or not np.isfinite(c[e:last + 1, j]).all() or not np.isfinite(o[e, j]):
            continue
        price = float(o[e, j])
        if limit_atr is not None:
            limit = float(c[i, j] - limit_atr * atr[i, j])
            if not l[e, j] <= limit:
                continue
            price = min(price, limit)
        rows.append({'day': int(i), 'col': int(j), 'entry_day': int(e), 'exit_day': int(last), 'entry_price': price})
    return rows


def run_account(panel: dict, trades: list[dict], priority: np.ndarray, slots: int, idle_daily: np.ndarray | None = None) -> np.ndarray:
    """Daily % change of an account split into equal slots, every position marked to the close.

    A slot that is not in a stock earns `idle_daily` (None = cash). Moving a slot between the idle
    asset and a stock pays the trading cost on both legs.
    """
    c = panel['close']
    days = len(c)
    by_entry: dict[int, list[dict]] = {}
    for t in trades:
        by_entry.setdefault(t['entry_day'], []).append(t)
    open_positions: list[dict] = []
    daily = np.zeros(days)
    switch_cost = IDLE_SWITCH_COST if idle_daily is not None else 0.0
    for d in range(days):
        total = 0.0
        new = sorted(by_entry.get(d, []), key=lambda t: -float(np.nan_to_num(priority[t['day'], t['col']], nan=-1e9)))
        for t in new:
            if len(open_positions) >= slots:
                break
            open_positions.append({**t, 'mark': t['entry_price'] * (1 + SIDE_COST) / (1 - switch_cost)})
        still = []
        for pos in open_positions:
            price = float(c[d, pos['col']])
            if pos['exit_day'] == d:
                price *= (1 - SIDE_COST) * (1 - switch_cost)
            total += price / pos['mark'] - 1.0
            pos['mark'] = float(c[d, pos['col']])
            if pos['exit_day'] > d:
                still.append(pos)
        idle_slots = slots - len(open_positions)
        if idle_daily is not None and np.isfinite(idle_daily[d]):
            total += idle_slots * float(idle_daily[d])
        open_positions = still
        daily[d] = total / slots
    return daily


def measure(daily: np.ndarray, dates: np.ndarray, rows: np.ndarray) -> dict:
    r = daily[rows]
    if not len(r):
        return {}
    equity = np.cumprod(1 + r)
    years = (np.datetime64(str(dates[rows][-1])) - np.datetime64(str(dates[rows][0]))).astype(int) / 365.25
    peak = np.maximum.accumulate(equity)
    return {'per_year_pct': round(float(equity[-1] ** (1 / years) - 1) * 100, 1) if years > 0 else None,
            'total_pct': round(float(equity[-1] - 1) * 100, 1), 'max_drawdown_pct': round(float((equity / peak - 1).min()) * 100, 1),
            'worst_day_pct': round(float(r.min()) * 100, 2)}


def by_year(daily: np.ndarray, dates: np.ndarray) -> dict:
    out = {}
    for year in sorted({str(d)[:4] for d in dates}):
        rows = np.array([str(d)[:4] == year for d in dates])
        out[year] = round(float(np.prod(1 + daily[rows]) - 1) * 100, 1)
    return out


def report_for(daily: np.ndarray, dates: np.ndarray, exposure: float | None = None) -> dict:
    everything = np.ones(len(dates), dtype=bool)
    return {'all_years': measure(daily, dates, everything), 'periods': {k: measure(daily, dates, (dates >= a) & (dates <= b)) for k, (a, b) in PERIODS.items()},
            'by_year_pct': by_year(daily, dates), 'avg_share_in_stocks_pct': exposure}


def exposure_of(panel: dict, trades: list[dict], priority: np.ndarray, slots: int) -> float:
    """Average share of the slots that hold a stock."""
    grouped: dict[int, list[dict]] = {}
    for t in trades:
        grouped.setdefault(t['entry_day'], []).append(t)
    exits: list[int] = []
    occupied = 0
    days = len(panel['close'])
    for d in range(days):
        for t in sorted(grouped.get(d, []), key=lambda t: -float(np.nan_to_num(priority[t['day'], t['col']], nan=-1e9))):
            if len(exits) < slots:
                exits.append(t['exit_day'])
        occupied += len(exits)
        exits = [x for x in exits if x > d]
    return round(occupied / days / slots * 100, 1)


def spy_daily(dates: np.ndarray) -> np.ndarray:
    import pandas as pd
    from market_data import load_price_history
    close = load_price_history('SPY', 'max')['Close'].astype(float)
    close.index = pd.DatetimeIndex(close.index).tz_localize(None) if getattr(close.index, 'tz', None) is not None else pd.DatetimeIndex(close.index)
    aligned = close.reindex(pd.DatetimeIndex([str(d) for d in dates])).ffill()
    return aligned.pct_change().fillna(0.0).to_numpy()


def build(ctx: se.Context, ledger: dict, spy: np.ndarray, extra_rules: dict | None = None) -> dict:
    panel, dates = ctx.panel, ctx.dates
    liquidity = ctx.features['dollar_volume_log']
    signal_sets = {'통과 규칙 2개': base_signals(ctx, ledger), **(extra_rules or {})}
    configs = {}
    for label, signals in signal_sets.items():
        for entry_label, limit in (('시가 매수', None), ('0.5 ATR 낮은 지정가', 0.5)):
            trades = planned_trades(panel, signals, HOLD, limit)
            for slots in (3, 5, 8):
                for idle_label, idle in (('남는 돈은 현금', None), ('남는 돈은 S&P 500 ETF', spy)):
                    daily = run_account(panel, trades, liquidity, slots, idle)
                    configs[f'{label} | {entry_label} | {slots}종목 | {idle_label}'] = {
                        'signals': label, 'entry': entry_label, 'slots': slots, 'idle': idle_label, 'trades_available': len(trades),
                        **report_for(daily, dates, exposure_of(panel, trades, liquidity, slots))}
    return {
        'version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'status': 'RESEARCH_ONLY', 'production_rules_mutated': False, 'frozen_rules_mutated': False,
        'hold_days': HOLD, 'first_date': str(dates[0]), 'last_date': str(dates[-1]),
        'benchmark_spy_buy_and_hold': report_for(spy, dates, 100.0), 'configs': configs,
        'limitations': [
            '매일 칸 크기를 다시 똑같이 맞춘다고 가정한 근사치입니다.',
            '지정가는 저가가 닿으면 체결된 것으로 봅니다.',
            '2017~2022년은 규칙을 찾는 데 쓴 구간이라 그 성적은 실제보다 좋게 나옵니다. 2025년 이후만 두 규칙 모두 처음 본 구간에 가깝지만, 그 구간에서 플러스였기 때문에 통과한 규칙이기도 합니다.',
            '가격이 남아 있지 않은 상장폐지 회사는 빠져 있습니다. 세금과 환전 비용은 넣지 않았습니다.',
        ],
    }


def main():
    ctx = se.Context(se.load_panel() if se.PANEL_CACHE.exists() else se.build_panel())
    report = build(ctx, json.loads(se.OUT.read_text(encoding='utf-8')), spy_daily(ctx.dates))
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    show = lambda r: (r['all_years']['per_year_pct'], r['all_years']['max_drawdown_pct'], [(v['per_year_pct'], v['max_drawdown_pct']) for v in r['periods'].values()], r['avg_share_in_stocks_pct'])
    print('SPY', show(report['benchmark_spy_buy_and_hold']), report['benchmark_spy_buy_and_hold']['by_year_pct'])
    for name, r in report['configs'].items():
        print(name, show(r))


if __name__ == '__main__':
    main()
