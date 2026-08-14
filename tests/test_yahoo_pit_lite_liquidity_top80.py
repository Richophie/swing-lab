from datetime import date
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yahoo_pit_lite_liquidity_top80 as liq
import yahoo_pit_lite_research as pit


def frame(volume: float) -> pd.DataFrame:
    idx = pd.bdate_range('2021-01-01', periods=30)
    return pd.DataFrame(
        {
            'Open': 100.0,
            'High': 101.0,
            'Low': 99.0,
            'Close': 100.0,
            'Volume': volume,
        },
        index=idx,
    )


def membership(*members: str) -> pit.MembershipIndex:
    return pit.MembershipIndex([
        {'date': date(2017, 1, 1), 'members': set(members)},
    ])


def test_top_n_uses_signal_day_information_only():
    frames = {'AAA': frame(300.0), 'BBB': frame(200.0), 'CCC': frame(100.0)}
    day = frames['AAA'].index[20].date()
    m = membership('AAA', 'BBB', 'CCC')

    before, _ = liq.historical_liquidity_top_n(frames, m, {day}, top_n=2)
    assert before[day] == {'AAA', 'BBB'}

    # Make CCC absurdly liquid only AFTER the signal day. A look-ahead bug would
    # incorrectly move it into the historical top2 for the earlier signal.
    changed = {k: v.copy() for k, v in frames.items()}
    future_mask = changed['CCC'].index.date > day
    changed['CCC'].loc[future_mask, 'Volume'] = 1_000_000_000.0
    after, _ = liq.historical_liquidity_top_n(changed, m, {day}, top_n=2)
    assert after[day] == before[day]


def test_cross_section_excludes_nonmembers_even_when_liquid():
    frames = {'AAA': frame(300.0), 'BBB': frame(200.0), 'CCC': frame(999999.0)}
    day = frames['AAA'].index[20].date()
    m = membership('AAA', 'BBB')
    top, diag = liq.historical_liquidity_top_n(frames, m, {day}, top_n=2)
    assert top[day] == {'AAA', 'BBB'}
    assert diag['days_with_at_least_top_n_observable_members'] == 1


def test_candidate_filter_is_signal_date_specific():
    day1 = date(2021, 1, 29)
    day2 = date(2021, 2, 1)
    candidates = [
        {'symbol': 'AAA', 'signal_date': day1.isoformat()},
        {'symbol': 'BBB', 'signal_date': day1.isoformat()},
        {'symbol': 'BBB', 'signal_date': day2.isoformat()},
    ]
    selected = liq.liquidity_filter(candidates, {day1: {'AAA'}, day2: {'BBB'}})
    assert [(x['symbol'], x['signal_date']) for x in selected] == [
        ('AAA', day1.isoformat()),
        ('BBB', day2.isoformat()),
    ]


def test_source_is_diagnostic_only_and_top80_is_fixed():
    src = Path('yahoo_pit_lite_liquidity_top80.py').read_text(encoding='utf-8')
    assert 'TOP_N = 80' in src
    assert 'ADV_LOOKBACK = 20' in src
    assert 'submit_order' not in src
    assert "'production_main_picker_mutated': False" in src
    assert "'forward_challengers_mutated': False" in src
    assert "'live_trading_mutated': False" in src


if __name__ == '__main__':
    test_top_n_uses_signal_day_information_only()
    test_cross_section_excludes_nonmembers_even_when_liquid()
    test_candidate_filter_is_signal_date_specific()
    test_source_is_diagnostic_only_and_top80_is_fixed()
    print('Yahoo PIT-Lite historical liquidity Top80 PASS')
