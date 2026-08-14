from pathlib import Path

import pandas as pd

import portfolio_flow_selection_diagnostic as flow


def test_peer_percentile_matches_flow_map_definition():
    frame = pd.DataFrame([[1.0, 2.0, 3.0], [5.0, 5.0, 1.0]], columns=['a', 'b', 'c'])
    got = flow._peer_percentile(frame)
    assert round(float(got.loc[0, 'a']), 6) == round(0.5 / 3.0, 6)
    assert round(float(got.loc[0, 'b']), 6) == round(1.5 / 3.0, 6)
    assert round(float(got.loc[0, 'c']), 6) == round(2.5 / 3.0, 6)
    # two equal leaders: below=1, equal=2 -> (1 + 1) / 3
    assert round(float(got.loc[1, 'a']), 6) == round(2.0 / 3.0, 6)
    assert round(float(got.loc[1, 'b']), 6) == round(2.0 / 3.0, 6)


def test_flow_buckets_are_frozen_to_existing_map_semantics():
    assert flow.flow_bucket(10.0) == 'strong'
    assert flow.flow_bucket(9.99) == 'neutral'
    assert flow.flow_bucket(-9.99) == 'neutral'
    assert flow.flow_bucket(-10.0) == 'weak'
    assert flow.flow_heat(35.0) == 'hot'
    assert flow.flow_heat(10.0) == 'warm'
    assert flow.flow_heat(0.0) == 'neutral'
    assert flow.flow_heat(-10.0) == 'cool'
    assert flow.flow_heat(-35.0) == 'cold'


def test_summary_reports_repetition_without_promoting():
    rows = []
    for year in range(2021, 2025):
        for i in range(6):
            rows.append({'fold': str(year), 'strategy_id': 'confirmed_pullback', 'flow_bucket': 'strong', 'flow_heat': 'warm', 'flow_score': 20.0, 'return_pct': 2.0 + i / 10, 'exit_reason': '목표가'})
            rows.append({'fold': str(year), 'strategy_id': 'confirmed_pullback', 'flow_bucket': 'weak', 'flow_heat': 'cool', 'flow_score': -20.0, 'return_pct': -1.0 + i / 20, 'exit_reason': '손절'})
    summary = flow.summarize(rows)
    assert summary['strong_minus_weak_mean_return_pp'] > 0
    assert summary['strong_minus_weak_median_return_pp'] > 0
    assert summary['strong_beats_weak_folds'] == 4
    assert summary['comparable_folds'] == 4
    assert summary['pattern'] == 'repeats_but_development_only'


def test_source_is_report_only_and_has_no_order_path():
    src = Path('portfolio_flow_selection_diagnostic.py').read_text(encoding='utf-8')
    assert "production_main_picker_mutated': False" in src
    assert "live_orders_mutated': False" in src
    assert "portfolio_filter_applied': False" in src
    assert "QUALITY_INTENSITY = 'loose'" in src
    assert 'FLOW_STRONG = 10.0' in src and 'FLOW_WEAK = -10.0' in src
    assert 'submit_order' not in src
    assert 'scanner' not in src


def main():
    test_peer_percentile_matches_flow_map_definition()
    test_flow_buckets_are_frozen_to_existing_map_semantics()
    test_summary_reports_repetition_without_promoting()
    test_source_is_report_only_and_has_no_order_path()
    print('portfolio Flow selection diagnostic PASS')


if __name__ == '__main__':
    main()
