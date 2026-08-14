from datetime import date

import capital_velocity_research as cvr


def row(symbol='A', change=.10):
    return {
        'start_date':'2026-01-02','end_date':'2026-01-05','change':change,
        'risk_fraction':.10,'priority':.8,'key':symbol,'symbol':symbol,
        'strategy_id':'donchian_55','marks':[('2026-01-02',1.0),('2026-01-05',1.0+change)],
    }


def test_policies_are_small_preregistered_set():
    assert list(cvr.POLICIES)==[
        'ref_075_cap10','cap15_075','cap20_075','broad060_cap15','broad050_cap20',
        'reserve15_075_cap20','adaptive075_050_cap20'
    ]
    assert cvr.POLICIES['ref_075_cap10']['risk_pct']==.75
    assert cvr.POLICIES['cap20_075']['capacity']==20
    assert cvr.POLICIES['reserve15_075_cap20']['cash_floor_pct']==.15
    assert cvr.POLICIES['adaptive075_050_cap20']['throttle_risk_pct']==.50


def test_risk_throttle_only_when_cash_is_low():
    p=cvr.POLICIES['adaptive075_050_cap20']
    assert cvr.risk_budget(p,800,1000)==.0075
    assert cvr.risk_budget(p,200,1000)==.005


def test_smaller_risk_allocates_smaller_position():
    rows=[row()]
    start,end=date(2026,1,1),date(2026,1,10)
    a=cvr.velocity_portfolio(rows,start,end,cvr.POLICIES['ref_075_cap10'])
    b=cvr.velocity_portfolio(rows,start,end,cvr.POLICIES['broad050_cap20'])
    assert a['trades']==b['trades']==1
    assert a['allocated_capital'] > b['allocated_capital']
    assert a['notional_turns_per_year'] > b['notional_turns_per_year']


def test_hard_cash_floor_preserves_cash_and_never_leverages():
    rows=[row(str(i),.02) for i in range(20)]
    start,end=date(2026,1,1),date(2026,1,10)
    r=cvr.velocity_portfolio(rows,start,end,cvr.POLICIES['reserve15_075_cap20'])
    assert 0 <= r['avg_exposure_pct'] <= 100
    assert 0 <= r['avg_cash_pct'] <= 100
    assert r['allocation_ratio'] <= 1.0 + 1e-9


def test_research_does_not_touch_forward_or_live_paths():
    source=open('capital_velocity_research.py',encoding='utf-8').read()
    assert 'priority_challenger_v1_state.json' not in source
    assert 'priority_challenger_v2_state.json' not in source
    assert 'submit_order' not in source
    assert "'grid_search': False" in source
    assert "'v1_v2_forward_untouched': True" in source
    assert 'Early winner harvesting / partial exits are intentionally reserved' in source


def main():
    test_policies_are_small_preregistered_set()
    test_risk_throttle_only_when_cash_is_low()
    test_smaller_risk_allocates_smaller_position()
    test_hard_cash_floor_preserves_cash_and_never_leverages()
    test_research_does_not_touch_forward_or_live_paths()
    print('capital velocity research PASS')


if __name__=='__main__':main()
