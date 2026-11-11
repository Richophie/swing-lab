import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import strategy_evolution as se


def _panel(edge_pct=0.0, seed=3, symbols=60):
    """Random-walk panel. With edge_pct, days where feature x is high get an upward drift the next day."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range('2017-11-01', '2026-10-30')
    T = len(dates)
    x = rng.normal(size=(T, symbols)).astype(np.float32)
    noise = rng.normal(size=(T, symbols)).astype(np.float32)
    daily = rng.normal(0, 0.012, size=(T, symbols))
    boost = np.zeros((T, symbols))
    boost[2:] = np.where(x[:-2] > 0.8, edge_pct / 100.0, 0.0)  # signal day d lifts the close of d+2 (inside a 3-day hold)
    close = 50 * np.exp(np.cumsum(daily + boost, axis=0))
    open_ = np.vstack([close[:1], close[:-1]]) * (1 + rng.normal(0, 0.001, size=(T, symbols)))
    high = np.maximum(open_, close) * 1.004
    low = np.minimum(open_, close) * 0.996
    f32 = lambda a: a.astype(np.float32)
    return {
        'dates': np.array([d.strftime('%Y-%m-%d') for d in dates]), 'symbols': np.array([f'S{i:02d}' for i in range(symbols)]),
        'open': f32(open_), 'high': f32(high), 'low': f32(low), 'close': f32(close), 'atr': f32(close * 0.015),
        'feature_names': ['x', 'noise', 'dollar_volume_log'],
        'features': {'x': x, 'noise': noise, 'dollar_volume_log': np.full((T, symbols), 8.5, dtype=np.float32)},
    }


def _tiny(opens, highs, lows, closes, atr=1.0):
    col = lambda v: np.array(v, dtype=np.float32)[:, None]
    return {'open': col(opens), 'high': col(highs), 'low': col(lows), 'close': col(closes), 'atr': np.full((len(opens), 1), atr, dtype=np.float32)}


def _net(entry, exit_):
    c, f = se.BACKTEST_COMMISSION_PCT / 100, (se.BACKTEST_SLIPPAGE_BPS + se.BACKTEST_HALF_SPREAD_BPS) / 10000
    return (exit_ * (1 - f) * (1 - c) / (entry * (1 + f) * (1 + c)) - 1) * 100


def test_time_exit_uses_close_of_last_hold_day_and_needs_full_window():
    p = _tiny([100, 100, 101, 102, 103], [101, 101, 102, 103, 104], [99, 99, 100, 101, 102], [100, 100.5, 101.5, 102.5, 103.5])
    r = se.trade_returns(p, 3, None, None)[:, 0]
    assert math.isclose(r[0], _net(100, 102.5), rel_tol=1e-4)
    assert np.isnan(r[2]) and np.isnan(r[4])


def test_stop_beats_target_in_same_bar_and_gap_fills_at_open():
    both = _tiny([100, 100, 100], [100, 103, 100], [100, 97, 100], [100, 100, 100])
    assert math.isclose(se.trade_returns(both, 1, 2.0, 2.0)[0, 0], _net(100, 98), rel_tol=1e-4)
    gap = _tiny([100, 100, 95, 95], [100, 101, 96, 96], [100, 99, 94, 94], [100, 100, 95, 95])
    assert math.isclose(se.trade_returns(gap, 2, 2.0, None)[0, 0], _net(100, 95), rel_tol=1e-4)
    target = _tiny([100, 100, 100], [100, 103, 100], [100, 99.5, 100], [100, 100, 100])
    assert math.isclose(se.trade_returns(target, 1, 2.0, 2.0)[0, 0], _net(100, 102), rel_tol=1e-4)


def test_signals_count_a_persistent_condition_once_until_it_resets():
    panel = _panel()
    panel['features']['x'][:] = -5
    panel['features']['x'][1000:1010, 0] = 5
    panel['features']['x'][1012, 0] = 5   # only two quiet days: still the same setup
    panel['features']['x'][1020, 0] = 5   # quiet for longer than the hold: a new setup
    ctx = se.Context(panel)
    ctx.thresholds['x'] = np.zeros(len(se.QUANTILES))
    signals = ctx.signals({'conditions': [('x', '>=', 4)], 'hold': 3, 'stop_atr': None, 'target_atr': None})
    assert list(np.flatnonzero(signals[:, 0])) == [1000, 1020]


def test_thresholds_ignore_later_periods_and_holdout_symbols():
    base = _panel()
    changed = _panel()
    later = changed['dates'] > se.TRAIN_FOLDS[-1][1]
    changed['features']['x'][later] += 100
    holdout = se.Context(base).holdout_symbol
    changed['features']['x'][:, holdout] += 100
    assert np.allclose(se.Context(base).thresholds['x'], se.Context(changed).thresholds['x'])
    assert 5 < holdout.sum() < len(holdout) - 5


def test_required_t_rises_with_every_validation_look():
    assert round(se.required_t(1), 2) == 1.64
    assert se.required_t(10) > se.required_t(1) and se.required_t(1000) > 3.0


def test_planted_edge_is_found_and_survives_every_gate():
    ctx = se.Context(_panel(edge_pct=1.5))
    ledger = se.run(ctx, {}, seed=1, population=60, generations=6)
    assert ledger['champions'], ledger['runs'][-1]
    champion = ledger['champions'][0]
    assert any(c['feature'] == 'x' and c['op'] == '>=' for c in champion['rule']['conditions'])
    assert champion['lockbox_opened'] is True and champion['lockbox']['avg_return_pct'] > 0
    assert champion['portfolio']['total_return_pct'] > 0
    assert ledger['validation_looks'] == len(ledger['hall_of_fame'])
    assert ledger['research_only'] is True and ledger['production_rules_mutated'] is False


def test_pure_noise_produces_no_champion_and_keeps_lockbox_shut():
    ctx = se.Context(_panel(edge_pct=0.0, seed=11))
    ledger = {}
    for _ in range(2):
        ledger = se.run(ctx, ledger, population=60, generations=6)
    assert ledger['champions'] == []
    assert len(ledger['runs']) == 2 and ledger['validation_looks'] == len(ledger['hall_of_fame'])
    assert ledger['lockbox_looks'] <= 1
    assert ledger['gates']['next_validation_t_required'] == round(se.required_t(ledger['validation_looks'] + 1), 2)


def test_same_finalist_is_never_judged_twice():
    ctx = se.Context(_panel(edge_pct=1.5))
    ledger = se.run(ctx, {}, seed=1, population=60, generations=4)
    first = {h['key'] for h in ledger['hall_of_fame']}
    ledger = se.run(ctx, ledger, seed=1, population=60, generations=4)
    keys = [h['key'] for h in ledger['hall_of_fame']]
    assert len(keys) == len(set(keys)) and first <= set(keys)


def test_family_candidate_is_frozen_once_and_tracked_append_only():
    panel = _panel(edge_pct=1.5)
    ctx = se.Context(panel)
    genome = {'conditions': [('x', '>=', 6)], 'hold': 3, 'stop_atr': None, 'target_atr': None}
    ledger = {}
    first = se.freeze_family_candidate(ctx, ledger, 'demo', genome, 'test')
    again = se.freeze_family_candidate(ctx, ledger, 'demo', genome, 'test')
    assert first is again and ledger['lockbox_looks'] == 1 and ledger['validation_looks'] == 1
    assert first['passed_automatic_gate'] is False and set(first['stats']) >= {'validation', 'symbol_test', 'lockbox'}

    first['frozen_at'] = '2000-01-01'
    cut = 2000
    early = se.Context({**panel, 'dates': panel['dates'][:cut], **{k: panel[k][:cut] for k in ('open', 'high', 'low', 'close', 'atr')},
                        'features': {k: v[:cut] for k, v in panel['features'].items()}})
    early.thresholds = ctx.thresholds
    shadow = se.track_candidates(early, ledger, {})
    recorded = [(x['signal_date'], x['symbol']) for x in shadow['signals']]
    assert recorded and all(x['status'] == 'OPEN' and x['signal_date'] == panel['dates'][cut - 1] for x in shadow['signals'])
    assert shadow['live_trading_enabled'] is False

    shadow = se.track_candidates(ctx, ledger, shadow)   # later panel: outcomes mature, old rows are kept
    old = [x for x in shadow['signals'] if (x['signal_date'], x['symbol']) in recorded]
    assert len(old) == len(recorded) and all(x['status'] == 'CLOSED' for x in old)
    assert shadow['summary']['closed'] == len(recorded)


def test_membership_mask_follows_snapshots_and_gates_signals():
    from datetime import date
    panel = _panel()
    snapshots = [{'date': date(2017, 1, 1), 'members': ['S00', 'S01']}, {'date': date(2020, 1, 1), 'members': ['S01', 'S02']}]
    mask = se.membership_mask(panel['dates'], panel['symbols'], snapshots)
    before, after = int(np.searchsorted(panel['dates'], '2019-12-31')), int(np.searchsorted(panel['dates'], '2020-01-02'))
    assert list(mask[before, :3]) == [True, True, False] and list(mask[after, :3]) == [False, True, True]
    assert not mask[:, 3:].any()
    ctx = se.Context({**panel, 'member': mask})
    signals = ctx.signals({'conditions': [('x', '>=', 0)], 'hold': 3, 'stop_atr': None, 'target_atr': None})
    assert signals.any() and not signals[~mask].any()


def test_frozen_signals_use_absolute_thresholds_on_any_panel():
    ctx = se.Context(_panel())
    candidate = {'genome': {'conditions': [['x', '>=', 8]], 'hold': 3, 'stop_atr': None, 'target_atr': None},
                 'rule': {'conditions': [{'feature': 'x', 'op': '>=', 'threshold': 2.5}]}}
    genome, signals = se.frozen_signals(ctx, candidate)
    assert genome['conditions'] == [('x', '>=', 0)]
    assert signals.any() and (ctx.features['x'][signals] >= 2.5).all()


def test_pit_lite_separates_current_and_former_members():
    from datetime import date
    import evolution_pit_lite as pl
    panel = _panel(edge_pct=1.5)
    names = [str(s) for s in panel['symbols']]
    snapshots = [{'date': date(2017, 1, 1), 'members': names}, {'date': date(2026, 10, 1), 'members': names[:40]}]
    ledger = {'family_candidates': [{'name': 'demo', 'genome': {'conditions': [['x', '>=', 0]], 'hold': 3, 'stop_atr': None, 'target_atr': None},
                                     'rule': {'conditions': [{'feature': 'x', 'op': '>=', 'threshold': 0.8}]}}]}
    report = pl.build_report(panel, snapshots, ledger, requested=70)
    assert report['survivorship_free'] is False and report['status'] == 'DIAGNOSTIC_ONLY'
    assert report['coverage'] == {'requested_tickers': 70, 'tickers_with_prices': 60, 'former_members_since_2017': 20,
                                  'former_members_with_prices': 20, 'former_member_price_coverage_pct': 100.0}
    whole = report['candidates']['demo']['전체']
    assert whole['all_members']['trades'] == whole['still_in_index']['trades'] + whole['left_index']['trades']
    assert whole['left_index']['trades'] > 0 and whole['all_members']['avg_return_pct'] > 0


def test_ledger_refuses_a_different_split():
    try:
        se.run(se.Context(_panel()), {'split_version': 'other'}, population=20, generations=1)
    except RuntimeError:
        return
    raise AssertionError('expected a split mismatch error')


def test_saved_ledger_contract():
    path = Path('static/strategy_evolution.json')
    if not path.exists():
        return
    d = json.loads(path.read_text(encoding='utf-8'))
    assert d['research_only'] is True and d['production_rules_mutated'] is False
    assert d['split_version'] == se.SPLIT_VERSION
    assert d['validation_looks'] >= len(d['champions'])
    for c in d['champions']:
        assert c['passed_all'] is True and c['lockbox_opened'] is True


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
    print('strategy evolution PASS')
