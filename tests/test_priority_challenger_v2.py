from pathlib import Path

import priority_challenger_v1 as v1
import priority_challenger_v2 as v2


def test_v2_is_one_variable_ab_against_v1():
    assert v2.CHALLENGER_ID == 'priority_challenger_v2_capital075'
    assert v2.FREEZE_DATE == v1.FREEZE_DATE == '2026-08-13'
    assert v2.FORWARD_START_DATE == v1.FORWARD_START_DATE == '2026-08-14'
    assert v2.RISK_BUDGET == 0.0075
    assert v1.RISK_BUDGET == 0.01
    assert v2.RISK_BUDGET_PCT == 0.75
    assert v2.COMPARISON_BASELINE == 'priority_challenger_v1'


def test_paths_are_isolated_from_v1():
    assert v2.CALIBRATION.name == 'priority_challenger_v2_calibration.json'
    assert v2.STATE.name == 'priority_challenger_v2_state.json'
    assert v2.CALIBRATION != v1.CALIBRATION
    assert v2.STATE != v1.STATE


def test_wrapper_does_not_submit_orders_or_retune():
    src=Path('priority_challenger_v2.py').read_text(encoding='utf-8')
    assert 'submit_order' not in src
    assert "'only_changed_variable': 'risk_budget_pct'" in src
    assert "'same_quality_filter': True" in src
    assert "'same_priority_formula': True" in src
    assert "'same_execution_and_exits': True" in src
    assert 'RISK_BUDGET = 0.0075' in src


def main():
    test_v2_is_one_variable_ab_against_v1()
    test_paths_are_isolated_from_v1()
    test_wrapper_does_not_submit_orders_or_retune()
    print('priority challenger v2 PASS')


if __name__=='__main__':main()
