from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import tempfile

import earnings_events as ee


def check(cond, message):
    if not cond:
        raise AssertionError(message)


def main():
    chosen, confidence, diff = ee._choose_sources('2026-08-20', '2026-08-20')
    check(chosen == '2026-08-20' and confidence == 'confirmed' and diff == 0, 'same-date sources must confirm')

    chosen, confidence, diff = ee._choose_sources('2026-08-20', '2026-08-24')
    check(chosen == '2026-08-20' and confidence == 'conflicting' and diff == 4, 'material source disagreement must be explicit')

    now = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
    imminent = ee._risk_from_entry({'earnings_date':'2026-08-15','confidence':'confirmed','stale':False}, {'days_max':5}, now)
    check(imminent['risk_code'] == 'IMMINENT', '0-3 day earnings must be imminent')

    within = ee._risk_from_entry({'earnings_date':'2026-08-20','confidence':'confirmed','stale':False}, {'days_max':5}, now)
    check(within['risk_code'] == 'WITHIN_HOLD', 'earnings inside converted hold window must be within-hold')

    upcoming = ee._risk_from_entry({'earnings_date':'2026-08-26','confidence':'confirmed','stale':False}, {'days_max':5}, now)
    check(upcoming['risk_code'] == 'UPCOMING', 'near earnings outside hold window should be upcoming')

    conflict = ee._risk_from_entry({'earnings_date':'2026-08-20','confidence':'conflicting','stale':False}, {'days_max':5}, now)
    check(conflict['risk_code'] == 'UNKNOWN', 'conflicting dates must never look safe')

    rows = [
        {'symbol':'AAA','elite_pass':True,'elite_score':81.7,'score':81.7,'trade_plan':{'days_max':5,'entry_low':10.0,'entry_high':10.2,'target':11.0,'stop':9.2}},
        {'symbol':'BBB','elite_pass':False,'elite_score':70.0,'score':70.0,'trade_plan':{'days_max':5}},
    ]
    before = json.loads(json.dumps(rows, ensure_ascii=False))
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / 'cache.json'
        p.write_text(json.dumps({
            'version':1,'updated_at':None,'symbols':{
                'AAA':{
                    'symbol':'AAA','earnings_date':'2026-08-20','confidence':'confirmed',
                    'source_dates':{'get_earnings_dates':'2026-08-20','calendar':'2026-08-20'},
                    'source_day_diff':0,'checked_at':'2026-08-13T11:00:00+00:00','last_attempt_at':'2026-08-13T11:00:00+00:00','stale':False,
                }
            }
        }),encoding='utf-8')
        out, meta = ee.enrich_elite_rows(rows, now_utc=now, cache_path=p)
        check(out[0]['event_risk']['risk_code'] == 'WITHIN_HOLD', 'elite row should receive cached event risk')
        check('event_risk' not in out[1], 'non-elite row must not trigger event enrichment')
        check(meta['earnings_cache_reused'] == 1 and meta['earnings_cache_queried'] == 0, 'fresh cache must prevent network query')
        for key in ('elite_pass','elite_score','score','trade_plan'):
            check(out[0][key] == before[0][key], f'event enrichment must not modify {key}')

    print('earnings event risk PASS')


if __name__ == '__main__':
    main()
