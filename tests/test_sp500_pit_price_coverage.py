from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

import sp500_pit_price_coverage as cov


def test_coverage_requires_warmup_and_near_removal():
    idx = pd.date_range('2019-01-01', periods=260, freq='B')
    s = pd.Series(range(260), index=idx, dtype=float)
    removal = idx[-1].date()
    result = cov.coverage_for_series(s, removal)
    assert result['rows'] == 260
    assert result['has_warmup'] is True
    assert result['near_removal'] is True
    assert result['usable_for_signal_replay'] is True


def test_missing_history_is_not_usable():
    result = cov.coverage_for_series(pd.Series(dtype=float), date(2020, 1, 1))
    assert result['has_any_history'] is False
    assert result['usable_for_signal_replay'] is False


def test_stale_history_near_removal_guard():
    idx = pd.date_range('2018-01-01', periods=260, freq='B')
    s = pd.Series(range(260), index=idx, dtype=float)
    result = cov.coverage_for_series(s, date(2020, 12, 31))
    assert result['has_warmup'] is True
    assert result['near_removal'] is False
    assert result['usable_for_signal_replay'] is False


def test_removed_map_uses_latest_removal_and_target_window():
    membership = {
        'target_start': '2017-01-01',
        'changes': [
            {'effective_date': '2016-01-01', 'removed': 'OLD'},
            {'effective_date': '2020-01-01', 'removed': 'AAA'},
            {'effective_date': '2022-01-01', 'removed': 'AAA'},
            {'effective_date': '2021-01-01', 'removed': 'BBB'},
        ],
    }
    m = cov._removal_map(membership)
    assert 'OLD' not in m
    assert m['AAA'] == date(2022, 1, 1)
    assert m['BBB'] == date(2021, 1, 1)


def test_probe_is_diagnostic_only_and_cannot_mutate_forward():
    src = Path('sp500_pit_price_coverage.py').read_text(encoding='utf-8')
    assert "'research_grade_pit_ready': False" in src
    assert "'production_main_picker_mutated': False" in src
    assert "'forward_challengers_mutated': False" in src
    for name in ('priority_challenger_v1', 'priority_challenger_v2', 'priority_challenger_v3', 'priority_challenger_v4'):
        assert name not in src


def main():
    test_coverage_requires_warmup_and_near_removal()
    test_missing_history_is_not_usable()
    test_stale_history_near_removal_guard()
    test_removed_map_uses_latest_removal_and_target_window()
    test_probe_is_diagnostic_only_and_cannot_mutate_forward()
    print('S&P 500 PIT free price coverage PASS')


if __name__ == '__main__':
    main()
