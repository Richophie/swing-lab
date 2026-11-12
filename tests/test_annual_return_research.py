import json
from pathlib import Path

import numpy as np

import annual_return_research as ar


def _panel(closes):
    c = np.array(closes, dtype=np.float64)[:, None]
    return {'open': c.copy(), 'high': c.copy(), 'low': c.copy(), 'close': c, 'atr': np.ones_like(c)}


def test_one_slot_account_matches_the_trade_return_after_costs():
    panel = _panel([100, 100, 110, 121, 121])
    trade = {'day': 0, 'col': 0, 'entry_day': 1, 'exit_day': 3, 'entry_price': 100.0}
    daily = ar.run_account(panel, [trade], np.ones((5, 1)), slots=1)
    expected = 121 * (1 - ar.SIDE_COST) / (100 * (1 + ar.SIDE_COST)) - 1
    assert abs(np.prod(1 + daily) - 1 - expected) < 1e-9 and daily[0] == 0 and daily[4] == 0


def test_idle_slots_earn_the_idle_asset_and_full_slots_ignore_new_signals():
    panel = _panel([100, 100, 100, 100, 100, 100])
    idle = np.full(6, 0.01)
    assert np.allclose(ar.run_account(panel, [], np.ones((6, 1)), 2, idle), 0.01)
    assert np.allclose(ar.run_account(panel, [], np.ones((6, 1)), 2, None), 0.0)
    trades = [{'day': 0, 'col': 0, 'entry_day': 1, 'exit_day': 4, 'entry_price': 100.0}, {'day': 1, 'col': 0, 'entry_day': 2, 'exit_day': 5, 'entry_price': 100.0}]
    assert ar.exposure_of(panel, trades, np.ones((6, 1)), 1) == round(4 / 6 * 100, 1)   # the second signal finds the slot taken


def test_limit_entry_needs_the_low_to_reach_the_limit():
    panel = _panel([100] * 12)
    signals = np.zeros((12, 1), dtype=bool); signals[0, 0] = True
    assert len(ar.planned_trades(panel, signals, 7, None)) == 1
    assert ar.planned_trades(panel, signals, 7, 0.5) == []
    panel['low'][1, 0] = 99.0
    assert ar.planned_trades(panel, signals, 7, 0.5)[0]['entry_price'] == 99.5


def test_measure_reports_yearly_growth_and_the_deepest_fall():
    dates = np.array(['2020-01-01', '2020-07-01', '2021-01-01'])
    m = ar.measure(np.array([0.0, -0.5, 1.0]), dates, np.ones(3, dtype=bool))
    assert m['total_pct'] == 0.0 and m['max_drawdown_pct'] == -50.0 and m['per_year_pct'] == 0.0


def test_saved_report_contract():
    path = Path('static/annual_return_research.json')
    if not path.exists():
        return
    d = json.loads(path.read_text(encoding='utf-8'))
    assert d['status'] == 'RESEARCH_ONLY' and d['frozen_rules_mutated'] is False
    assert len(d['configs']) % 12 == 0 and 'benchmark_spy_buy_and_hold' in d
    for c in d['configs'].values():
        assert set(c['periods']) == set(ar.PERIODS) and 0 <= c['avg_share_in_stocks_pct'] <= 100


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
    print('annual return research PASS')
