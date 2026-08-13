from signal_log import update_log


def _scan(*, elite=False, score=90.0, elite_score=80.0, results=True):
    rows = []
    if results:
        rows = [
            {
                'symbol': 'L',
                'name_ko': 'Loews Corporation',
                'security_name': 'Loews Corporation',
                'sparkline': [112.0, 113.0],
                'rsi': 43.2,
                'd120': 2.83,
                'bb_pos': 17.2,
                'strategy_signals': [
                    {
                        'strategy_id': 'rsi2_trend_reversion',
                        'strategy_name': 'RSI2 추세내 과매도',
                        'strategy_score': score,
                        'elite_score': elite_score,
                        'elite_pass': elite,
                        'checks': {
                            'current_signal': True,
                            'flow': elite,
                            'risk_reward': True,
                            'market': True,
                            'entry_viable': True,
                            'atr_stop_margin': True,
                        },
                        'flow_score': 40 if not elite else 60,
                    }
                ],
                'strategy_trade_plans': {
                    'rsi2_trend_reversion': {
                        'entry_low': 112.8,
                        'entry_high': 113.4,
                        'target': 116.2,
                        'stop': 109.6,
                        'risk_reward_gate': 1.3,
                    }
                },
            }
        ]
    return {
        'status': 'ready',
        'scanned_at': '2026-08-13T14:00:00+00:00',
        'market': {'state': '좋음'},
        'results': rows,
    }


def test_s_capture_is_logged_even_before_elite_pass():
    log = {'version': 3, 'active': {}, 'elite_active': {}, 'events': []}
    log = update_log(_scan(elite=False), log)
    assert len(log['active']) == 1
    assert len(log['elite_active']) == 0
    assert log['events'][-1]['event'] == 'ENTER'
    assert log['events'][-1]['tier'] == 'S'
    assert log['events'][-1]['strategy_score'] == 90.0


def test_elite_upgrade_and_downgrade_do_not_fake_s_exit():
    log = {'version': 3, 'active': {}, 'elite_active': {}, 'events': []}
    log = update_log(_scan(elite=False), log)
    log = update_log(_scan(elite=True, elite_score=84.0), log)
    assert log['events'][-1]['event'] == 'ELITE_ENTER'
    assert len(log['active']) == 1
    assert len(log['elite_active']) == 1

    log = update_log(_scan(elite=False, elite_score=80.0), log)
    assert log['events'][-1]['event'] == 'ELITE_EXIT'
    assert len(log['active']) == 1
    assert len(log['elite_active']) == 0


def test_true_s_disappearance_is_exit_and_same_day_return_is_reentry():
    log = {'version': 3, 'active': {}, 'elite_active': {}, 'events': []}
    log = update_log(_scan(elite=False), log)
    log = update_log(_scan(results=False), log)
    assert log['events'][-1]['event'] == 'EXIT'
    log = update_log(_scan(elite=False), log)
    assert log['events'][-1]['event'] == 'REENTER'


def main():
    test_s_capture_is_logged_even_before_elite_pass()
    test_elite_upgrade_and_downgrade_do_not_fake_s_exit()
    test_true_s_disappearance_is_exit_and_same_day_return_is_reentry()
    print('signal tier log PASS')


if __name__ == '__main__':
    main()
