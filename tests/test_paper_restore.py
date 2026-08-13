from pathlib import Path
import tempfile

from paper_broker import PaperBrokerStore, submit_order
from paper_restore import restore_browser_backup, sanitize_browser_backup


def backup_state():
    return {
        'version': 1,
        'starting_cash_krw': 3_000_000,
        'cash_krw': 3_000_000,
        'orders': [
            {
                'id': 'PAPER-BACKUP1',
                'symbol': 'FMX',
                'strategy_id': 'rsi2_trend_reversion',
                'strategy_name': 'RSI2 추세내 과매도',
                'status': 'PENDING',
                'qty': 5,
                'buy_low': 116.0,
                'buy_high': 118.0,
                'target': 125.0,
                'stop': 111.0,
                'reserved_cash_krw': 830_000,
                'live_order_sent': True,
            }
        ],
        'events': [{'event': 'SUBMITTED', 'symbol': 'FMX'}],
        'live_trading_enabled': True,
    }


def test_sanitize_forces_live_flags_off():
    state = sanitize_browser_backup(backup_state())
    assert state['live_trading_enabled'] is False
    assert state['orders'][0]['live_order_sent'] is False
    assert state['orders'][0]['symbol'] == 'FMX'


def test_restore_only_when_server_ledger_is_empty():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / 'paper.json'
        restored = restore_browser_backup(backup_state(), state_path=path)
        assert restored['browser_restore'] == 'restored'
        assert len(restored['orders']) == 1
        assert restored['orders'][0]['live_order_sent'] is False

        store = PaperBrokerStore(path)
        state = store.load()
        # Add another server-side order so a stale browser backup cannot overwrite it.
        state['orders'].append({
            'id': 'SERVER-ONLY', 'symbol': 'AAPL', 'strategy_id': 'confirmed_pullback',
            'strategy_name': '확인형 눌림반등', 'status': 'CANCELLED', 'qty': 0,
            'live_order_sent': False,
        })
        store.save(state)
        second = restore_browser_backup(backup_state(), state_path=path)
        assert second['browser_restore'] == 'server_state_kept'
        assert any(o.get('id') == 'SERVER-ONLY' for o in second['orders'])


def test_rejects_invalid_status():
    bad = backup_state()
    bad['orders'][0]['status'] = 'LIVE_SENT'
    try:
        sanitize_browser_backup(bad)
    except ValueError:
        pass
    else:
        raise AssertionError('invalid status must be rejected')


def main():
    test_sanitize_forces_live_flags_off()
    test_restore_only_when_server_ledger_is_empty()
    test_rejects_invalid_status()
    print('paper restore PASS')


if __name__ == '__main__':
    main()
