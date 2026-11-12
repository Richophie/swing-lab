"""Many weak rules as one: does the crowd hold up where no single rule did?

The search that climbs yearly account return produced finalists that each earned a little in
2023-2024 but not enough to be told apart from luck one by one. Their signals are pooled here
into one stream and judged as a single idea on 2025+, which none of them has been shown.

The pool is fixed before looking: every finalist of the account-objective runs, whatever its
validation result, so nothing is picked with hindsight. One lockbox look is spent.
Research only: nothing here changes a frozen rule or a recommendation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

import annual_return_research as ar
import strategy_evolution as se
from public_playbook_bench import fresh
from washout_risk_research import SEGMENTS, base_signals

OUT = Path('static/frequent_ensemble_research.json')
HOLD = 7
MIN_T = 2.0


def pooled(ctx: se.Context, ledger: dict) -> tuple[np.ndarray, np.ndarray, int]:
    """Union of the pool's signals and, per signal, the return under the plan of the first rule that fired."""
    members = [h for h in ledger.get('hall_of_fame') or [] if h.get('objective') == 'account']
    signals = np.zeros(ctx.panel['close'].shape, dtype=bool)
    returns = np.full(ctx.panel['close'].shape, np.nan, dtype=np.float32)
    for entry in members:
        genome, mine = se.frozen_signals(ctx, entry)
        r = ctx.returns(genome)
        new = mine & ~signals
        returns[new] = r[new]
        signals |= mine
    keep = fresh(signals, HOLD)
    return keep, returns, len(members)


def stats_by_segment(ctx: se.Context, signals: np.ndarray, returns: np.ndarray) -> dict:
    everything = np.ones(len(ctx.symbols), dtype=bool)
    return {name: se.segment_stats(returns, signals, ctx.rows(*span), everything, se.Context.span_years(ctx.dates[ctx.rows(*span)])) for name, span in SEGMENTS.items()}


def build(ctx: se.Context, ledger: dict, spy: np.ndarray) -> dict:
    signals, returns, members = pooled(ctx, ledger)
    champions = base_signals(ctx, ledger)
    segments = stats_by_segment(ctx, signals, returns)
    box = segments['lockbox']
    liquidity = ctx.features['dollar_volume_log']
    accounts = {}
    for label, mask in (('통과 규칙 2개만', champions), ('묶음만', signals), ('통과 규칙 2개 + 묶음', fresh(champions | signals, HOLD))):
        trades = ar.planned_trades(ctx.panel, mask, HOLD)
        for slots in (5, 8):
            daily = ar.run_account(ctx.panel, trades, liquidity, slots)
            accounts[f'{label} | {slots}종목'] = ar.report_for(daily, ctx.dates, ar.exposure_of(ctx.panel, trades, liquidity, slots))
    return {
        'version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'status': 'RESEARCH_ONLY', 'production_rules_mutated': False, 'frozen_rules_mutated': False,
        'pool': 'every finalist of the account-objective evolution runs, regardless of its validation result', 'pool_size': members,
        'lockbox_looks_spent': 1, 'pass_rule': f'lockbox 평균이 플러스이고 날짜 묶음 t값이 {MIN_T} 이상',
        'segments': segments, 'overlap_with_passing_rules': round(se.overlap(se.footprint(signals), se.footprint(champions)), 2),
        'passes': bool(box.get('trades', 0) >= 100 and box['avg_return_pct'] > 0 and box['t_stat'] >= MIN_T),
        'accounts_plain_7_day_hold': accounts, 'benchmark_spy_buy_and_hold': ar.report_for(spy, ctx.dates, 100.0),
        'limitations': [
            '묶음의 2023~2024년 성적은 규칙마다 이미 한 번씩 본 뒤라 새 증거가 아닙니다. 2025년 이후만 처음 본 구간입니다.',
            '계좌 수익은 모든 신호를 7거래일 뒤 종가에 파는 것으로 단순화했습니다.',
            '가격이 남아 있지 않은 상장폐지 회사는 빠져 있습니다.',
        ],
    }


def main():
    ctx = se.Context(se.load_panel() if se.PANEL_CACHE.exists() else se.build_panel())
    report = build(ctx, json.loads(se.OUT.read_text(encoding='utf-8')), ar.spy_daily(ctx.dates))
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print('pool', report['pool_size'], 'overlap', report['overlap_with_passing_rules'], 'PASSES', report['passes'])
    for name, s in report['segments'].items():
        print(name, s.get('trades'), s.get('avg_return_pct'), s.get('win_rate_pct'), s.get('t_stat'), s.get('trades_per_year'))
    show = lambda r: (r['all_years']['per_year_pct'], r['all_years']['max_drawdown_pct'], [(v['per_year_pct'], v['max_drawdown_pct']) for v in r['periods'].values()], r['avg_share_in_stocks_pct'])
    for name, r in report['accounts_plain_7_day_hold'].items():
        print(name, show(r), r['by_year_pct'])


if __name__ == '__main__':
    main()
