from baseline_rules import BASELINE_VERSION, baseline_snapshot
from paper_broker import new_state
from shadow_lab import TRACK_A, TRACK_B, _sample_gate, combined_snapshot, lab_snapshot


def test_baseline_snapshot_is_frozen_and_complete():
    b = baseline_snapshot()
    assert b['baseline_version'] == BASELINE_VERSION
    assert b['public_strategies'] == [
        'confirmed_pullback',
        'rsi2_trend_reversion',
        'momentum_pullback',
    ]
    assert b['s_threshold'] == 85.0
    assert b['portfolio']['starting_cash_krw'] == 3_000_000
    assert b['portfolio']['max_positions'] == 3
    assert b['portfolio']['risk_per_trade_pct'] == 1.0
    assert b['forward_review']['no_strategy_tuning_before_closed_trades'] == 30
    assert b['forward_review']['formal_review_target_closed_trades'] == 50


def test_sample_gate_locks_strategy_tuning_until_forward_sample_is_large_enough():
    g0 = _sample_gate(0)
    g29 = _sample_gate(29)
    g30 = _sample_gate(30)
    g50 = _sample_gate(50)
    assert g0['production_tuning_locked'] is True and g0['remaining'] == 30
    assert g29['production_tuning_locked'] is True and g29['remaining'] == 1
    assert g30['production_tuning_locked'] is True and g30['stage'] == '1차 가설검토'
    assert g50['production_tuning_locked'] is False and g50['stage'] == '정식 Forward Review 가능'


def test_ab_accounts_are_independent_and_keep_live_trading_off():
    a = new_state(3_000_000)
    b = new_state(3_000_000)
    a_snap = lab_snapshot(a, TRACK_A)
    b_snap = lab_snapshot(b, TRACK_B)
    combined = combined_snapshot(a_snap, b_snap)
    assert combined['tracks'][TRACK_A]['summary']['starting_cash_krw'] == 3_000_000
    assert combined['tracks'][TRACK_B]['summary']['starting_cash_krw'] == 3_000_000
    assert combined['tracks'][TRACK_A]['lab_meta']['entry_mode'] == 'NEXT_OPEN_GAP_GUARD'
    assert combined['tracks'][TRACK_B]['lab_meta']['entry_mode'] == 'NEXT_SESSION_BUY_TOUCH'
    assert combined['tracks'][TRACK_A]['live_trading_enabled'] is False
    assert combined['tracks'][TRACK_B]['live_trading_enabled'] is False
    assert combined['comparison']['production_tuning_locked'] is True


def main():
    test_baseline_snapshot_is_frozen_and_complete()
    test_sample_gate_locks_strategy_tuning_until_forward_sample_is_large_enough()
    test_ab_accounts_are_independent_and_keep_live_trading_off()
    print('forward lab PASS')


if __name__ == '__main__':
    main()
