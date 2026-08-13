from pathlib import Path
import tempfile

from paper_broker import PaperBrokerStore, new_state, process_bar, state_summary, submit_order


def _plan(max_hold=5):
    return {
        'entry_low': 99.0,
        'entry_high': 101.0,
        'target': 105.0,
        'stop': 95.0,
        'atr': 2.0,
        'days_max': max_hold,
    }


def _submit(state, order_id='PAPER-TEST-1', max_hold=5):
    return submit_order(
        state,
        symbol='TEST',
        strategy_id='rsi2_trend_reversion',
        strategy_name='RSI2 추세내 과매도',
        plan=_plan(max_hold),
        fx_rate=1000.0,
        submitted_market_date='2026-01-05',
        signal_date='2026-01-05',
        order_id=order_id,
    )


def test_pending_waits_for_next_session_and_same_day_stop_is_conservative():
    state = new_state(3_000_000)
    order = _submit(state)
    before = state['cash_krw']
    process_bar(state, symbol='TEST', date='2026-01-05', open_px=100, high_px=110, low_px=90, close_px=100, fx_rate=1000)
    assert order['status'] == 'PENDING'
    assert state['cash_krw'] == before

    process_bar(state, symbol='TEST', date='2026-01-06', open_px=100, high_px=106, low_px=94, close_px=100, fx_rate=1000)
    assert order['status'] == 'CLOSED'
    assert order['exit_reason'] == '손절'
    assert order['entry_date'] == '2026-01-06'
    assert order['exit_date'] == '2026-01-06'
    assert order['pnl_krw'] < 0
    assert order['live_order_sent'] is False


def test_gap_rejection_cancels_next_open_order():
    state = new_state(3_000_000)
    order = _submit(state)
    process_bar(state, symbol='TEST', date='2026-01-06', open_px=110, high_px=112, low_px=108, close_px=111, fx_rate=1000)
    assert order['status'] == 'CANCELLED'
    assert '허용 진입범위' in order['cancel_reason']
    assert state_summary(state)['open_positions'] == 0


def test_target_close_updates_cash_and_realized_pnl():
    state = new_state(3_000_000)
    order = _submit(state)
    process_bar(state, symbol='TEST', date='2026-01-06', open_px=100, high_px=106, low_px=98, close_px=105, fx_rate=1000)
    assert order['status'] == 'CLOSED'
    assert order['exit_reason'] == '목표달성'
    assert order['pnl_krw'] > 0
    summary = state_summary(state)
    assert summary['closed_trades'] == 1
    assert summary['realized_pnl_krw'] == order['pnl_krw']
    assert summary['cash_krw'] > 3_000_000


def test_time_exit_occurs_after_max_hold_bars():
    state = new_state(3_000_000)
    order = _submit(state, max_hold=2)
    process_bar(state, symbol='TEST', date='2026-01-06', open_px=100, high_px=102, low_px=98, close_px=100, fx_rate=1000)
    assert order['status'] == 'FILLED'
    assert order['held_bars'] == 0
    process_bar(state, symbol='TEST', date='2026-01-07', open_px=100, high_px=102, low_px=98, close_px=101, fx_rate=1000)
    assert order['status'] == 'FILLED'
    assert order['held_bars'] == 1
    process_bar(state, symbol='TEST', date='2026-01-08', open_px=101, high_px=103, low_px=99, close_px=102, fx_rate=1000)
    assert order['status'] == 'CLOSED'
    assert order['exit_reason'] == '기간종료'
    assert order['exit_date'] == '2026-01-08'


def test_pending_orders_reserve_cash_and_capacity():
    state = new_state(3_000_000)
    first = _submit(state, order_id='PAPER-A')
    summary = state_summary(state)
    assert summary['pending_orders'] == 1
    assert summary['reserved_cash_krw'] > 0
    try:
        submit_order(
            state,
            symbol='OTHER',
            strategy_id='rsi2_trend_reversion',
            strategy_name='RSI2',
            plan=_plan(),
            fx_rate=1000,
            submitted_market_date='2026-01-05',
            max_positions=1,
            order_id='PAPER-B',
        )
        raise AssertionError('capacity rejection expected')
    except ValueError as exc:
        assert '최대 동시 포지션' in str(exc)
    assert first['status'] == 'PENDING'


def test_store_round_trip_and_live_flag_is_immutable_false():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'paper.json'
        store = PaperBrokerStore(path)
        state = store.load()
        _submit(state)
        state['live_trading_enabled'] = True
        store.save(state)
        loaded = store.load()
        assert loaded['live_trading_enabled'] is False
        assert loaded['orders'][0]['status'] == 'PENDING'


def main():
    test_pending_waits_for_next_session_and_same_day_stop_is_conservative()
    test_gap_rejection_cancels_next_open_order()
    test_target_close_updates_cash_and_realized_pnl()
    test_time_exit_occurs_after_max_hold_bars()
    test_pending_orders_reserve_cash_and_capacity()
    test_store_round_trip_and_live_flag_is_immutable_false()
    print('paper broker PASS')


if __name__ == '__main__':
    main()
