from pathlib import Path

import priority_challenger_v1 as v1
import priority_challenger_v2 as v2
import priority_challenger_v3 as v3
import priority_challenger_v4 as v4


def _item(symbol, priority, key=None):
    return {
        'pending': {
            'symbol': symbol,
            'challenger_priority': priority,
            'signal_key': key or f'2026-08-14|{symbol}|donchian_55',
        },
        'entry_date': '2026-08-17',
        'raw_open': 100.0,
        'entry': 100.1,
        'stop': 95.0,
        'target': None,
    }


def test_v4_is_forward_sibling_of_v2():
    assert v4.CHALLENGER_ID == 'priority_challenger_v4_same_day_rank1_full'
    assert v4.COMPARISON_BASELINE == v2.CHALLENGER_ID
    assert v4.FORWARD_START_DATE == v2.FORWARD_START_DATE == v3.FORWARD_START_DATE == '2026-08-14'
    assert v4.HYPOTHESIS_FREEZE_DATE == '2026-08-14'
    assert v4.TOP_RANK_RISK_BUDGET == v2.RISK_BUDGET == 0.0075
    assert v4.OTHER_RANK_RISK_BUDGET == 0.00375


def test_paths_are_isolated():
    assert v4.CALIBRATION.name == 'priority_challenger_v4_calibration.json'
    assert v4.STATE.name == 'priority_challenger_v4_state.json'
    assert v4.CALIBRATION not in {v1.CALIBRATION, v2.CALIBRATION, v3.CALIBRATION}
    assert v4.STATE not in {v1.STATE, v2.STATE, v3.STATE}


def test_same_day_rank_is_binary_and_deterministic():
    rows = v4._rank_day([
        _item('BBB', 0.70),
        _item('AAA', 0.90),
        _item('CCC', 0.70),
    ])
    assert [x['pending']['symbol'] for x in rows] == ['AAA', 'BBB', 'CCC']
    assert [x['entry_day_rank'] for x in rows] == [1, 2, 3]
    assert all(x['entry_day_candidate_count'] == 3 for x in rows)
    assert rows[0]['risk_budget_pct'] == 0.75
    assert rows[0]['rank_reduced'] is False
    assert rows[1]['risk_budget_pct'] == rows[2]['risk_budget_pct'] == 0.375
    assert rows[1]['rank_reduced'] is True and rows[2]['rank_reduced'] is True
    assert {x['risk_budget_pct'] for x in rows} == {0.75, 0.375}


def test_single_candidate_keeps_v2_risk():
    row = v4._rank_day([_item('AAA', 0.2)])[0]
    assert row['entry_day_rank'] == 1
    assert row['entry_day_candidate_count'] == 1
    assert row['risk_budget_pct'] == 0.75
    assert row['rank_reduced'] is False


def test_v4_does_not_mutate_production_or_add_parameter_search():
    src = Path('priority_challenger_v4.py').read_text(encoding='utf-8')
    assert 'submit_order' not in src
    assert 'TOP_RANK_RISK_BUDGET = 0.0075' in src
    assert 'OTHER_RANK_RISK_BUDGET = 0.00375' in src
    assert "'production_main_picker_mutated'] = False" in src
    assert "'live_orders_mutated'] = False" in src
    assert "'threshold_grid': False" in src
    assert 'for threshold in' not in src.lower()
    assert 'for multiplier in' not in src.lower()


def main():
    test_v4_is_forward_sibling_of_v2()
    test_paths_are_isolated()
    test_same_day_rank_is_binary_and_deterministic()
    test_single_candidate_keeps_v2_risk()
    test_v4_does_not_mutate_production_or_add_parameter_search()
    print('priority challenger v4 PASS')


if __name__ == '__main__':
    main()
