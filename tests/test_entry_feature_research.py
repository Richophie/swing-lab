import json
from pathlib import Path

import numpy as np
import pandas as pd

import entry_feature_pool as pool
import entry_feature_research as fr


def _prices(n=320, seed=7):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, n)))
    index = pd.bdate_range('2021-01-04', periods=n)
    open_ = close * (1 + rng.normal(0, 0.004, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    return pd.DataFrame({'Open': open_, 'High': high, 'Low': low, 'Close': close, 'Volume': rng.integers(1e6, 5e6, n).astype(float)}, index=index)


def test_features_do_not_look_ahead():
    d = _prices()
    full = pool.feature_frame(d)
    cut = pool.feature_frame(d.iloc[:250])
    day = d.index[249]
    assert set(full.columns) <= set(pool.FEATURES)
    pd.testing.assert_series_equal(full.loc[day], cut.loc[day])


def test_down_streak_counts_consecutive_lower_closes():
    d = _prices(60)
    d['Close'] = [100.0] * 55 + [99.0, 98.0, 97.0, 98.0, 97.5]
    streak = pool.feature_frame(d)['down_streak']
    assert list(streak.iloc[-5:]) == [1, 2, 3, 0, 1]


def _row(day, ret, value, sid='confirmed_pullback'):
    return {'symbol': 'AAA', 'strategy_id': sid, 'signal_date': day, 'return_pct': ret, 'reason': 'time', 'held_bars': 3, 'features': {'x': value, 'noise': 1.0}}


def test_tercile_cuts_come_from_train_only():
    assert fr.tercile_cuts([1.0] * 100) is None
    assert fr.tercile_cuts(list(range(10))) is None
    low, high = fr.tercile_cuts([float(i) for i in range(90)])
    assert (low, high) == (30.0, 60.0)
    assert [fr.bucket_of(v, (low, high)) for v in (29.9, 30.0, 59.9, 60.0, None)] == [0, 1, 1, 2, None]


def test_real_feature_passes_and_constant_feature_is_skipped():
    train = [_row(f'2020-{1 + i % 12:02d}-{1 + i % 27:02d}', 2.0 if i % 3 == 2 else -1.0, float(i % 3)) for i in range(600)]
    oos = [_row(f'2025-{1 + i % 12:02d}-{1 + i % 27:02d}', 2.0 if i % 3 == 2 else -1.0, float(i % 3)) for i in range(300)]
    out = fr.research_strategy(train + oos, '2024-01-01', {'x': 'X', 'noise': 'N'})
    assert 'noise' not in out['features']
    assert out['features']['x']['stable'] is True and out['features']['x']['higher_is_better'] is True
    assert out['train_pick']['feature'] == 'x' and out['train_pick']['shape'] == 'keep_best'
    assert out['train_pick_passes_oos'] is True


def test_train_only_pattern_is_vetoed_by_oos():
    train = [_row(f'2020-{1 + i % 12:02d}-{1 + i % 27:02d}', 2.0 if i % 3 == 2 else -1.0, float(i % 3)) for i in range(600)]
    oos = [_row(f'2025-{1 + i % 12:02d}-{1 + i % 27:02d}', -2.0 if i % 3 == 2 else 1.0, float(i % 3)) for i in range(300)]
    out = fr.research_strategy(train + oos, '2024-01-01', {'x': 'X'})
    assert out['features']['x']['stable'] is False
    assert out['train_pick_passes_oos'] is False


def test_forward_window_never_enters_development_splits():
    assert fr.split_of('2026-08-14', '2024-01-01') == 'forward'
    rows = [_row('2026-09-01', 5.0, 1.0), _row('2020-01-02', 1.0, 1.0), _row('2021-01-04', 1.0, 1.0)]
    assert fr.split_cutoff(rows) < '2026-08-14'


def test_rule_shadow_tags_post_freeze_items_without_lookahead():
    import entry_rule_shadow as shadow
    from datetime import datetime, timezone
    d = _prices(260)
    day = d.index[200].strftime('%Y-%m-%d')
    old_freeze = shadow.FREEZE_DATE
    shadow.FREEZE_DATE = day
    try:
        def item(sid, date, **extra):
            return {'symbol': 'AAA', 'strategy_id': sid, 'market_date': date, 'status_code': 'STOP', 'outcome_return_pct': -2.0, **extra}
        history = {'days': [{'date': day, 'items': [
            item('momentum_pullback', day),
            item('confirmed_pullback', day, entry_low=99.0, entry_high=101.0, target=109.0, stop=97.0),
            item('rsi2_trend_reversion', day),
            item('momentum_pullback', d.index[100].strftime('%Y-%m-%d')),
        ]}]}
        report = shadow.build_report(history, {'AAA': d}, datetime(2026, 12, 1, tzinfo=timezone.utc))
    finally:
        shadow.FREEZE_DATE = old_freeze
    assert report['live_trading_enabled'] is False and report['production_mutation_enabled'] is False
    assert [(t['strategy_id'], t['signal_date']) for t in report['trades']] == [('momentum_pullback', day), ('confirmed_pullback', day)]
    momentum, confirmed = report['trades']
    assert momentum['feature_value'] == round(float(pool.feature_frame(d.iloc[:201])['body_atr'].iloc[-1]), 4)
    assert confirmed['feature_value'] == 3.0 and confirmed['passes_rule'] is True
    assert report['strategies']['confirmed_pullback']['sample_ready'] is False


def test_saved_report_contract():
    d = json.loads(Path('static/entry_feature_research.json').read_text(encoding='utf-8'))
    assert d['research_only'] is True and d['production_rules_mutated'] is False
    assert d['train_end_exclusive'] < d['forward_start_date']
    for row in d['strategies'].values():
        assert row['candidate_rules_compared'] > 0
        if row['train_pick_passes_oos']:
            assert row['train_pick']['passes_gate'] is True


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
    print('entry feature research PASS')
