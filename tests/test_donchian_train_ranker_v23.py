from datetime import date

import donchian_train_ranker_v23 as v23


def candidate(i, body=1.0):
    return {
        'strategy_id':'donchian_55',
        '_quality':80.0,
        'quality_features':{
            'breakout_atr':0.1+i*.001,
            'volume_ratio':1.0+i*.002,
            'close_position':0.7,
            'body_atr':body+i*.003,
            'sma200_slope_20d_pct':0.02,
            'distance_sma200_pct':0.1,
            'atr_pct':0.03,
        },
    }


def row(i):
    return {
        'start_date':f'2020-{1+(i//28)%12:02d}-{1+i%28:02d}',
        'end_date':f'2020-{1+(i//28)%12:02d}-{1+i%28:02d}',
        'change':(i%9-3)*0.01,
        'risk_fraction':0.05,
        'priority':2.0,
        '_audit_current_priority':2.0,
        'symbol':str(i),
        'key':str(i),
    }


def test_features_are_fixed_signal_day_fields():
    assert v23.FEATURES == ('breakout_atr','volume_ratio','close_position','body_atr','sma200_slope_20d_pct','distance_sma200_pct','atr_pct')
    assert len(v23.feature_vector(candidate(0))) == 7


def test_fit_uses_only_fully_closed_train_labels():
    pairs=[(candidate(i),row(i)) for i in range(140)]
    fold={'train_start':date(2020,1,1),'train_end':date(2020,12,31)}
    model=v23.fit_train_model(pairs,fold)
    assert model['n']==140
    assert len(model['beta'])==8
    assert len(model['train_predictions'])==140
    assert all(model['train_predictions'][i] <= model['train_predictions'][i+1] for i in range(139))
    pred=v23.model_prediction(candidate(141),model)
    assert isinstance(pred,float)


def test_no_hyperparameter_grid_or_v1_mutation():
    source=open('donchian_train_ranker_v23.py',encoding='utf-8').read()
    assert 'priority_challenger_v1_state.json' not in source
    assert 'priority_challenger_v1_calibration.json' not in source
    assert 'submit_order' not in source
    assert 'np.linalg.lstsq' in source
    assert "'hyperparameter_search': False" in source
    assert "'test_never_fits_model': True" in source
    assert "promotion_status': 'development_only_train_fitted_not_fresh_holdout'" in source


def main():
    test_features_are_fixed_signal_day_fields()
    test_fit_uses_only_fully_closed_train_labels()
    test_no_hyperparameter_grid_or_v1_mutation()
    print('donchian train ranker v2.3 PASS')


if __name__=='__main__':main()
