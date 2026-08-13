import scanner


def _plan(stop):
    return {
        'entry_low': 99.0,
        'entry_high': 101.0,
        'target': 106.0,
        'stop': stop,
        'risk_reward': 1.20,  # display-rounded legacy value
        'stop_atr_multiple': 1.5,
        'min_stop_atr': 1.5,
        'entry_viable': True,
        'entry_status': '진입 적정',
    }


def test_rr_1195ish_does_not_pass_as_display_120():
    plan = _plan(94.98)  # 6 / 5.02 ~= 1.1952, which used to round to display 1.20
    result = scanner._current_selection(90, plan, {}, market_state='좋음')
    assert plan['risk_reward'] == 1.20
    assert plan['risk_reward_gate'] < 1.20
    assert result['checks']['risk_reward'] is False
    assert result['elite_pass'] is False


def test_true_rr_120_or_more_passes_rr_check():
    plan = _plan(95.0)  # exactly 6 / 5 = 1.20 before costs
    result = scanner._current_selection(90, plan, {}, market_state='좋음')
    assert plan['risk_reward_gate'] >= 1.20
    assert result['checks']['risk_reward'] is True
    assert result['net_risk_reward'] < result['gross_risk_reward_gate']


def test_net_rr_is_diagnostic_not_live_gate():
    plan = _plan(95.0)
    result = scanner._current_selection(95, plan, {'relative_volume':1,'volume_5d_vs_20d':.9,'up_down_volume_ratio':1.2,'avg_dollar_volume_20d':100_000_000}, market_state='좋음')
    assert result['gross_risk_reward_gate'] >= 1.20
    assert result['net_risk_reward'] < 1.20
    assert result['checks']['risk_reward'] is True
    assert result['elite_pass'] is True


def main():
    test_rr_1195ish_does_not_pass_as_display_120()
    test_true_rr_120_or_more_passes_rr_check()
    test_net_rr_is_diagnostic_not_live_gate()
    print('selection precision PASS')


if __name__=='__main__':main()
