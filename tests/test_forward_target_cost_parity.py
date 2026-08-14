from datetime import datetime, timezone
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import priority_challenger_v1 as c
from backtest_engine import market_sell_fill
from config import BACKTEST_COMMISSION_PCT, BACKTEST_HALF_SPREAD_BPS, BACKTEST_SLIPPAGE_BPS


def test_forward_target_exit_uses_same_exit_friction_as_replay():
    frame = pd.DataFrame(
        {
            'Open': [100.0],
            'High': [106.0],
            'Low': [99.0],
            'Close': [105.0],
        },
        index=pd.to_datetime(['2026-08-13']),
    )
    position = {
        'id': 'x',
        'symbol': 'AAA',
        'strategy_id': c.CONFIRMED_ID,
        'entry_date': '2026-08-13',
        'entry_fill_usd': 100.0,
        'notional_krw': 1_000_000.0,
        'stop': 90.0,
        'target': 105.0,
        'max_hold': 5,
        'held_bars': 0,
        'last_close_processed': '',
    }
    state = {'cash_krw': 0.0, 'positions': [position], 'closed': [], 'decisions': []}

    c._process_position(state, position, frame, datetime(2026, 8, 14, 12, tzinfo=timezone.utc))

    assert len(state['closed']) == 1
    closed = state['closed'][0]
    expected_fill = market_sell_fill(105.0, BACKTEST_SLIPPAGE_BPS, BACKTEST_HALF_SPREAD_BPS)
    commission = BACKTEST_COMMISSION_PCT / 100.0
    expected_factor = expected_fill * (1.0 - commission) / (100.0 * (1.0 + commission))

    assert closed['exit_reason'] == '목표가'
    assert closed['exit_fill_usd'] == round(expected_fill, 6)
    assert closed['return_pct'] == round((expected_factor - 1.0) * 100.0, 4)
    assert state['cash_krw'] == round(1_000_000.0 * expected_factor, 2)


if __name__ == '__main__':
    test_forward_target_exit_uses_same_exit_friction_as_replay()
    print('forward target cost parity PASS')
