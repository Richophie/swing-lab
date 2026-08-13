from __future__ import annotations

import json
from pathlib import Path
import tempfile

import journal
import paper_broker_service as pbs
from risk_observability import event_bucket, snapshot_event_risk


def check(cond, message):
    if not cond:
        raise AssertionError(message)


def main():
    er = {'risk_code':'WITHIN_HOLD','risk_label':'보유기간 중 실적 가능 · 5일','earnings_date':'2026-08-20','days_until':5,'confidence':'confirmed','stale':False,'hold_calendar_days':8,'source_day_diff':0,'checked_at':'2026-08-13T09:00:00+00:00'}
    snap = snapshot_event_risk(er)
    check(snap['risk_code']=='WITHIN_HOLD' and snap['days_until']==5, 'snapshot should preserve event context')
    er['risk_code']='CLEAR'
    check(snap['risk_code']=='WITHIN_HOLD', 'snapshot must be independent from later source mutation')
    check(event_bucket({'event_risk_snapshot':snap})=='WITHIN_HOLD', 'event bucket should use frozen snapshot')
    check(event_bucket({})=='LEGACY_UNTRACKED', 'legacy records should stay explicit')

    row={'symbol':'AAA','name_ko':'AAA','security_name':'AAA Inc','rsi':40,'d120':2,'bb_pos':10,'event_risk':dict(snap),'sparkline':[],'bb_high_spark':[],'bb_low_spark':[]}
    sig={'strategy_id':'rsi2_trend_reversion','strategy_name':'RSI2','elite_score':80,'strategy_score':90,'evidence':'x','selection_reason':'y'}
    plan={'entry_low':10,'entry_high':10.2,'target':11,'stop':9,'target_pct':8,'stop_pct':10,'target_days':{'days_low':1,'days_high':5},'risk_reward':1.2}
    frozen=journal.freeze_signal(row,sig,plan,'2026-08-13T21:00:00+00:00','2026-08-13')
    check(frozen['event_risk_snapshot']['risk_code']=='WITHIN_HOLD', 'official journal must freeze event risk')
    check(frozen['publication_status']=='CONFIRMED_CLOSE', 'event snapshot must not alter publication status')

    closed1=dict(frozen);closed1.update({'status_code':'SUCCESS','outcome_return_pct':5.0})
    closed2=dict(frozen);closed2['event_risk_snapshot']=snapshot_event_risk({'risk_code':'CLEAR'});closed2.update({'status_code':'STOP','outcome_return_pct':-3.0})
    summary=journal._summarize_items([closed1,closed2])
    check(summary['by_event_risk']['WITHIN_HOLD']['closed']==1, 'event bucket outcome count should be tracked')
    check(summary['by_event_risk']['CLEAR']['avg_return_pct']==-3.0, 'event bucket average return should be tracked')

    with tempfile.TemporaryDirectory() as td:
        scan_path=Path(td)/'latest_scan.json'
        scan_path.write_text(json.dumps({'scanned_at':'2026-08-13T09:00:00+00:00','results':[{
            'symbol':'AAA','event_risk':dict(snap),
            'strategy_signals':[{'strategy_id':'rsi2_trend_reversion','strategy_name':'RSI2','elite_pass':True,'elite_score':80,'strategy_score':90}],
            'strategy_trade_plans':{'rsi2_trend_reversion':plan},'trade_plan':plan,
        }]}),encoding='utf-8')
        old=pbs.SCAN_FILE
        try:
            pbs.SCAN_FILE=scan_path
            info=pbs.latest_plan('AAA','rsi2_trend_reversion')
        finally:
            pbs.SCAN_FILE=old
        check(info['event_risk_snapshot']['risk_code']=='WITHIN_HOLD', 'Paper latest-plan metadata should carry event snapshot')
        check(info['plan']==plan, 'observability metadata must not modify trade plan')

    print('risk observability PASS')


if __name__=='__main__':
    main()
