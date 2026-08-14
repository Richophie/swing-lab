from datetime import date

import portfolio_sameday_rank_v21 as v21


def row(symbol, priority, change=0.10, start='2026-01-02', end='2026-01-05'):
    return {
        'start_date': start,
        'end_date': end,
        'change': change,
        'risk_fraction': 0.10,
        'priority': priority,
        'key': f'{symbol}|{priority}',
        'symbol': symbol,
        'strategy_id': 'donchian_55',
        'marks': [(start, 1.0), (end, 1.0 + change)],
    }


def test_rank_buckets_and_fixed_rule():
    assert v21.rank_bucket(1) == 'rank1'
    assert v21.rank_bucket(2) == 'rank2_3'
    assert v21.rank_bucket(3) == 'rank2_3'
    assert v21.rank_bucket(4) == 'rank4_plus'
    assert v21.RANK_RISK == {'rank1': 1.0, 'rank2_3': 0.75, 'rank4_plus': 0.5}
    assert max(v21.RANK_RISK.values()) <= 1.0


def test_same_day_rank_changes_capital_not_eligibility():
    rows = [
        row('A', 0.9),
        row('B', 0.8),
        row('C', 0.7),
        row('D', 0.6),
    ]
    result = v21.same_day_rank_portfolio(rows, date(2026, 1, 1), date(2026, 1, 10), 10)
    assert result['trades'] == 4
    assert result['trades_by_rank']['rank1'] == 1
    assert result['trades_by_rank']['rank2_3'] == 2
    assert result['trades_by_rank']['rank4_plus'] == 1
    # 10% stop risk means base 1% account risk is a 10% notional position.
    assert round(result['capital_by_rank']['rank1'], 2) == 300000.00
    assert round(result['capital_by_rank']['rank2_3'], 2) == 450000.00
    assert round(result['capital_by_rank']['rank4_plus'], 2) == 150000.00


def test_duplicate_symbol_is_removed_before_effective_rank():
    rows = [
        row('A', 0.95),
        row('A', 0.90),
        row('B', 0.80),
    ]
    result = v21.same_day_rank_portfolio(rows, date(2026, 1, 1), date(2026, 1, 10), 10)
    assert result['trades'] == 2
    assert result['reject_duplicate'] == 1
    assert result['trades_by_rank']['rank1'] == 1
    assert result['trades_by_rank']['rank2_3'] == 1


def test_v1_is_not_mutated_and_rule_is_posthoc():
    source = open('portfolio_sameday_rank_v21.py', encoding='utf-8').read()
    assert 'priority_challenger_v1_state.json' not in source
    assert 'priority_challenger_v1_calibration.json' not in source
    assert 'submit_order' not in source
    assert "promotion_status': 'posthoc_development_only_not_fresh_holdout'" in source
    assert "'grid_search': False" in source
    assert "'candidate_exclusion': False" in source


def main():
    test_rank_buckets_and_fixed_rule()
    test_same_day_rank_changes_capital_not_eligibility()
    test_duplicate_symbol_is_removed_before_effective_rank()
    test_v1_is_not_mutated_and_rule_is_posthoc()
    print('same-day rank v2.1 PASS')


if __name__ == '__main__':
    main()
