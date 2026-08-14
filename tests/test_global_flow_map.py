from __future__ import annotations

import pandas as pd

import global_flow_map as flow


def _frame(start=100.0, step=1.0, volume=1_000_000):
    idx = pd.date_range('2026-01-01', periods=30, freq='B')
    close = [start + step * i for i in range(30)]
    return pd.DataFrame({'Close': close, 'Volume': [volume] * 30}, index=idx)


def main():
    m = flow._metrics(_frame())
    assert m is not None
    assert m['return_5d_pct'] > 0
    assert m['return_20d_pct'] > m['return_5d_pct']
    assert m['volume_ratio_5v20'] == 1.0

    benchmark = {'return_5d_pct': 1.0, 'return_20d_pct': 2.0}
    rows = [
        {'ticker': 'A', 'return_5d_pct': 4.0, 'return_20d_pct': 8.0, 'volume_ratio_5v20': 1.5},
        {'ticker': 'B', 'return_5d_pct': 1.0, 'return_20d_pct': 2.0, 'volume_ratio_5v20': 1.0},
        {'ticker': 'C', 'return_5d_pct': -2.0, 'return_20d_pct': -4.0, 'volume_ratio_5v20': 0.7},
    ]
    ranked = flow._score_group(rows, benchmark)
    assert [x['ticker'] for x in ranked] == ['A', 'B', 'C']
    assert ranked[0]['flow_score'] > 0
    assert ranked[-1]['flow_score'] < 0
    assert ranked[0]['quadrant'] == 'leading'
    assert ranked[-1]['quadrant'] == 'lagging'

    pulse = flow._pulse(ranked, ranked)
    assert pulse['state'] in {'risk_on', 'risk_off', 'mixed'}
    assert len(pulse['top_sectors']) == 3
    print('global flow map PASS')


if __name__ == '__main__':
    main()
