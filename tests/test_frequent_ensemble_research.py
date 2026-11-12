import json
from pathlib import Path

import numpy as np

import frequent_ensemble_research as fe
import strategy_evolution as se
from tests.test_strategy_evolution import _panel


def test_pool_takes_every_account_objective_finalist_and_nothing_else():
    ctx = se.Context(_panel(edge_pct=1.5))
    rule = lambda q: {'genome': {'conditions': [['x', '>=', q]], 'hold': 3, 'stop_atr': None, 'target_atr': None},
                      'rule': {'conditions': [{'feature': 'x', 'op': '>=', 'threshold': float(ctx.thresholds['x'][q])}]}}
    ledger = {'hall_of_fame': [{**rule(8), 'objective': 'account'}, {**rule(7), 'objective': 'account'}, {**rule(0), 'objective': 'edge'}, rule(1)]}
    signals, returns, members = fe.pooled(ctx, ledger)
    assert members == 2
    wide = se.frozen_signals(ctx, rule(7))[1]
    assert signals.any() and not (signals & ~ctx.tradable).any()
    assert signals.sum() <= wide.sum() and np.isfinite(returns[signals & np.isfinite(ctx.returns(rule(7)['genome']))]).all()


def test_saved_report_contract():
    path = Path('static/frequent_ensemble_research.json')
    if not path.exists():
        return
    d = json.loads(path.read_text(encoding='utf-8'))
    box = d['segments']['lockbox']
    assert d['status'] == 'RESEARCH_ONLY' and d['lockbox_looks_spent'] == 1
    assert d['passes'] == (box['trades'] >= 100 and box['avg_return_pct'] > 0 and box['t_stat'] >= fe.MIN_T)
    ledger = json.loads(Path('static/strategy_evolution.json').read_text(encoding='utf-8'))
    assert any(t['name'] == 'account_objective_finalists_pool' for t in ledger.get('pooled_tests', []))


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
    print('frequent ensemble research PASS')
