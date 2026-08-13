import paper_manual


def _state():
    return {
        'starting_cash_krw': 3_000_000.0,
        'cash_krw': 3_000_000.0,
        'orders': [],
        'events': [],
        'live_trading_enabled': False,
    }


def _order():
    return {
        'id': 'PAPER-IMM',
        'symbol': 'AAA',
        'strategy_id': 'rsi2_trend_reversion',
        'strategy_name': 'RSI2',
        'status': 'PENDING',
        'qty': 2,
        'max_allowed_qty': 2,
        'buy_low': 99.0,
        'buy_high': 101.0,
        'target': 106.0,
        'stop': 95.0,
        'planned_entry_usd': 100.0,
        'fx_at_submit': 1000.0,
        'created_at': '2026-08-13T11:15:00+00:00',
        'risk_budget_krw': 30_000.0,
        'commission_pct_per_side': 0.10,
        'slippage_bps': 5.0,
        'half_spread_bps': 2.5,
        'submitted_market_date': '2026-08-13',
        'reserved_cash_krw': 202_202.0,
        'order_origin': 'MANUAL_PAPER',
    }


def test_manual_fill_uses_latest_quote_immediately_and_creates_pnl_basis():
    state = _state()
    order = _order()
    state['orders'].append(order)
    old_price, old_fx = paper_manual._price_mark, paper_manual.current_fx_rate
    try:
        paper_manual._price_mark = lambda symbol: (100.0, '2026-08-13T19:59:00+00:00', '1m')
        paper_manual.current_fx_rate = lambda: 1000.0
        paper_manual._fill_manual_now(state, order)
    finally:
        paper_manual._price_mark, paper_manual.current_fx_rate = old_price, old_fx
    assert order['status'] == 'FILLED'
    assert order['entry_fill_usd'] > 100.0
    assert order['entry_timestamp'] == '2026-08-13T19:59:00+00:00'
    assert order['entry_resolution_quality'] == 'manual_1m_quote'
    assert order['reserved_cash_krw'] == 0.0
    assert order['entry_cost_krw'] > 0
    assert state['cash_krw'] < 3_000_000.0
    assert any(e['event'] == 'FILLED' for e in state['events'])


def test_manual_fill_blocks_new_buy_below_stop():
    state = _state()
    order = _order()
    state['orders'].append(order)
    old_price, old_fx = paper_manual._price_mark, paper_manual.current_fx_rate
    try:
        paper_manual._price_mark = lambda symbol: (94.0, '2026-08-13T19:59:00+00:00', '1m')
        paper_manual.current_fx_rate = lambda: 1000.0
        try:
            paper_manual._fill_manual_now(state, order)
            raise AssertionError('below-stop manual buy should be rejected')
        except ValueError as exc:
            assert 'STOP' in str(exc)
    finally:
        paper_manual._price_mark, paper_manual.current_fx_rate = old_price, old_fx


def test_legacy_pending_manual_buy_uses_original_click_price_fx_and_time():
    state = _state()
    order = _order()
    state['orders'].append(order)
    paper_manual._apply_legacy_submit_fill(state, order)
    assert order['status'] == 'FILLED'
    assert order['entry_raw_open_usd'] == 100.0
    assert order['entry_fill_usd'] > 100.0
    assert order['fx_at_entry'] == 1000.0
    assert order['entry_timestamp'] == '2026-08-13T11:15:00+00:00'
    assert order['entry_resolution_quality'] == 'manual_legacy_click_price'
    assert order['manual_immediate_upgrade_repaired'] is True
    assert order['manual_fill_quote_source'] == 'legacy_planned_entry_at_click'


def test_already_migrated_legacy_buy_is_repaired_back_to_click_basis():
    state = _state()
    order = _order()
    state['orders'].append(order)
    old_price, old_fx = paper_manual._price_mark, paper_manual.current_fx_rate
    try:
        paper_manual._price_mark = lambda symbol: (102.0, '2026-08-13T12:00:00+00:00', '1m_ext')
        paper_manual.current_fx_rate = lambda: 1010.0
        paper_manual._fill_manual_now(state, order)
    finally:
        paper_manual._price_mark, paper_manual.current_fx_rate = old_price, old_fx
    order['manual_immediate_upgrade'] = True
    wrong_cost = order['entry_cost_krw']
    assert order['entry_raw_open_usd'] == 102.0

    paper_manual._apply_legacy_submit_fill(state, order, repair_existing_fill=True)
    assert order['entry_raw_open_usd'] == 100.0
    assert order['fx_at_entry'] == 1000.0
    assert order['entry_timestamp'] == '2026-08-13T11:15:00+00:00'
    assert order['entry_cost_krw'] < wrong_cost
    assert order['manual_immediate_upgrade_repaired'] is True
    assert any(e['event'] == 'MIGRATION_REPAIRED' for e in state['events'])


def main():
    test_manual_fill_uses_latest_quote_immediately_and_creates_pnl_basis()
    test_manual_fill_blocks_new_buy_below_stop()
    test_legacy_pending_manual_buy_uses_original_click_price_fx_and_time()
    test_already_migrated_legacy_buy_is_repaired_back_to_click_basis()
    print('manual immediate fill PASS')


if __name__ == '__main__':
    main()
