from datetime import date
from pathlib import Path

import portfolio_priority_mechanism as m


def test_current_pct_normalizes_equal_donchian_priority():
    d={'donchian_55':{'priority':[2.0,2.0,2.0],'quality':[10,50,90]}}
    c={'strategy_id':'donchian_55','_quality':90}
    r={'strategy_id':'donchian_55','priority':2.0,'_audit_current_priority':2.0}
    assert m.rank_value('current_pct',c,r,d)==0.5
    assert m.rank_value('quality_pct',c,r,d)>0.8


def test_allocation_trace_detects_cash_limiting():
    rows=[]
    for i in range(4):
        rows.append({
            'start_date':'2025-01-02','end_date':'2025-01-05','change':0.01,
            'risk_fraction':0.01,'priority':4-i,'key':str(i),'symbol':f'S{i}',
            'strategy_id':'x','marks':[],
        })
    x=m.allocation_trace(rows,date(2025,1,1),date(2025,12,31),10)
    assert x['accepted_entries']>=3
    assert x['cash_limited_entries']>=1 or x['cash_exhausted_rejects']>=1
    assert x['capacity_rejects']==0


def test_mechanism_is_explicitly_posthoc_and_rank_has_no_future_outcome():
    src=Path('portfolio_priority_mechanism.py').read_text(encoding='utf-8')
    rank=src[src.index('def rank_value'):src.index('def ranked_rows')]
    for forbidden in ('change','return_pct','mdd_pct','test_end'):
        assert forbidden not in rank, forbidden
    assert 'posthoc_mechanism_diagnostic_only' in src
    assert 'not a fresh holdout' in src
    assert 'production/실거래 priority는 이 파일로 자동 변경하지 않습니다.' in src


def main():
    test_current_pct_normalizes_equal_donchian_priority()
    test_allocation_trace_detects_cash_limiting()
    test_mechanism_is_explicitly_posthoc_and_rank_has_no_future_outcome()
    print('priority allocation mechanism PASS')


if __name__=='__main__':
    main()
