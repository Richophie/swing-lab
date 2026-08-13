from datetime import datetime, timezone
from pathlib import Path
import tempfile

import pandas as pd

import journal
import paper_broker_service
import scanner


def test_incomplete_daily_bar_uses_previous_completed_flow():
    idx = pd.date_range('2026-01-01', periods=206, freq='D')
    d = pd.DataFrame({'Open':1.0,'High':1.0,'Low':1.0,'Close':1.0,'Volume':100.0}, index=idx)
    # Force the final row to a US-session date and evaluate before 16:05 ET.
    d.index = list(d.index[:-1]) + [pd.Timestamp('2026-08-13')]
    now = datetime(2026,8,13,18,0,tzinfo=timezone.utc)  # 14:00 ET
    assert scanner._has_incomplete_daily_bar(d, now)

    old = scanner.evaluate_strategies
    scanner.evaluate_strategies = lambda frame, state: {'flow': {'relative_volume': 1.11, 'volume_5d_vs_20d': .91}}
    try:
        flow,basis = scanner._selection_flow(d, {'relative_volume': .15}, '좋음', now)
    finally:
        scanner.evaluate_strategies = old
    assert basis == 'previous_completed_session'
    assert flow['relative_volume'] == 1.11


def test_closed_session_keeps_current_flow():
    d = pd.DataFrame({'Close':[1.0]}, index=[pd.Timestamp('2026-08-13')])
    now = datetime(2026,8,13,21,0,tzinfo=timezone.utc)  # 17:00 ET
    flow,basis = scanner._selection_flow(d, {'relative_volume': 1.4}, '좋음', now)
    assert basis == 'current_completed_session'
    assert flow['relative_volume'] == 1.4


def test_official_journal_excludes_experimental_from_publish_and_summary():
    scan = {
        'scanned_at':'2026-08-13T21:10:00+00:00',
        'results':[{
            'symbol':'AAA','name_ko':'AAA','strategy_trade_plans':{
                'rsi2_trend_reversion':{'entry_low':99,'entry_high':101,'target':105,'stop':95,'days_max':5},
                'volatility_breakout':{'entry_low':99,'entry_high':101,'target':106,'stop':95,'days_max':5},
            },
            'strategy_signals':[
                {'strategy_id':'rsi2_trend_reversion','strategy_name':'RSI2','elite_pass':True,'experimental':False,'strategy_score':90,'elite_score':86},
                {'strategy_id':'volatility_breakout','strategy_name':'VCP','elite_pass':True,'experimental':True,'strategy_score':95,'elite_score':95},
            ],
        }],
    }
    store = {'days':[]}
    old = journal.confirmed_market_date
    journal.confirmed_market_date = lambda s:'2026-08-13'
    try:
        day,added = journal.append_current_scan(scan,store)
    finally:
        journal.confirmed_market_date = old
    assert day == '2026-08-13'
    assert added == 1
    assert len(store['days'][0]['items']) == 1
    assert store['days'][0]['items'][0]['strategy_id'] == 'rsi2_trend_reversion'
    assert store['days'][0]['items'][0]['performance_bucket'] == 'official_public'

    official = {**store['days'][0]['items'][0], 'status_code':'SUCCESS', 'outcome_return_pct':2.0}
    experimental = {'strategy_id':'volatility_breakout','experimental':True,'status_code':'STOP','outcome_return_pct':-2.0}
    summary,research = journal.summarize({'days':[{'items':[official,experimental]}]})
    assert summary['total_signals'] == 1
    assert summary['success'] == 1
    assert summary['excluded_research_signals'] == 1
    assert research['total_signals'] == 1
    assert research['stop'] == 1


def test_live_paper_order_is_tagged_research_origin():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)/'paper.json'
        old_plan = paper_broker_service.latest_plan
        old_fx = paper_broker_service.current_fx_rate
        old_date = paper_broker_service._latest_market_date
        paper_broker_service.latest_plan = lambda symbol,strategy_id=None:{
            'symbol':'TEST','strategy_id':'rsi2_trend_reversion','strategy_name':'RSI2',
            'scan_date':'2026-08-13','plan':{'entry_low':99,'entry_high':101,'target':105,'stop':95,'atr':2,'days_max':5},
        }
        paper_broker_service.current_fx_rate = lambda:1000.0
        paper_broker_service._latest_market_date = lambda symbol:'2026-08-13'
        try:
            paper_broker_service.submit_from_latest('TEST',state_path=path)
            state = paper_broker_service.PaperBrokerStore(path).load()
        finally:
            paper_broker_service.latest_plan = old_plan
            paper_broker_service.current_fx_rate = old_fx
            paper_broker_service._latest_market_date = old_date
        order = state['orders'][0]
        assert order['order_origin'] == 'LIVE_CANDIDATE'
        assert order['signal_origin'] == 'intraday_latest_scan'
        assert order['live_order_sent'] is False


def main():
    test_incomplete_daily_bar_uses_previous_completed_flow()
    test_closed_session_keeps_current_flow()
    test_official_journal_excludes_experimental_from_publish_and_summary()
    test_live_paper_order_is_tagged_research_origin()
    print('P0 structure PASS')


if __name__=='__main__':main()
