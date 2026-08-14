import strategy_selection_research as r


def test_donchian_quality_rewards_cleaner_signal():
    weak = {
        'strategy_id': 'donchian_55',
        'quality_features': {
            'breakout_atr': 0.05,
            'volume_ratio': 0.8,
            'close_position': 0.55,
            'body_atr': 0.1,
            'sma200_slope_20d_pct': 0.005,
        },
    }
    strong = {
        'strategy_id': 'donchian_55',
        'quality_features': {
            'breakout_atr': 1.0,
            'volume_ratio': 2.2,
            'close_position': 0.95,
            'body_atr': 1.0,
            'sma200_slope_20d_pct': 0.05,
        },
    }
    assert r.quality_score(strong) > r.quality_score(weak)


def test_sma_quality_rewards_tight_clean_breakout():
    noisy = {
        'strategy_id': 'sma200_20_squeeze',
        'quality_features': {
            'body_atr': 0.7,
            'ma_spread_pct': 0.035,
            'crosses_30': 2,
            'volume_ratio': 0.75,
            'ma_clearance_atr': 0.0,
            'sma200_slope_20d_pct': 0.001,
        },
    }
    clean = {
        'strategy_id': 'sma200_20_squeeze',
        'quality_features': {
            'body_atr': 1.5,
            'ma_spread_pct': 0.005,
            'crosses_30': 0,
            'volume_ratio': 1.5,
            'ma_clearance_atr': 0.8,
            'sma200_slope_20d_pct': 0.04,
        },
    }
    assert r.quality_score(clean) > r.quality_score(noisy)


def test_percentile_thresholds_are_distribution_only():
    xs = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert r.quantile(xs, 0.50) == 30.0
    assert r.quantile(xs, 0.70) == 38.0
    assert r.quantile(xs, 0.85) == 44.0


def test_research_families_are_frozen_challengers():
    ids = [x['id'] for x in r.FAMILIES]
    assert ids == ['donchian_core', 'donchian_momentum', 'confirmed_sma_donchian']
    assert [x[0] for x in r.INTENSITIES] == ['raw', 'loose', 'normal', 'strong']


if __name__ == '__main__':
    test_donchian_quality_rewards_cleaner_signal()
    test_sma_quality_rewards_tight_clean_breakout()
    test_percentile_thresholds_are_distribution_only()
    test_research_families_are_frozen_challengers()
    print('strategy selection research PASS')
