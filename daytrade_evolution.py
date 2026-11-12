"""Very short holds: the same evolution search and gates, limited to one or two trading days.

- hold 1: buy at the next open, sell at that day's close (in and out the same session)
- hold 2: buy at the next open, sell at the following day's close

Both can be placed as orders in advance, so nobody has to watch the US session overnight.
True intraday timing is out of reach: free minute data only goes back days, not years.

This keeps its own ledger. The validation bar counts only the ideas judged here, and the
swing ledger is never touched. Research only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import strategy_evolution as se

OUT = Path('static/daytrade_evolution.json')
SPLIT_VERSION = 'daytrade-v1-pit-lite-2026-11-12'
HOLDS = (1, 2)
# Tighter than the swing search: a one-day move is small next to a 3 ATR stop.
STOPS_ATR = (None, 1.0, 2.0)
TARGETS_ATR = (None, 1.0, 2.0)


def configure() -> None:
    """Point the shared engine at the short-hold search space and ledger."""
    se.HOLDS, se.STOPS_ATR, se.TARGETS_ATR = HOLDS, STOPS_ATR, TARGETS_ATR
    se.SPLIT_VERSION, se.OUT = SPLIT_VERSION, OUT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runs', type=int, default=1)
    parser.add_argument('--population', type=int, default=se.POPULATION)
    parser.add_argument('--generations', type=int, default=se.GENERATIONS)
    args = parser.parse_args()
    configure()
    ctx = se.Context(se.load_panel() if se.PANEL_CACHE.exists() else se.build_panel())
    ledger = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {}
    for _ in range(args.runs):
        ledger = se.run(ctx, ledger, population=args.population, generations=args.generations)
        ledger['horizon'] = '1~2거래일 보유 (다음 날 시가 매수)'
        last = ledger['runs'][-1]
        print(json.dumps({'run': last['run'], 'scored': last['candidates_scored'], 'best_train': last['best_train_fitness'],
                          'finalists': len(last['finalists']), 'passed': len(last['passed']), 'failed_at': list(last['failed_at'].values())}, ensure_ascii=False), flush=True)
        OUT.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
