from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

import sp500_pit_diagnostic as diag


def fixture_tables():
    fillers = [f'X{i:03d}' for i in range(498)]
    current = pd.DataFrame({
        'Symbol': [*fillers, 'ADD1', 'ADD2'],
        'Security': [f'Company {i}' for i in range(500)],
    })
    columns = pd.MultiIndex.from_tuples([
        ('Effective Date', 'Effective Date'),
        ('Added', 'Ticker'),
        ('Added', 'Security'),
        ('Removed', 'Ticker'),
        ('Removed', 'Security'),
        ('Reason', 'Reason'),
    ])
    changes = pd.DataFrame([
        ['January 2, 2020', 'ADD2', 'Added Two', 'REM2', 'Removed Two', 'fixture'],
        ['January 5, 2026', 'ADD1', 'Added One', 'REM1', 'Removed One', 'fixture'],
    ], columns=columns)
    return [current, changes]


def test_table_detection_and_normalization():
    current, changes = diag.identify_tables(fixture_tables())
    cur = diag.normalize_current_table(current)
    chg = diag.normalize_changes_table(changes)
    assert len(cur) == 500
    assert cur[-1]['symbol'] == 'ADD2'
    assert [x['effective_date'] for x in chg] == ['2020-01-02', '2026-01-05']
    assert chg[0]['added'] == 'ADD2' and chg[0]['removed'] == 'REM2'


def test_reverse_reconstruction_restores_removed_names_without_count_drift():
    current, changes = diag.identify_tables(fixture_tables())
    current_symbols = {x['symbol'] for x in diag.normalize_current_table(current)}
    ledger = diag.normalize_changes_table(changes)
    as_of = date(2026, 8, 14)

    now_members = diag.members_on(as_of, current_symbols, ledger, as_of=as_of)
    assert 'ADD1' in now_members and 'ADD2' in now_members
    assert 'REM1' not in now_members and 'REM2' not in now_members
    assert len(now_members) == 500

    old = diag.members_on(date(2019, 12, 31), current_symbols, ledger, as_of=as_of)
    assert 'REM1' in old and 'REM2' in old
    assert 'ADD1' not in old and 'ADD2' not in old
    assert len(old) == 500


def test_build_is_diagnostic_only_even_when_membership_counts_are_plausible():
    payload = diag.build_from_tables(fixture_tables(), as_of=date(2026, 8, 14))
    assert payload['ready'] is True
    assert payload['status'] == 'DIAGNOSTIC_MEMBERSHIP_READY'
    assert payload['promotion_status'] == 'DIAGNOSTIC_ONLY_COMMUNITY_MEMBERSHIP'
    assert payload['current_member_count'] == 500
    assert min(x['member_count'] for x in payload['monthly_member_counts']) == 500
    assert max(x['member_count'] for x in payload['monthly_member_counts']) == 500
    assert {'REM1', 'REM2'} <= set(payload['historical_removed_tickers'])


def test_diagnostic_never_imports_or_mutates_forward_challengers():
    src = Path('sp500_pit_diagnostic.py').read_text(encoding='utf-8')
    for name in ('priority_challenger_v1', 'priority_challenger_v2', 'priority_challenger_v3', 'priority_challenger_v4'):
        assert name not in src
    assert "'production_main_picker_mutated'] = False" in src
    assert "'forward_challengers_mutated'] = False" in src


def main():
    test_table_detection_and_normalization()
    test_reverse_reconstruction_restores_removed_names_without_count_drift()
    test_build_is_diagnostic_only_even_when_membership_counts_are_plausible()
    test_diagnostic_never_imports_or_mutates_forward_challengers()
    print('S&P 500 PIT diagnostic PASS')


if __name__ == '__main__':
    main()
