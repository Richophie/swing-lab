"""Free, partial survivorship check for frozen evolution candidates.

The evolution panel only holds companies that are large and liquid today, which
flatters any rule that buys beaten-down stocks. A truly survivorship-free test
needs prices of delisted companies, and those are not available for free.

What is free: community-maintained historical S&P 500 membership, plus Yahoo
prices for the former members that still trade. This module replays each frozen
candidate on "was an index member on the signal day" instead of "is big today",
and splits the result into companies still in the index and companies that have
since left it. Former members whose prices are gone are counted and reported,
never silently dropped.

Diagnostic only. It can weaken confidence in a candidate; it cannot prove one.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

import strategy_evolution as se

OUT = Path('static/evolution_pit_lite.json')
PERIODS = {'2017~2019': ('2017-11-01', '2019-12-31'), '2020~2022': ('2020-01-01', '2022-12-31'),
           '2023~2024': ('2023-01-01', '2024-12-31'), '2025~': ('2025-01-01', '2099-12-31')}


def evaluate_candidate(ctx: se.Context, candidate: dict, member: np.ndarray, current: np.ndarray) -> dict:
    genome, signals = se.frozen_signals(ctx, candidate)
    returns = ctx.returns(genome)
    signals = signals & member
    groups = {'all_members': np.ones(len(ctx.symbols), dtype=bool), 'still_in_index': current, 'left_index': ~current}
    table = {}
    for label, (start, end) in {'전체': (str(ctx.dates[0]), '2099-12-31'), **PERIODS}.items():
        rows = ctx.rows(start, end)
        years = se.Context.span_years(ctx.dates[rows]) if rows.sum() > 1 else 0.0
        table[label] = {name: se.segment_stats(returns, signals, rows, cols, years) for name, cols in groups.items()}
    return table


def build_report(panel: dict, snapshots: list[dict], ledger: dict, requested: int) -> dict:
    ctx = se.Context(panel)
    member = se.membership_mask(ctx.dates, ctx.symbols, snapshots)
    latest = set(snapshots[-1]['members'])
    current = np.array([str(s) in latest for s in ctx.symbols])
    ever = set().union(*[set(r['members']) for r in snapshots if r['date'].isoformat() >= '2017-01-01'])
    former = ever - latest
    have = {str(s) for s in ctx.symbols}
    return {
        'version': 1,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'status': 'DIAGNOSTIC_ONLY',
        'survivorship_free': False,
        'production_rules_mutated': False,
        'membership_source': 'community-maintained historical S&P 500 snapshots',
        'price_source': 'Yahoo Finance (companies whose prices are still published)',
        'coverage': {
            'requested_tickers': requested, 'tickers_with_prices': len(have),
            'former_members_since_2017': len(former), 'former_members_with_prices': len(former & have),
            'former_member_price_coverage_pct': round(len(former & have) / len(former) * 100.0, 1) if former else None,
        },
        'candidates': {c['name']: evaluate_candidate(ctx, c, member, current) for c in ledger.get('family_candidates') or []},
        'limitations': [
            '지수에서 빠진 뒤 상장폐지·합병된 회사는 가격이 무료로 남아 있지 않아 포함하지 못했습니다. 그 수를 coverage에 적었습니다.',
            'S&P 500 구성 이력은 커뮤니티가 정리한 자료이며 공식 자료가 아닙니다.',
            '이 결과는 후보에 대한 믿음을 낮출 수는 있어도 입증하지는 못합니다.',
        ],
    }


def main():
    from sp500_pit_diagnostic import fetch_snapshots

    snapshots = fetch_snapshots()
    panel = se.load_panel() if se.PANEL_CACHE.exists() else se.build_panel()
    ledger = json.loads(se.OUT.read_text(encoding='utf-8'))
    report = build_report(panel, snapshots, ledger, int(panel.get('requested_symbols', len(panel['symbols']))))
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({'coverage': report['coverage'], **{k: {g: (v['전체'][g].get('trades'), v['전체'][g].get('avg_return_pct')) for g in v['전체']} for k, v in report['candidates'].items()}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
