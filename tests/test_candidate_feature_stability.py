import candidate_feature_stability as cfs


def test_feature_catalog_is_fixed_and_signal_day_only():
    assert cfs.FEATURES['confirmed_pullback']['elite_score'] == 'higher'
    assert cfs.FEATURES['sma200_20_squeeze']['ma_spread_pct'] == 'lower'
    assert cfs.FEATURES['donchian_55']['breakout_atr'] == 'higher'
    assert cfs.FEATURES['donchian_55']['atr_pct'] == 'diagnostic'


def test_train_cuts_and_bucket():
    xs = list(range(1, 13))
    low, high = cfs.cuts(xs)
    assert low < high
    assert cfs.bucket(low - 1, low, high) == 'low'
    assert cfs.bucket((low + high) / 2, low, high) == 'mid'
    assert cfs.bucket(high + 1, low, high) == 'high'
    assert cfs.cuts([1,2,3]) is None


def test_feature_value_reads_only_candidate_fields():
    candidate = {
        'elite_score': 88,
        'net_risk_reward': 1.4,
        'quality_features': {'breakout_atr': 0.7},
    }
    assert cfs.feature_value(candidate, 'elite_score') == 88.0
    assert cfs.feature_value(candidate, 'net_risk_reward') == 1.4
    assert cfs.feature_value(candidate, 'breakout_atr') == 0.7
    assert cfs.feature_value(candidate, 'missing') is None


def test_no_v1_mutation_or_production_write():
    source = open('candidate_feature_stability.py', encoding='utf-8').read()
    assert 'priority_challenger_v1_state.json' not in source
    assert 'priority_challenger_v1_calibration.json' not in source
    assert 'submit_order' not in source
    assert "promotion_status': 'diagnostic_only_not_fresh_holdout'" in source
    assert "'feature_cuts': '33/67 percentiles estimated on each fold TRAIN only'" in source


def main():
    test_feature_catalog_is_fixed_and_signal_day_only()
    test_train_cuts_and_bucket()
    test_feature_value_reads_only_candidate_fields()
    test_no_v1_mutation_or_production_write()
    print('candidate feature stability PASS')


if __name__ == '__main__':
    main()
