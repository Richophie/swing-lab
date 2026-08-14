from __future__ import annotations

from datetime import date
from pathlib import Path

import yahoo_pit_lite_research as pit


def snapshots_fixture():
    return [
        {'date': date(2016, 12, 30), 'members': {'OLD', 'KEEP'}},
        {'date': date(2018, 1, 2), 'members': {'NEW', 'KEEP'}},
        {'date': date(2020, 1, 2), 'members': {'NEW', 'KEEP', 'LATE'}},
        {'date': date(2025, 12, 31), 'members': {'NEW', 'KEEP', 'LATE'}},
    ]


def test_membership_index_uses_latest_snapshot_without_future_lookahead():
    idx = pit.MembershipIndex(snapshots_fixture())
    assert idx.contains('OLD', date(2017, 6, 1))
    assert not idx.contains('NEW', date(2017, 6, 1))
    assert not idx.contains('OLD', date(2018, 1, 2))
    assert idx.contains('NEW', date(2018, 1, 2))
    assert idx.contains('LATE', date(2024, 1, 1))


def test_signal_and_next_open_must_both_be_historical_members():
    idx = pit.MembershipIndex(snapshots_fixture())
    rows = [
        {'symbol': 'OLD', 'signal_date': '2017-12-29', 'entry_date': '2018-01-02'},
        {'symbol': 'KEEP', 'signal_date': '2017-12-29', 'entry_date': '2018-01-02'},
        {'symbol': 'NEW', 'signal_date': '2018-01-02', 'entry_date': '2018-01-03'},
    ]
    kept = pit.membership_filter(rows, idx)
    assert [(x['symbol'], x['signal_date']) for x in kept] == [
        ('KEEP', '2017-12-29'),
        ('NEW', '2018-01-02'),
    ]


def test_historical_union_includes_name_removed_after_start():
    idx = pit.MembershipIndex(snapshots_fixture())
    u = idx.union(date(2017, 1, 1), date(2025, 12, 31))
    assert {'OLD', 'NEW', 'KEEP', 'LATE'} <= u


def test_comparison_delta_is_pit_minus_survivor_control():
    survivor = [
        {'fold': '2021', 'test': {'return_pct': 10.0, 'mdd_pct': -8.0, 'trades': 10, 'trades_per_year': 10.0, 'reject_cash': 1, 'avg_cash_pct': 20.0}},
        {'fold': '2022', 'test': {'return_pct': -5.0, 'mdd_pct': -10.0, 'trades': 12, 'trades_per_year': 12.0, 'reject_cash': 2, 'avg_cash_pct': 21.0}},
    ]
    full = [
        {'fold': '2021', 'test': {'return_pct': 8.0, 'mdd_pct': -9.0, 'trades': 14, 'trades_per_year': 14.0, 'reject_cash': 3, 'avg_cash_pct': 18.0}},
        {'fold': '2022', 'test': {'return_pct': -7.0, 'mdd_pct': -12.0, 'trades': 15, 'trades_per_year': 15.0, 'reject_cash': 4, 'avg_cash_pct': 19.0}},
    ]
    c = pit.compare_universes(survivor, full)
    assert c['per_fold'][0]['delta_pct'] == -2.0
    assert c['per_fold'][1]['delta_pct'] == -2.0
    assert c['pit_lite_worse_folds'] == 2
    assert c['pit_lite_better_folds'] == 0


def test_research_is_explicitly_isolated_from_production_and_forward_files():
    src = Path('yahoo_pit_lite_research.py').read_text(encoding='utf-8')
    assert "'promotion_status': 'DIAGNOSTIC_ONLY_NOT_SURVIVORSHIP_FREE'" in src
    assert "'production_main_picker_mutated': False" in src
    assert "'forward_challengers_mutated': False" in src
    assert "'live_trading_mutated': False" in src
    for frozen in ('priority_challenger_v1', 'priority_challenger_v2', 'priority_challenger_v3', 'priority_challenger_v4'):
        assert frozen not in src


def main():
    test_membership_index_uses_latest_snapshot_without_future_lookahead()
    test_signal_and_next_open_must_both_be_historical_members()
    test_historical_union_includes_name_removed_after_start()
    test_comparison_delta_is_pit_minus_survivor_control()
    test_research_is_explicitly_isolated_from_production_and_forward_files()
    print('Yahoo PIT-Lite deterministic tests PASS')


if __name__ == '__main__':
    main()
