import numpy as np
import pandas as pd

import indicator_library as lib
import strategy_evolution as se


def _frame(rows=420, seed=5):
    rng = np.random.default_rng(seed)
    close = 80 * np.exp(np.cumsum(rng.normal(0, 0.015, rows)))
    open_ = np.concatenate([close[:1], close[:-1]]) * (1 + rng.normal(0, 0.004, rows))
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, rows))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, rows))
    return pd.DataFrame({'Open': open_, 'High': high, 'Low': low, 'Close': close, 'Volume': rng.integers(1_000_000, 5_000_000, rows).astype(float)},
                        index=pd.bdate_range('2020-01-01', periods=rows))


def test_every_indicator_uses_only_data_up_to_that_day():
    d = _frame()
    full = lib.extra_features(d)
    cut = lib.extra_features(d.iloc[:330])
    assert set(full.columns) <= set(lib.LABELS)
    for name in full.columns:
        a, b = full[name].iloc[:330].to_numpy(), cut[name].to_numpy()
        assert np.allclose(a, b, equal_nan=True), name
        assert np.isfinite(full[name].iloc[-1]), name


def test_bounded_indicators_stay_in_range():
    f = lib.extra_features(_frame()).dropna()
    for name, low, high in (('stoch_k', 0, 100), ('mfi14', 0, 100), ('adx14', 0, 100), ('rsi5', 0, 100), ('donchian_pos20', 0, 1),
                            ('up_volume_ratio10', 0, 1), ('efficiency10', 0, 1), ('bb_width_rank120', 0, 1), ('days_since_high20', 0, 19)):
        assert f[name].min() >= low - 1e-9 and f[name].max() <= high + 1e-9, name
    assert (f['lower_wick_atr'] >= -1e-9).all() and (f['upper_wick_atr'] >= -1e-9).all()


def test_days_since_extreme_counts_back_from_today():
    highs = pd.Series([1.0] * 19 + [5.0, 2.0, 2.0])
    out = lib._bars_since_extreme(highs, 20, True)
    assert np.isnan(out.iloc[18]) and list(out.iloc[19:]) == [0.0, 1.0, 2.0]


def test_panel_features_rank_inside_members_only_and_measure_breadth():
    ret = np.array([[0.01, 0.02, 0.03, 0.50]] * 8, dtype=np.float32)
    features = {'ret5': ret, 'ret20': ret, 'ret60': ret, 'rsi2': np.full_like(ret, 5.0),
                'spy_ret20': np.full_like(ret, 0.01), 'spy_ret60': np.full_like(ret, 0.01),
                'dist_sma50': np.array([[0.1, -0.1, 0.1, 0.1]] * 8, dtype=np.float32), 'dist_sma200': np.full_like(ret, 0.1)}
    member = np.array([[True, True, True, False]] * 8)
    lib.add_panel_features(features, member)
    assert np.allclose(features['rank_ret20'][0, :3], [1 / 3, 2 / 3, 1.0]) and np.isnan(features['rank_ret20'][0, 3])
    assert np.allclose(features['breadth_sma50'], 2 / 3) and np.allclose(features['breadth_oversold'], 1.0)
    assert np.allclose(features['rs_spy20'][0], [0.0, 0.01, 0.02, 0.49])
    assert np.isnan(features['breadth_change5'][4, 0]) and features['breadth_change5'][5, 0] == 0


def test_market_features_work_without_vix():
    spy = _frame()
    assert 'vix' not in lib.market_features(spy, None)
    with_vix = lib.market_features(spy, pd.DataFrame({'Close': np.linspace(15, 30, len(spy))}, index=spy.index))
    assert {'vix', 'vix_vs_sma20', 'vix_ret5', 'spy_rsi2'} <= set(with_vix.columns)


def test_evolution_features_have_a_label_each():
    names = set(se.evolution_features(_frame()).columns)
    assert len(names) > 55 and names <= set(se.feature_labels())


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
    print('indicator library PASS')
