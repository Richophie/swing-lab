import json
import math
from pathlib import Path

import numpy as np

import washout_plan_research as wp


def _panel(opens, highs, lows, closes, atr=2.0):
    col = lambda v: np.array(v, dtype=np.float64)[:, None]
    return {'open': col(opens), 'high': col(highs), 'low': col(lows), 'close': col(closes), 'atr': np.full((len(opens), 1), atr)}


def _net(entry, exit_):
    c, f = wp.BACKTEST_COMMISSION_PCT / 100, (wp.BACKTEST_SLIPPAGE_BPS + wp.BACKTEST_HALF_SPREAD_BPS) / 10000
    return (exit_ * (1 - f) * (1 - c) / (entry * (1 + f) * (1 + c)) - 1) * 100


def _run(panel, entry, exit_):
    signals = np.zeros_like(panel['close'], dtype=bool); signals[0, 0] = True
    sma5 = np.full_like(panel['close'], 1e9)
    return wp.trades_for(panel, sma5, signals, entry, exit_)


def test_limit_order_fills_only_when_the_low_reaches_it_and_never_above_the_open():
    flat = [100] * 12
    touched = _panel(flat, [101] * 12, [100, 98.5] + [99] * 10, flat)
    trade = _run(touched, 'limit_0.5atr', 'hold_3d')[0]
    assert math.isclose(trade['return_pct'], _net(99, 100), rel_tol=1e-9) and trade['exit_day'] == 3
    assert _run(_panel(flat, [101] * 12, [99.5] * 12, flat), 'limit_0.5atr', 'hold_3d') == []
    gapped = _panel([100, 97] + [100] * 10, [101] * 12, [100, 96] + [99] * 10, flat)
    assert math.isclose(_run(gapped, 'limit_0.5atr', 'hold_3d')[0]['return_pct'], _net(97, 100), rel_tol=1e-9)


def test_exits_take_the_first_bounce_and_fall_back_to_the_last_day():
    closes = [100, 99, 98, 101, 102, 103, 104, 105, 106, 107, 108, 109]
    panel = _panel([100] * 12, [c + 0.5 for c in closes], [c - 1.5 for c in closes], closes)
    first = _run(panel, 'next_open', 'first_profit_close_7d')[0]
    assert first['exit_day'] == 3 and math.isclose(first['return_pct'], _net(100, 101), rel_tol=1e-9)
    target = _run(panel, 'next_open', 'target_1.5atr_7d')[0]
    assert target['exit_day'] == 5 and math.isclose(target['return_pct'], _net(100, 103), rel_tol=1e-9)
    assert _run(panel, 'next_open', 'hold_7d')[0]['exit_day'] == 7
    falling = [100 - k for k in range(12)]
    down = _panel(falling, [c + 0.2 for c in falling], [c - 1 for c in falling], falling)
    assert _run(down, 'next_open', 'first_profit_close_7d')[0]['exit_day'] == 7


def test_account_reuses_a_slot_only_after_its_exit():
    trade = lambda day, exit_day, r: {'day': day, 'col': 0, 'entry_day': day + 1, 'exit_day': exit_day, 'return_pct': r}
    liquidity = np.ones((20, 1))
    result = wp.account([trade(0, 5, 10.0), trade(2, 6, 10.0), trade(5, 9, -10.0)], liquidity, slots=1)
    assert result['trades_taken'] == 2 and result['total_return_pct'] == -1.0 and result['max_drawdown_pct'] == -10.0


def test_choose_needs_a_better_worst_fold_without_a_deeper_drawdown():
    seg = lambda r, dd: {'total_return_pct': r, 'max_drawdown_pct': dd}
    plan = lambda r, dd: {f: seg(r, dd) for f in wp.TRAIN}
    plans = {'|'.join(wp.BASE): plan(10, -15), 'a|x': plan(12, -17), 'b|x': plan(20, -30), 'c|x': plan(9, -5)}
    assert wp.choose(plans) == ['a|x']


def test_saved_report_contract():
    path = Path('static/washout_plan_research.json')
    if not path.exists():
        return
    d = json.loads(path.read_text(encoding='utf-8'))
    assert d['status'] == 'RESEARCH_ONLY' and d['production_rules_mutated'] is False and d['frozen_rules_mutated'] is False
    assert d['plans_tried'] == len(wp.ENTRIES) * len(wp.EXITS) and d['base_plan'] in d['plans']
    assert set(d['survivors']) <= {f['plan'] for f in d['finalists']} and len(d['finalists']) <= wp.FINALISTS


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
    print('washout plan research PASS')
