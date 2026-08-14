from __future__ import annotations

import opportunity_cost_rotation as rot


def _row(symbol='OLD'):
    return {
        'symbol': symbol,
        'end_date': '2026-02-20',
        'risk_fraction': 0.10,
        'change': 0.20,
        'marks': [
            ('2026-02-10', 0.98),
            ('2026-02-11', 1.00),
            ('2026-02-12', 1.08),
            ('2026-02-13', 1.24),
        ],
        '_open_factors': {
            '2026-02-12': 1.01,
            '2026-02-13': 1.10,
        },
    }


def main():
    pos = {'row': _row(), 'size': 1000.0, 'mark': 0.99, 'age_sessions': 6}
    positions = {1: pos}

    picked = rot.choose_victim(positions, '2026-02-12', rot.POLICIES['negative_after_5'])
    assert picked is not None
    assert picked[0] == 1
    assert picked[2] < 0

    young = {'row': _row(), 'size': 1000.0, 'mark': 0.99, 'age_sessions': 3}
    assert rot.choose_victim({1: young}, '2026-02-12', rot.POLICIES['negative_after_5']) is None

    winner = {'row': _row(), 'size': 1000.0, 'mark': 1.15, 'age_sessions': 12}
    assert rot.choose_victim({1: winner}, '2026-02-12', rot.POLICIES['stale_after_10']) is None

    stale = {'row': _row(), 'size': 1000.0, 'mark': 1.02, 'age_sessions': 12}
    picked2 = rot.choose_victim({1: stale}, '2026-02-12', rot.POLICIES['stale_after_10'])
    assert picked2 is not None
    assert picked2[2] <= 0.25

    regret = rot.regret_after_rotation(_row(), '2026-02-12', 1.01)
    assert regret['missed_mfe_from_sale_pct'] > 20
    assert regret['became_2r_winner_after_sale'] is True

    assert rot.POLICIES['natural']['rotate'] is False
    assert rot.BASE_RISK_PCT == 0.75
    assert rot.CAPACITY == 10
    print('opportunity-cost rotation PASS')


if __name__ == '__main__':
    main()
