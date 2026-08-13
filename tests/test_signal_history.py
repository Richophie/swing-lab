from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from journal import should_publish_scan
from signal_log import update_log
from stock_names import korean_name


def synthetic_scan(at='2026-08-13T19:30:00+00:00', include=True, elite_pass=True, checks=None, risk_reward=1.31, flow_score=68, elite_score=85):
    rows = []
    if include:
        rows = [
            {
                'symbol': 'FMX',
                'name_ko': '펨사(FEMSA)',
                'security_name': 'Fomento Economico Mexicano S.A.B. de C.V.',
                'score': 85,
                'rsi': 36,
                'd120': -1.58,
                'bb_pos': 0.4,
                'sparkline': [116.0, 117.5],
                'strategy_trade_plans': {
                    'rsi2_trend_reversion': {
                        'entry_low': 116.99,
                        'entry_high': 118.10,
                        'target': 125.91,
                        'stop': 112.27,
                        'risk_reward': risk_reward,
                        'entry_status': '진입 적정',
                        'stop_atr_multiple': 1.8,
                        'min_stop_atr': 1.5,
                    }
                },
                'strategy_signals': [
                    {
                        'strategy_id': 'rsi2_trend_reversion',
                        'strategy_name': 'RSI2 추세내 과매도',
                        'strategy_score': 91,
                        'elite_score': elite_score,
                        'elite_pass': elite_pass,
                        'flow_score': flow_score,
                        'checks': checks or {
                            'current_signal': True,
                            'flow': True,
                            'risk_reward': True,
                            'market': True,
                            'entry_viable': True,
                            'atr_stop_margin': True,
                        },
                        'experimental': False,
                    }
                ],
            }
        ]
    return {'status': 'ready', 'scanned_at': at, 'market': {'state': '좋음'}, 'results': rows}


def test_close_publication_gate():
    # Aug 13 2026 is EDT (UTC-4): 19:30Z = 15:30 ET, still intraday.
    assert not should_publish_scan(synthetic_scan('2026-08-13T19:30:00+00:00'))
    # 20:10Z = 16:10 ET, after the publication buffer.
    assert should_publish_scan(synthetic_scan('2026-08-13T20:10:00+00:00'))


def test_intraday_enter_exit_log_is_append_only():
    log = {'version': 1, 'active': {}, 'events': []}
    log = update_log(synthetic_scan(), log)
    assert len(log['active']) == 1
    assert log['events'][-1]['event'] == 'ENTER'
    first_seen = log['events'][-1]['first_seen']

    # Same S signal in the next scan updates last_seen without creating duplicate ENTER.
    again = synthetic_scan('2026-08-13T20:00:00+00:00')
    log = update_log(again, log)
    assert len(log['events']) == 1
    assert next(iter(log['active'].values()))['first_seen'] == first_seen

    # If the S signal itself drops out later, preserve ENTER and append a true EXIT.
    gone = synthetic_scan('2026-08-13T20:30:00+00:00', include=False)
    log = update_log(gone, log)
    assert len(log['active']) == 0
    assert [e['event'] for e in log['events']] == ['ENTER', 'EXIT']
    assert log['events'][-1]['exit_reason_code'] == 'signal_missing'
    assert '해당 전략 S 신호' in log['events'][-1]['exit_reason']


def test_intraday_elite_exit_reason_identifies_failed_elite_checks():
    log = {'version': 1, 'active': {}, 'events': []}
    log = update_log(synthetic_scan(), log)
    failed_checks = {
        'current_signal': True,
        'flow': False,
        'risk_reward': False,
        'market': True,
        'entry_viable': True,
        'atr_stop_margin': True,
    }
    failed = synthetic_scan(
        '2026-08-13T20:15:00+00:00',
        elite_pass=False,
        checks=failed_checks,
        risk_reward=1.08,
        flow_score=39,
        elite_score=68,
    )
    log = update_log(failed, log)
    event = log['events'][-1]
    # The strategy S signal is still alive; only the elite/엄선 layer was lost.
    assert event['event'] == 'ELITE_EXIT'
    assert len(log['active']) == 1
    assert len(log['elite_active']) == 0
    assert event['exit_reason_code'] == 'flow+risk_reward'
    assert '수급 점수 39 < 42' in event['exit_reason']
    assert '손익비 1.08:1 < 1.20:1' in event['exit_reason']
    assert event['exit_details']['flow_score'] == 39
    assert event['exit_details']['risk_reward'] == 1.08


def test_korean_names_for_new_scan_names():
    assert korean_name('FMX', 'Fomento Economico Mexicano S.A.B. de C.V.') == '펨사(FEMSA)'
    assert korean_name('WRB', 'W.R. Berkley Corporation') == 'W.R. 버클리'
    assert korean_name('BUD', 'Anheuser-Busch Inbev SA Sponsored ADR (Belgium)') == '앤하이저부시 인베브'


def main():
    test_close_publication_gate()
    test_intraday_enter_exit_log_is_append_only()
    test_intraday_elite_exit_reason_identifies_failed_elite_checks()
    test_korean_names_for_new_scan_names()
    print('signal history PASS')


if __name__ == '__main__':
    main()
