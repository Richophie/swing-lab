from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from journal import should_publish_scan
from signal_log import update_log
from stock_names import korean_name


def synthetic_scan(at='2026-08-13T19:30:00+00:00', include=True):
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
                    }
                },
                'strategy_signals': [
                    {
                        'strategy_id': 'rsi2_trend_reversion',
                        'strategy_name': 'RSI2 추세내 과매도',
                        'strategy_score': 91,
                        'elite_score': 85,
                        'elite_pass': True,
                        'experimental': False,
                    }
                ],
            }
        ]
    return {'status': 'ready', 'scanned_at': at, 'results': rows}


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

    # Same signal in the next scan updates last_seen without creating duplicate ENTER.
    again = synthetic_scan('2026-08-13T20:00:00+00:00')
    log = update_log(again, log)
    assert len(log['events']) == 1
    assert next(iter(log['active'].values()))['first_seen'] == first_seen

    # If it drops out later, preserve the earlier ENTER and append EXIT.
    gone = synthetic_scan('2026-08-13T20:30:00+00:00', include=False)
    log = update_log(gone, log)
    assert len(log['active']) == 0
    assert [e['event'] for e in log['events']] == ['ENTER', 'EXIT']


def test_korean_names_for_new_scan_names():
    assert korean_name('FMX', 'Fomento Economico Mexicano S.A.B. de C.V.') == '펨사(FEMSA)'
    assert korean_name('WRB', 'W.R. Berkley Corporation') == 'W.R. 버클리'
    assert korean_name('BUD', 'Anheuser-Busch Inbev SA Sponsored ADR (Belgium)') == '앤하이저부시 인베브'


def main():
    test_close_publication_gate()
    test_intraday_enter_exit_log_is_append_only()
    test_korean_names_for_new_scan_names()
    print('signal history PASS')


if __name__ == '__main__':
    main()
