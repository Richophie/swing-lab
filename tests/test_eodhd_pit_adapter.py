from __future__ import annotations

from datetime import date
from pathlib import Path

import eodhd_pit_adapter as eod


def fixture_components():
    return {
        '0': {
            'Code': 'AAPL', 'Name': 'Apple', 'StartDate': '1982-11-30', 'EndDate': None,
            'IsActiveNow': 1, 'IsDelisted': 0,
        },
        '1': {
            'Code': 'ATVI', 'Name': 'Activision Blizzard', 'StartDate': '2015-08-31', 'EndDate': '2023-10-18',
            'IsActiveNow': 0, 'IsDelisted': 1,
        },
        '2': {
            'Code': 'TWTR', 'Name': 'Twitter', 'StartDate': '2018-06-07', 'EndDate': '2022-11-01',
            'IsActiveNow': 0, 'IsDelisted': 1,
        },
    }


def test_parse_historical_components_and_vendor_symbol():
    rows = eod.parse_historical_components(fixture_components())
    assert len(rows) == 3
    atvi = next(x for x in rows if x.code == 'ATVI')
    assert atvi.start_date == date(2015, 8, 31)
    assert atvi.end_date == date(2023, 10, 18)
    assert atvi.is_delisted is True
    assert atvi.vendor_symbol == 'ATVI.US'


def test_parse_nested_historical_components():
    rows = eod.parse_historical_components({'HistoricalTickerComponents': fixture_components()})
    assert {x.code for x in rows} == {'AAPL', 'ATVI', 'TWTR'}


def test_eod_rows_and_coverage():
    payload = [
        {'date': f'2023-01-{day:02d}', 'open': 10, 'high': 11, 'low': 9, 'close': 10, 'adjusted_close': 10, 'volume': 1000}
        for day in range(1, 29)
    ]
    rows = eod.parse_eod_rows(payload)
    assert len(rows) == 28
    coverage = eod.eod_coverage(rows * 8, date(2023, 1, 28))
    # Duplicated fixture rows deliberately provide >205 valid records and the expected end date.
    assert coverage['has_warmup'] is True
    assert coverage['near_end'] is True
    assert coverage['usable'] is True


def test_probe_selection_prefers_delisted_former_components():
    rows = eod.parse_historical_components(fixture_components())
    chosen = eod.choose_probe_components(rows, 2)
    assert len(chosen) == 2
    assert all(x.end_date is not None for x in chosen)
    assert all(x.is_delisted for x in chosen)
    assert chosen[0].end_date >= chosen[1].end_date


def test_no_token_means_no_silent_vendor_or_production_fallback():
    try:
        eod.EODHDPITClient('')
        raise AssertionError('missing token should fail')
    except ValueError as exc:
        assert eod.TOKEN_ENV in str(exc)
    src = Path('eodhd_pit_adapter.py').read_text(encoding='utf-8')
    for forbidden in ('research_universe', 'prefilter_symbols', 'submit_order'):
        assert forbidden not in src
    assert "'strict_pit_source_verified': False" in src
    assert "'source_manifest_mutated': False" in src
    assert "'production_main_picker_mutated': False" in src
    assert "'forward_challengers_mutated': False" in src
    assert "'raw_vendor_data_committed': False" in src


def main():
    test_parse_historical_components_and_vendor_symbol()
    test_parse_nested_historical_components()
    test_eod_rows_and_coverage()
    test_probe_selection_prefers_delisted_former_components()
    test_no_token_means_no_silent_vendor_or_production_fallback()
    print('EODHD PIT adapter PASS')


if __name__ == '__main__':
    main()
