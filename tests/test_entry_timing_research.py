import json
from pathlib import Path

import entry_timing_research as et

COMMISSION, FRICTION = 0.001, 0.00075


def _candidate(path, *, stop=94.0, target=110.0, max_hold=3):
    return {'symbol': 'TEST', 'strategy_id': 'confirmed_pullback', 'signal_date': '2020-01-02', 'signal_close': 100.0,
            'buy_low': 99.0, 'buy_high': 100.5, 'atr': 2.0, 'stop': stop, 'target': target, 'max_hold': max_hold,
            'path': [[f'd{i}', *bar] for i, bar in enumerate(path)]}


def test_next_open_matches_baseline_gap_guard():
    assert et.entry_fill(_candidate([[100.2, 101, 99.5, 100.5]]), 'next_open')[:2] == (0, 100.2)
    assert et.entry_fill(_candidate([[104.0, 105, 103, 104]]), 'next_open') is None


def test_limit_fills_at_limit_or_better_open_and_expires():
    touched = _candidate([[100.2, 101, 98.5, 100], [100, 101, 99.5, 100.5]])
    assert et.entry_fill(touched, 'limit_buy_low') == (0, 99.0, {'intraday_entry': True})
    gapped = _candidate([[100.2, 101, 99.5, 100], [98.0, 99, 97.5, 98.5]])
    assert et.entry_fill(gapped, 'limit_buy_low') == (1, 98.0, {})
    never = _candidate([[100.2, 101, 99.5, 100]] * 5)
    assert et.entry_fill(never, 'limit_buy_low') is None


def test_breakout_needs_a_later_bar_above_first_day_high():
    path = [[100, 101, 99.5, 100.5], [100.5, 100.9, 100, 100.6], [100.6, 102, 100.4, 101.8]]
    assert et.entry_fill(_candidate(path), 'breakout_confirm') == (2, 101.0, {'intraday_entry': True})
    assert et.entry_fill(_candidate([[100, 101, 99.5, 100.5]] + [[100, 100.9, 99.6, 100.2]] * 4), 'breakout_confirm') is None


def test_up_close_confirm_buys_the_open_after_the_confirming_bar():
    path = [[100, 100.5, 99, 99.5], [99.5, 101.5, 99.4, 101.2], [101.4, 102, 101, 101.8]]
    assert et.entry_fill(_candidate(path), 'up_close_confirm') == (2, 101.4, {})


def test_intraday_fill_ignores_same_bar_target_but_not_stop():
    hit_both = _candidate([[100.2, 111, 98.5, 100], [100, 101, 99.5, 100.5], [100.5, 101, 100, 100.8]])
    trade = et.simulate(hit_both, 'limit_buy_low', COMMISSION, FRICTION)
    assert trade['reason'] == 'time' and trade['held_bars'] == 3
    stopped = _candidate([[100.2, 101, 93.5, 94.5]])
    assert et.simulate(stopped, 'limit_buy_low', COMMISSION, FRICTION)['reason'] == 'stop'


def test_first_close_entry_can_gap_through_stop_next_morning():
    path = [[100.2, 101, 99.5, 100.4], [93.0, 93.5, 92, 93.2]]
    trade = et.simulate(_candidate(path), 'first_close', COMMISSION, FRICTION)
    assert trade['reason'] == 'stop_gap'


def test_judge_requires_fill_rate_and_positive_train():
    base = {'train': {'trades': 100, 'avg_return_pct': -0.5}, 'oos': {'trades': 50, 'avg_return_pct': 0.1}}
    oos = {'trades': 40, 'avg_return_pct': 0.6, 'profit_factor': 1.5}
    assert et.judge({'train': {'trades': 90, 'avg_return_pct': 0.3}, 'oos': oos, 'fill_rate': 0.7}, base)[0] is True
    assert et.judge({'train': {'trades': 90, 'avg_return_pct': -0.1}, 'oos': oos, 'fill_rate': 0.7}, base)[0] is False
    assert et.judge({'train': {'trades': 90, 'avg_return_pct': 0.3}, 'oos': oos, 'fill_rate': 0.2}, base)[0] is False


def test_saved_report_contract():
    d = json.loads(Path('static/entry_timing_research.json').read_text(encoding='utf-8'))
    assert d['research_only'] is True and d['production_rules_mutated'] is False
    for row in d['strategies'].values():
        assert set(row['entries']) == set(et.ENTRIES)
        assert row['train_pick'] != 'next_open'
    assert 'donchian_55' in d['signal_families']


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
    print('entry timing research PASS')
