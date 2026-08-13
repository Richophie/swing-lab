from paper_broker import new_state
from shadow_lab import ingest_confirmed_signals, lab_snapshot


def _item(symbol, rr, score=90):
    return {
        'market_date': '2026-08-13',
        'symbol': symbol,
        'strategy_id': 'rsi2_trend_reversion',
        'strategy_name': 'RSI2 추세내 과매도',
        'score': score,
        'risk_reward': rr,
        'entry_low': 99.0,
        'entry_high': 101.0,
        'target': 106.0,
        'stop': 95.0,
        'atr': 2.0,
        'target_days_low': 1,
        'target_days_high': 5,
        'performance_bucket': 'official_public',
        'experimental': False,
    }


def test_shadow_uses_official_close_signals_and_capacity_with_rr_priority():
    state = new_state(3_000_000)
    history = {
        'days': [
            {
                'date': '2026-08-13',
                'items': [
                    _item('AAA', 1.2),
                    _item('BBB', 2.1),
                    _item('CCC', 1.8),
                    _item('DDD', 1.5),
                ],
            }
        ]
    }
    result = ingest_confirmed_signals(state, history, fx_rate=1000.0)
    assert result == {'submitted': 3, 'skipped': 1}
    submitted = [o['symbol'] for o in state['orders']]
    assert submitted == ['BBB', 'CCC', 'DDD']
    assert all(o['order_origin'] == 'AUTO_CONFIRMED_CLOSE' for o in state['orders'])
    assert all(o['live_order_sent'] is False for o in state['orders'])
    # 0.75 ATR = $1.50, larger than the 1% ($1.00) fallback.
    assert all(o['atr'] == 2.0 for o in state['orders'])
    assert all(o['gap_guard'] == 1.5 for o in state['orders'])
    skipped = [x for x in state['shadow_decisions'] if x['decision'] == 'SKIPPED']
    assert len(skipped) == 1 and skipped[0]['symbol'] == 'AAA'


def test_shadow_does_not_duplicate_same_confirmed_signal():
    state = new_state(3_000_000)
    history = {'days': [{'date': '2026-08-13', 'items': [_item('AAA', 1.5)]}]}
    first = ingest_confirmed_signals(state, history, fx_rate=1000.0)
    second = ingest_confirmed_signals(state, history, fx_rate=1000.0)
    assert first['submitted'] == 1
    assert second == {'submitted': 0, 'skipped': 0}
    assert len(state['orders']) == 1


def test_shadow_rejects_missing_atr_instead_of_silently_using_one_percent():
    state = new_state(3_000_000)
    item = _item('AAA', 1.5)
    item.pop('atr')
    history = {'days': [{'date': '2026-08-13', 'items': [item]}]}
    result = ingest_confirmed_signals(state, history, fx_rate=1000.0)
    assert result == {'submitted': 0, 'skipped': 1}
    assert not state['orders']
    assert 'ATR' in state['shadow_decisions'][0]['reason']


def test_shadow_snapshot_keeps_live_trading_disabled():
    state = new_state(3_000_000)
    snap = lab_snapshot(state)
    assert snap['live_trading_enabled'] is False
    assert snap['lab_meta']['human_intervention'] is False
    assert snap['lab_summary']['total_orders'] == 0


def main():
    test_shadow_uses_official_close_signals_and_capacity_with_rr_priority()
    test_shadow_does_not_duplicate_same_confirmed_signal()
    test_shadow_rejects_missing_atr_instead_of_silently_using_one_percent()
    test_shadow_snapshot_keeps_live_trading_disabled()
    print('shadow lab PASS')


if __name__ == '__main__':
    main()
