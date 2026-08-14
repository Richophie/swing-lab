from __future__ import annotations

from datetime import date
from pathlib import Path

import sp500_pit_diagnostic as diag


def fixture_csv() -> str:
    base = [f'X{i:03d}' for i in range(498)]
    old = ','.join([*base, 'REM1', 'REM2'])
    mid = ','.join([*base, 'REM1', 'ADD2'])
    latest = ','.join([*base, 'ADD1', 'ADD2'])
    return (
        'date,tickers\n'
        f'2016-12-30,"{old}"\n'
        f'2019-12-31,"{old}"\n'
        f'2020-01-02,"{mid}"\n'
        f'2025-12-31,"{mid}"\n'
        f'2026-01-05,"{latest}"\n'
        f'2026-08-01,"{latest}"\n'
    )


def test_parse_and_snapshot_lookup():
    rows = diag.parse_snapshot_csv(fixture_csv())
    assert len(rows) == 6
    old = diag.snapshot_on(date(2019, 12, 31), rows)
    assert 'REM1' in old and 'REM2' in old
    assert 'ADD1' not in old and 'ADD2' not in old
    latest = diag.snapshot_on(date(2026, 8, 13), rows)
    assert 'ADD1' in latest and 'ADD2' in latest
    assert len(latest) == 500


def test_build_tracks_noncurrent_last_seen_without_count_drift():
    rows = diag.parse_snapshot_csv(fixture_csv())
    payload = diag.build_from_snapshots(rows, as_of=date(2026, 8, 14))
    assert payload['ready'] is True
    assert payload['status'] == 'DIAGNOSTIC_MEMBERSHIP_READY'
    assert payload['promotion_status'] == 'DIAGNOSTIC_ONLY_COMMUNITY_MEMBERSHIP'
    assert payload['current_member_count'] == 500
    assert payload['source_coverage_end'] == '2026-08-01'
    assert min(x['member_count'] for x in payload['monthly_member_counts']) == 500
    assert max(x['member_count'] for x in payload['monthly_member_counts']) == 500
    assert {'REM1', 'REM2'} <= set(payload['historical_removed_tickers'])
    assert payload['ticker_last_seen']['REM2'] == '2019-12-31'
    assert payload['ticker_last_seen']['REM1'] == '2025-12-31'


def test_stale_source_is_not_ready_even_if_counts_look_good():
    rows = diag.parse_snapshot_csv(fixture_csv().replace('2026-08-01', '2026-01-06'))
    payload = diag.build_from_snapshots(rows, as_of=date(2026, 8, 14))
    assert payload['ready'] is False
    assert payload['coverage_checks']['monthly_member_count_plausible'] is True
    assert payload['coverage_checks']['source_fresh_enough'] is False


def test_diagnostic_never_imports_or_mutates_forward_challengers():
    src = Path('sp500_pit_diagnostic.py').read_text(encoding='utf-8')
    for name in ('priority_challenger_v1', 'priority_challenger_v2', 'priority_challenger_v3', 'priority_challenger_v4'):
        assert name not in src
    assert "'production_main_picker_mutated'] = False" in src
    assert "'forward_challengers_mutated'] = False" in src
    assert 'DIAGNOSTIC_ONLY_COMMUNITY_MEMBERSHIP' in src


def main():
    test_parse_and_snapshot_lookup()
    test_build_tracks_noncurrent_last_seen_without_count_drift()
    test_stale_source_is_not_ready_even_if_counts_look_good()
    test_diagnostic_never_imports_or_mutates_forward_challengers()
    print('S&P 500 PIT diagnostic PASS')


if __name__ == '__main__':
    main()
