from datetime import date

import portfolio_candidate_capital_v2 as v2


def row(conviction=0.40, change=0.10, key='A'):
    return {
        'start_date': '2026-01-02',
        'end_date': '2026-01-05',
        'change': change,
        'risk_fraction': 0.10,
        'priority': conviction,
        '_v2_conviction': conviction,
        '_v2_tier': v2.conviction_tier(conviction),
        'key': key,
        'symbol': key,
        'strategy_id': 'donchian_55',
        'marks': [('2026-01-02', 1.00), ('2026-01-05', 1.0 + change)],
    }


def test_fixed_policy_set_and_tiers():
    ids = [x['id'] for x in v2.POLICIES]
    assert ids == ['v1_flat', 'tiered_all', 'selective', 'high_conviction']
    assert v2.conviction_tier(0.49) == 'low'
    assert v2.conviction_tier(0.50) == 'mid'
    assert v2.conviction_tier(0.75) == 'high'

    flat = v2.POLICIES[0]
    tiered = v2.POLICIES[1]
    selective = v2.POLICIES[2]
    concentrated = v2.POLICIES[3]
    assert v2.policy_multiplier(flat, 0.10) == 1.0
    assert v2.policy_multiplier(tiered, 0.40) == 0.5
    assert v2.policy_multiplier(tiered, 0.60) == 0.75
    assert v2.policy_multiplier(tiered, 0.90) == 1.0
    assert v2.policy_multiplier(selective, 0.40) == 0.0
    assert v2.policy_multiplier(concentrated, 0.70) == 0.0
    assert v2.policy_multiplier(concentrated, 0.90) == 1.0


def test_weighted_risk_budget_changes_position_without_boosting_above_v1():
    start, end = date(2026, 1, 1), date(2026, 1, 10)
    low = [row(0.40)]
    flat = v2.weighted_mtm_portfolio(low, start, end, 10, v2.POLICIES[0])
    tiered = v2.weighted_mtm_portfolio(low, start, end, 10, v2.POLICIES[1])
    selective = v2.weighted_mtm_portfolio(low, start, end, 10, v2.POLICIES[2])

    assert flat['trades'] == 1
    assert tiered['trades'] == 1
    assert selective['trades'] == 0
    assert flat['allocated_capital'] == 300000.0
    assert tiered['allocated_capital'] == 150000.0
    assert tiered['return'] < flat['return']
    assert max(p['high_mult'] for p in v2.POLICIES) <= 1.0


def test_outcome_diagnostics_are_result_only():
    good = row(0.90, 0.20, 'GOOD')
    good['marks'] = [('2026-01-02', 0.98), ('2026-01-03', 1.25), ('2026-01-05', 1.20)]
    bad = row(0.20, -0.10, 'BAD')
    bad['marks'] = [('2026-01-02', 0.95), ('2026-01-05', 0.90)]
    stats = v2.outcome_stats([good, bad])
    assert stats['signals'] == 2
    assert stats['win_rate_pct'] == 50.0
    assert stats['realized_2r_plus_pct'] == 50.0
    assert stats['realized_loss_08r_pct'] == 50.0
    assert stats['avg_mfe_close_r'] > 0
    assert stats['avg_mae_close_r'] < 0


def test_research_does_not_mutate_frozen_v1():
    source = open('portfolio_candidate_capital_v2.py', encoding='utf-8').read()
    assert 'priority_challenger_v1_state.json' not in source
    assert 'priority_challenger_v1_calibration.json' not in source
    assert 'submit_order' not in source
    assert "promotion_status': 'development_only_not_fresh_holdout'" in source
    assert "QUALITY_INTENSITY = 'loose'" in source


def main():
    test_fixed_policy_set_and_tiers()
    test_weighted_risk_budget_changes_position_without_boosting_above_v1()
    test_outcome_diagnostics_are_result_only()
    test_research_does_not_mutate_frozen_v1()
    print('candidate capital v2 PASS')


if __name__ == '__main__':
    main()
