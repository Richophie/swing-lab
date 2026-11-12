import json
from pathlib import Path

import numpy as np

import earnings_calendar as ec
import earnings_research as er


def test_acceptance_time_decides_the_first_session_that_can_react():
    sessions = ['2026-10-26', '2026-10-27', '2026-10-28']
    assert ec.announcement_day('2026-10-27T11:30:23.000Z') == ('2026-10-27', False)      # 7:30 in New York, before the open
    assert ec.announcement_day('2019-07-18T20:40:43.000Z') == ('2019-07-18', True)       # 16:40 summer time, after the close
    assert ec.announcement_day('2026-01-28T20:59:00.000Z') == ('2026-01-28', False)      # 15:59 winter time
    assert ec.announcement_day('2026-03-09T20:05:00.000Z') == ('2026-03-09', True)       # summer time has begun
    assert ec.reaction_day('2026-10-27', False, sessions) == '2026-10-27'
    assert ec.reaction_day('2026-10-27', True, sessions) == '2026-10-28'
    assert ec.reaction_day('2026-10-25', False, sessions) == '2026-10-26'                # filed on a Sunday
    assert ec.reaction_day('2026-10-28', True, sessions) is None


def test_only_results_filings_count_and_a_contact_is_required(monkeypatch):
    block = {'form': ['8-K', '8-K', '10-Q'], 'items': ['2.02,9.01', '5.02', ''], 'acceptanceDateTime': ['2026-10-27T11:30:00.000Z'] * 3}
    assert ec.earnings_filings(block) == [('2026-10-27', False)]
    monkeypatch.delenv(ec.CONTACT_ENV, raising=False)
    try:
        ec.headers()
    except RuntimeError:
        pass
    else:
        raise AssertionError('expected a missing-contact error')
    monkeypatch.setenv(ec.CONTACT_ENV, 'someone@example.com')
    assert 'someone@example.com' in ec.headers()['User-Agent']
    import re
    assert not re.search(r'[\w.]+@[\w-]+\.\w+', Path('earnings_calendar.py').read_text(encoding='utf-8'))   # no address stored in the code


def test_day_counters_look_forward_and_back_without_crossing_symbols():
    matrix = np.zeros((6, 2), dtype=bool)
    matrix[2, 0] = True; matrix[4, 1] = True
    assert list(er.days_until_next(matrix)[:, 0]) == [2, 1, 0, 10_000, 10_000, 10_000]
    assert list(er.days_since_last(matrix)[:, 0]) == [10_000, 10_000, 0, 1, 2, 3]
    assert list(er.days_until_next(matrix)[:, 1]) == [4, 3, 2, 1, 0, 10_000]


def test_saved_reports_contract():
    calendar, report = Path('static/earnings_dates.json'), Path('static/earnings_research.json')
    if calendar.exists():
        d = json.loads(calendar.read_text(encoding='utf-8'))
        assert d['symbols_with_dates'] == len(d['dates']) and '@' not in calendar.read_text(encoding='utf-8')
        assert all(days == sorted(set(days)) for days in d['dates'].values())
    if report.exists():
        d = json.loads(report.read_text(encoding='utf-8'))
        assert d['status'] == 'RESEARCH_ONLY' and d['frozen_rules_mutated'] is False
        assert set(d['drift']['holding_up']) == {k for k, v in d['drift']['setups'].items() if v['holds_up']}


if __name__ == '__main__':
    print('run with pytest')
