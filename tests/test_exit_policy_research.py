from datetime import datetime, timezone
from pathlib import Path
import json

import numpy as np
import pandas as pd

import exit_policy_research as er
import exit_challenger_shadow as shadow
from strategy_rules import trade_levels_from_row

COMMISSION, FRICTION = 0.001, 0.00075


def _candidate(path, *, stop=95.0, target=110.0, max_hold=3, date='2020-01-02'):
    return {
        'symbol': 'TEST', 'strategy_id': 'confirmed_pullback', 'signal_date': date, 'signal_close': 100.0,
        'buy_low': 99.5, 'buy_high': 100.5, 'atr': 2.0, 'stop': stop, 'target': target, 'max_hold': max_hold,
        'path': [[f'd{i}', *bar] for i, bar in enumerate(path)],
    }


def _net(raw_entry, raw_exit):
    paid = raw_entry * (1 + FRICTION) * (1 + COMMISSION)
    received = raw_exit * (1 - FRICTION) * (1 - COMMISSION)
    return (received / paid - 1) * 100


def test_entry_gap_guard_rejects_far_open():
    assert er.execute(_candidate([[104.0, 105, 103, 104]]), er.POLICIES['baseline'], COMMISSION, FRICTION) is None


def test_same_bar_target_and_stop_resolves_stop_first():
    trade = er.execute(_candidate([[100.0, 111, 94, 100]]), er.POLICIES['baseline'], COMMISSION, FRICTION)
    assert trade['reason'] == 'stop'
    assert round(trade['return_pct'], 6) == round(_net(100.0, 95.0), 6)


def test_gap_below_stop_fills_at_open_not_stop():
    trade = er.execute(_candidate([[100.0, 101, 99, 100], [93.0, 94, 92, 93]]), er.POLICIES['baseline'], COMMISSION, FRICTION)
    assert trade['reason'] == 'stop_gap'
    assert round(trade['return_pct'], 6) == round(_net(100.0, 93.0), 6)


def test_gap_above_target_fills_at_target():
    trade = er.execute(_candidate([[100.0, 101, 99, 100], [112.0, 113, 111, 112]]), er.POLICIES['baseline'], COMMISSION, FRICTION)
    assert trade['reason'] == 'target'
    assert round(trade['return_pct'], 6) == round(_net(100.0, 110.0), 6)


def test_time_exit_at_max_hold_close():
    path = [[100.0, 101, 99, 100.5], [100.5, 102, 100, 101], [101, 102, 100, 101.5], [101.5, 120, 101, 119]]
    trade = er.execute(_candidate(path), er.POLICIES['baseline'], COMMISSION, FRICTION)
    assert trade['reason'] == 'time' and trade['held_bars'] == 3
    assert round(trade['return_pct'], 6) == round(_net(100.0, 101.5), 6)


def test_wide_stop_and_long_hold_change_only_their_own_lever():
    path = [[100.0, 101, 96.5, 97], [97, 98, 96, 97.5], [97.5, 99, 97, 98], [98, 99, 97.5, 98.5], [98.5, 100, 98, 99.5], [99.5, 104, 99, 103]]
    base = er.execute(_candidate(path, stop=97.0), er.POLICIES['baseline'], COMMISSION, FRICTION)
    wide = er.execute(_candidate(path, stop=97.0), er.POLICIES['wide_stop_long_hold'], COMMISSION, FRICTION)
    assert base['reason'] == 'stop'
    assert wide['reason'] == 'time' and wide['held_bars'] == 6
    # A wider stop never tightens a canonical stop that is already further away.
    far = er.execute(_candidate(path, stop=90.0), er.POLICIES['wide_stop'], COMMISSION, FRICTION)
    assert far['reason'] == 'time' and far['held_bars'] == 3


def test_reach_target_uses_train_only_mfe():
    train = [_candidate([[100.0, 102 + i, 99, 101]], date=f'2020-01-{i + 1:02d}') for i in range(5)]
    late = [_candidate([[100.0, 150, 99, 101]], date='2026-01-05')]
    out = er.research_strategy(train + late, '2025-01-01', COMMISSION, FRICTION)
    assert out['train_median_mfe_atr'] == 2.0


def test_gate_needs_train_edge_and_positive_oos():
    base = {'trades': 100, 'avg_return_pct': 0.1}
    good_oos = {'trades': 40, 'avg_return_pct': 0.5, 'profit_factor': 1.4}
    assert er.passes(base, {'trades': 100, 'avg_return_pct': 0.4}, good_oos, {'trades': 40, 'avg_return_pct': 0.2})[0] is True
    assert er.passes(base, {'trades': 100, 'avg_return_pct': 0.15}, good_oos, {'trades': 40, 'avg_return_pct': 0.2})[0] is False
    assert er.passes(base, {'trades': 100, 'avg_return_pct': 0.4}, {'trades': 40, 'avg_return_pct': -0.1, 'profit_factor': 0.9}, {'trades': 40, 'avg_return_pct': -0.3})[0] is False
    assert er.passes(base, {'trades': 100, 'avg_return_pct': 0.4}, {'trades': 10, 'avg_return_pct': 2.0, 'profit_factor': 3.0}, {'trades': 10, 'avg_return_pct': 0.2})[0] is False


def test_split_keeps_forward_window_out_of_development_data():
    assert er.split_of('2026-08-14', '2024-01-01') == 'forward'
    assert er.split_of('2026-08-13', '2024-01-01') == 'oos'
    assert er.split_of('2023-12-29', '2024-01-01') == 'train'


def test_current_report_contract():
    report = er.build_report()
    assert report['research_only'] is True and report['production_rules_mutated'] is False
    assert set(report['strategies']) == set(er.PUBLIC_STRATEGIES)
    for row in report['strategies'].values():
        assert set(row['policies']) == set(er.POLICIES)
        assert row['train_pick'] != 'baseline'
        if row['train_pick_passes_oos']:
            assert row['policies'][row['train_pick']]['passes_gate'] is True


def test_shadow_atr_matches_canonical_buy_zone():
    row = pd.Series({'close': 100.0, 'atr': 2.5, 'recent_low': 96.0, 'recent_high': 108.0, 's20': 101.0, 's120': 99.0})
    levels = trade_levels_from_row(row, 'confirmed_pullback')
    assert np.isclose((levels['buy_high'] - levels['buy_low']) / shadow.BUY_ZONE_WIDTH_ATR, 2.5)


def test_shadow_only_takes_post_freeze_confirmed_pullback_and_keeps_short_paths_open():
    def item(strategy, date):
        return {'symbol': 'AAA', 'strategy_id': strategy, 'market_date': date, 'entry_low': 99.6, 'entry_high': 100.4,
                'stop': 96.0, 'target': 108.0, 'target_days_high': 8, 'sparkline': [99.0, 100.0]}
    history = {'days': [{'date': '2026-11-12', 'items': [item('confirmed_pullback', '2026-11-12'), item('rsi2_trend_reversion', '2026-11-12')]},
                        {'date': '2026-11-10', 'items': [item('confirmed_pullback', '2026-11-10')]}]}
    assert [c['signal_date'] for c in shadow.shadow_candidates(history)] == ['2026-11-12']

    index = pd.to_datetime(['2026-11-12', '2026-11-13', '2026-11-16'])
    frame = pd.DataFrame({'Open': [100, 100, 100.5], 'High': [101, 101, 102], 'Low': [99, 99, 100], 'Close': [100, 100.5, 101]}, index=index)
    report = shadow.build_report(history, {'AAA': frame}, datetime(2026, 11, 17, 12, tzinfo=timezone.utc))
    assert report['live_trading_enabled'] is False and report['production_mutation_enabled'] is False
    assert report['signals'] == 1 and report['sample_ready'] is False
    trade = report['trades'][0]
    assert trade['baseline']['status'] == 'OPEN' and trade['baseline']['held_bars'] == 2
    assert trade['challenger']['status'] == 'OPEN'


def test_shadow_does_not_touch_journal(tmp_path):
    before = shadow.HISTORY.read_bytes()
    shadow.build_report(json.loads(before.decode('utf-8')), {}, datetime.now(timezone.utc))
    assert shadow.HISTORY.read_bytes() == before
    assert Path('static/exit_policy_research.json').exists()


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn(Path('.')) if 'tmp_path' in fn.__code__.co_varnames[:fn.__code__.co_argcount] else fn()
    print('exit policy research PASS')
