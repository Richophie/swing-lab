from datetime import date
from pathlib import Path

import portfolio_batch_allocation_diagnostic as b


def row(key, symbol, priority, risk=.01):
    return {
        'start_date':'2025-01-02','end_date':'2025-01-05','change':.02,
        'risk_fraction':risk,'priority':priority,'key':key,'symbol':symbol,
        'strategy_id':'x','marks':[],
    }


def test_batch_allocates_same_factor_when_cash_is_short():
    rows=[row('A','AAA',3),row('B','BBB',2),row('C','CCC',1)]
    x=b.batch_prorata_portfolio(rows,date(2025,1,1),date(2025,12,31),10)
    assert x['trades']==3
    assert x['scaled_days']>=1
    assert x['scaled_entries']==3
    assert 0 < x['mean_allocation_factor'] < 1
    assert x['reject_capacity']==0


def test_capacity_still_selects_top_ranked_candidates():
    rows=[row('A','AAA',3),row('B','BBB',2),row('C','CCC',1)]
    x=b.batch_prorata_portfolio(rows,date(2025,1,1),date(2025,12,31),2)
    assert x['trades']==2
    assert x['reject_capacity']==1


def test_explicitly_posthoc_no_grid():
    src=Path('portfolio_batch_allocation_diagnostic.py').read_text(encoding='utf-8')
    assert 'posthoc_allocation_diagnostic_only' in src
    assert "'no_grid_search': True" in src
    assert 'historical returns are not a fresh holdout' in src
    assert 'production/실거래 사이징과 priority는 자동 변경하지 않습니다.' in src


def main():
    test_batch_allocates_same_factor_when_cash_is_short()
    test_capacity_still_selects_top_ranked_candidates()
    test_explicitly_posthoc_no_grid()
    print('batch allocation diagnostic PASS')


if __name__=='__main__':
    main()
