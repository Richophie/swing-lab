import pandas as pd

from intraday_execution import first_buy_touch, first_exit_touch


def _bars(rows):
    idx = pd.DatetimeIndex([x[0] for x in rows], tz='America/New_York')
    return pd.DataFrame(
        {
            'Open': [x[1] for x in rows],
            'High': [x[2] for x in rows],
            'Low': [x[3] for x in rows],
            'Close': [x[4] for x in rows],
        },
        index=idx,
    )


def test_buy_touch_accepts_cheaper_open_above_stop():
    d = _bars([('2026-08-14 09:30', 98.0, 99.0, 97.5, 98.4)])
    hit = first_buy_touch(d, 99.0, 101.0, stop=95.0)
    assert hit['invalid'] is False
    assert hit['raw_price'] == 98.0
    assert hit['quality'] == '1m_open_at_or_better_than_buy'


def test_buy_touch_rejects_open_that_already_broke_stop():
    d = _bars([('2026-08-14 09:30', 94.0, 96.0, 93.5, 95.0)])
    hit = first_buy_touch(d, 99.0, 101.0, stop=95.0)
    assert hit['invalid'] is True
    assert hit['raw_price'] == 94.0


def test_buy_touch_waits_from_above_until_buy_ceiling():
    d = _bars(
        [
            ('2026-08-14 09:30', 103.0, 103.5, 102.2, 102.8),
            ('2026-08-14 09:31', 102.7, 102.8, 100.7, 101.2),
        ]
    )
    hit = first_buy_touch(d, 99.0, 101.0, stop=95.0)
    assert hit['invalid'] is False
    assert hit['raw_price'] == 101.0
    assert hit['timestamp'].startswith('2026-08-14T09:31')


def test_target_first_across_minutes_wins_even_if_stop_hits_later():
    d = _bars(
        [
            ('2026-08-14 10:15', 103.0, 106.2, 102.8, 105.8),
            ('2026-08-14 13:20', 96.0, 96.5, 94.5, 95.2),
        ]
    )
    hit = first_exit_touch(d, target=106.0, stop=95.0)
    assert hit['side'] == 'TARGET'
    assert hit['quality'] == '1m_first_touch'
    assert hit['timestamp'].startswith('2026-08-14T10:15')


def test_stop_first_across_minutes_wins_even_if_target_hits_later():
    d = _bars(
        [
            ('2026-08-14 10:15', 97.0, 98.0, 94.8, 95.4),
            ('2026-08-14 13:20', 104.0, 106.4, 103.8, 106.1),
        ]
    )
    hit = first_exit_touch(d, target=106.0, stop=95.0)
    assert hit['side'] == 'STOP'
    assert hit['quality'] == '1m_first_touch'


def test_same_one_minute_both_sides_stays_conservative():
    d = _bars([('2026-08-14 10:15', 100.0, 106.5, 94.5, 101.0)])
    hit = first_exit_touch(d, target=106.0, stop=95.0)
    assert hit['side'] == 'STOP'
    assert hit['quality'] == '1m_ambiguous_stop_fallback'


def main():
    test_buy_touch_accepts_cheaper_open_above_stop()
    test_buy_touch_rejects_open_that_already_broke_stop()
    test_buy_touch_waits_from_above_until_buy_ceiling()
    test_target_first_across_minutes_wins_even_if_stop_hits_later()
    test_stop_first_across_minutes_wins_even_if_target_hits_later()
    test_same_one_minute_both_sides_stays_conservative()
    print('intraday execution PASS')


if __name__ == '__main__':
    main()
