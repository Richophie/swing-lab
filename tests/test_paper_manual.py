from paper_manual import _resize_order


def _order(qty=6):
    return {
        'id': 'PAPER-X',
        'qty': qty,
        'planned_entry_usd': 100.0,
        'stop': 95.0,
        'fx_at_submit': 1000.0,
        'commission_pct_per_side': 0.10,
        'buy_low': 99.0,
        'buy_high': 101.0,
        'planned_notional_krw': qty * 100_000.0,
        'planned_risk_krw': qty * 5_000.0,
        'reserved_cash_krw': qty * 100_100.0,
    }


def test_manual_quantity_can_be_reduced_without_changing_trade_levels():
    order = _order()
    state = {
        'events': [
            {
                'order_id': 'PAPER-X',
                'event': 'SUBMITTED',
                'detail': 'old',
            }
        ]
    }
    _resize_order(order, state, 3)
    assert order['qty'] == 3
    assert order['max_allowed_qty'] == 6
    assert order['planned_notional_krw'] == 300_000.0
    assert order['planned_risk_krw'] == 15_000.0
    assert order['reserved_cash_krw'] == 300_300.0
    assert order['stop'] == 95.0
    assert '3주' in state['events'][0]['detail']


def test_manual_quantity_cannot_exceed_engine_max():
    order = _order()
    try:
        _resize_order(order, {'events': []}, 7)
        raise AssertionError('max quantity rejection expected')
    except ValueError as exc:
        assert '최대 6주' in str(exc)


def main():
    test_manual_quantity_can_be_reduced_without_changing_trade_levels()
    test_manual_quantity_cannot_exceed_engine_max()
    print('paper manual PASS')


if __name__ == '__main__':
    main()
