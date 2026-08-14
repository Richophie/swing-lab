from datetime import date
from pathlib import Path

import portfolio_priority_audit as p
import strategy_optimizer_runner as mtm


def row(key, symbol, start, end, priority, change=.05, quality=50):
    return {
        'start_date': start,
        'end_date': end,
        'change': change,
        'risk_fraction': .05,
        'priority': priority,
        'key': key,
        'symbol': symbol,
        'strategy_id': 'donchian_55',
        'strategy_name': 'Donchian',
        'reason': 'test',
        'marks': [],
        '_audit_quality': quality,
        '_audit_current_priority': priority,
    }


def test_empirical_percentile_ties_are_equal():
    xs=[1.0,2.0,2.0,2.0,3.0]
    assert p.empirical_percentile(xs,2.0)==.5
    assert p.empirical_percentile(xs,1.0)==.1
    assert p.empirical_percentile(xs,3.0)==.9


def test_trace_matches_capacity_count_and_priority_order():
    rows=[
        row('A','AAA','2025-01-02','2025-01-05',2.0,.01,40),
        row('B','BBB','2025-01-02','2025-01-05',3.0,.02,80),
        row('C','CCC','2025-01-02','2025-01-05',1.0,.30,90),
    ]
    start=date(2025,1,1);end=date(2025,12,31)
    base=mtm.mtm_portfolio(rows,start,end,2)
    trace=p.decision_trace(rows,start,end,2)
    assert base['reject_capacity']==1
    assert len(trace['rejected_capacity'])==1
    assert [x['symbol'] for x in trace['accepted']]==['BBB','AAA']
    assert trace['rejected_capacity'][0]['symbol']=='CCC'


def test_rankers_use_no_future_outcome():
    src=Path('portfolio_priority_audit.py').read_text(encoding='utf-8')
    rank=src[src.index('def rank_value'):src.index('def rows_for_ranker')]
    for forbidden in ('change','return_pct','mdd_pct','test_end'):
        assert forbidden not in rank, forbidden
    assert 'empirical_percentile' in rank
    choose=src[src.index('def choose_quality_intensity'):src.index('def train_distributions')]
    assert 'train_pick_score' in choose
    assert 'fold["test_' not in choose
    assert 'No ranker is promoted' in src or 'no ranker is promoted' in src


def main():
    test_empirical_percentile_ties_are_equal()
    test_trace_matches_capacity_count_and_priority_order()
    test_rankers_use_no_future_outcome()
    print('priority slot audit PASS')


if __name__=='__main__':
    main()
