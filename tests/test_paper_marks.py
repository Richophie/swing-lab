from pathlib import Path
import tempfile

import paper_marks
from paper_broker import PaperBrokerStore, new_state, process_bar, submit_order


def _plan():
    return {
        'entry_low': 99.0,
        'entry_high': 101.0,
        'target': 105.0,
        'stop': 95.0,
        'atr': 2.0,
        'days_max': 5,
    }


def test_current_marks_show_recent_price_and_net_unrealized_pnl():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'paper.json'
        state = new_state(3_000_000)
        submit_order(
            state,
            symbol='TEST',
            strategy_id='rsi2_trend_reversion',
            strategy_name='RSI2 추세내 과매도',
            plan=_plan(),
            fx_rate=1000.0,
            submitted_market_date='2026-01-05',
            signal_date='2026-01-05',
            order_id='PAPER-MARK-1',
        )
        process_bar(
            state,
            symbol='TEST',
            date='2026-01-06',
            open_px=100.0,
            high_px=102.0,
            low_px=98.0,
            close_px=101.0,
            fx_rate=1000.0,
        )
        assert state['orders'][0]['status'] == 'FILLED'
        PaperBrokerStore(path).save(state)

        old_price = paper_marks._price_mark
        old_fx = paper_marks.current_fx_rate
        paper_marks._price_mark = lambda symbol: (102.0, '2026-01-06T19:00:00+00:00', '1m')
        paper_marks.current_fx_rate = lambda: 1000.0
        try:
            result = paper_marks.current_marks(path)
        finally:
            paper_marks._price_mark = old_price
            paper_marks.current_fx_rate = old_fx

        assert result['live_trading_enabled'] is False
        assert len(result['orders']) == 1
        mark = result['orders'][0]
        assert mark['current_price_usd'] == 102.0
        assert mark['price_source'] == '1m'
        assert mark['market_value_krw'] > 0
        assert mark['unrealized_pnl_krw'] > 0
        assert mark['unrealized_return_pct'] > 0
        assert mark['estimated_liquidation_value_krw'] < mark['market_value_krw']
        assert result['summary']['unrealized_pnl_krw'] == mark['unrealized_pnl_krw']
        assert result['summary']['equity_krw'] == round(result['summary']['cash_krw'] + mark['estimated_liquidation_value_krw'], 2)


def test_pending_mark_has_price_but_no_unrealized_pnl():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'paper.json'
        state = new_state(3_000_000)
        submit_order(
            state,
            symbol='TEST',
            strategy_id='rsi2_trend_reversion',
            strategy_name='RSI2 추세내 과매도',
            plan=_plan(),
            fx_rate=1000.0,
            submitted_market_date='2026-01-05',
            order_id='PAPER-MARK-2',
        )
        PaperBrokerStore(path).save(state)

        old_price = paper_marks._price_mark
        old_fx = paper_marks.current_fx_rate
        paper_marks._price_mark = lambda symbol: (100.5, '2026-01-05T19:00:00+00:00', '1m')
        paper_marks.current_fx_rate = lambda: 1000.0
        try:
            result = paper_marks.current_marks(path)
            mark = result['orders'][0]
        finally:
            paper_marks._price_mark = old_price
            paper_marks.current_fx_rate = old_fx

        assert mark['status'] == 'PENDING'
        assert mark['current_price_usd'] == 100.5
        assert mark['unrealized_pnl_krw'] is None
        assert result['summary']['unrealized_pnl_krw'] == 0.0


def main():
    test_current_marks_show_recent_price_and_net_unrealized_pnl()
    test_pending_mark_has_price_but_no_unrealized_pnl()
    print('paper marks PASS')


if __name__ == '__main__':
    main()
