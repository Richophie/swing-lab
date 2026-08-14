from datetime import date

import portfolio_walkforward_research as wf


def test_folds_are_four_year_train_next_year_test():
    folds = wf.folds_for(date(2017, 6, 9), date(2026, 8, 13))
    assert folds[0]['id'] == '2021'
    assert str(folds[0]['train_start']) == '2017-06-09'
    assert str(folds[0]['train_end']) == '2020-12-31'
    assert str(folds[0]['test_start']) == '2021-01-01'
    assert str(folds[0]['test_end']) == '2021-12-31'
    assert folds[-1]['id'] == '2026'
    assert str(folds[-1]['train_start']) == '2022-01-01'
    assert str(folds[-1]['train_end']) == '2025-12-31'
    assert str(folds[-1]['test_end']) == '2026-08-13'
    assert len(folds) == 6


def test_summary_grades_repeated_positive_oos():
    rows=[]
    for year in range(2021,2027):
        rows.append({
            'test_start': f'{year}-01-01',
            'test_end': f'{year}-12-31' if year < 2026 else '2026-08-13',
            'selected_intensity': 'raw',
            'test': {
                'return_pct': 8.0,
                'mdd_pct': -12.0,
                'trades': 20,
            },
        })
    s=wf.summarize(rows)
    assert s['positive_folds'] == 6
    assert s['positive_fold_ratio'] == 1.0
    assert s['median_test_return_pct'] == 8.0
    assert s['worst_fold_mdd_pct'] == -12.0
    assert s['total_test_trades'] == 120
    assert s['grade'] == 'A'


def test_walkforward_uses_frozen_challenger_families():
    ids=[x['id'] for x in wf.selection.FAMILIES]
    assert ids == ['donchian_core','donchian_momentum','confirmed_sma_donchian']
    assert wf.TRAIN_YEARS == 4
    assert wf.FIRST_TEST_YEAR == 2021


def test_no_test_outcome_used_by_threshold_builder():
    import inspect
    source=inspect.getsource(wf.thresholds_for)
    for forbidden in ('change','return_pct','mdd','test'):
        assert forbidden not in source
    assert '_quality' in source
    assert 'train_start' in source and 'train_end' in source


if __name__ == '__main__':
    test_folds_are_four_year_train_next_year_test()
    test_summary_grades_repeated_positive_oos()
    test_walkforward_uses_frozen_challenger_families()
    test_no_test_outcome_used_by_threshold_builder()
    print('portfolio walk-forward PASS')
