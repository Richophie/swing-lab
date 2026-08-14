from datetime import date

import capital_mechanism_audit as cma


def row(tier='low', change=.10, symbol='A'):
    conviction={'low':.25,'mid':.60,'high':.90}[tier]
    return {
        'start_date':'2026-01-02','end_date':'2026-01-05','change':change,
        'risk_fraction':.10,'priority':conviction,'_v2_conviction':conviction,'_v2_tier':tier,
        'key':symbol,'symbol':symbol,'strategy_id':'donchian_55',
        'marks':[('2026-01-02',1.0),('2026-01-05',1.0+change)],
    }


def test_controls_are_pre_registered_and_not_grid():
    assert list(cma.POLICIES)==['flat_100','flat_075','flat_050','tiered','reversed']
    assert cma.POLICIES['tiered']=={'label':'점수순 0.50/0.75/1.00%','low':.5,'mid':.75,'high':1.0}
    assert cma.POLICIES['reversed']=={'label':'역순 1.00/0.75/0.50%','low':1.0,'mid':.75,'high':.5}


def test_uniform_and_tiered_position_sizes_are_isolated():
    rows=[row('low',symbol='L'),row('mid',symbol='M'),row('high',symbol='H')]
    start,end=date(2026,1,1),date(2026,1,10)
    flat75=cma.mechanism_portfolio(rows,start,end,10,cma.POLICIES['flat_075'])
    tiered=cma.mechanism_portfolio(rows,start,end,10,cma.POLICIES['tiered'])
    reversed_=cma.mechanism_portfolio(rows,start,end,10,cma.POLICIES['reversed'])
    assert flat75['trades']==3 and tiered['trades']==3 and reversed_['trades']==3
    # 10% stop risk: 1% account-risk budget => 10% notional of 3m = 300k.
    assert round(sum(flat75['capital_by_tier'].values()),2)==675000.00
    assert round(sum(tiered['capital_by_tier'].values()),2)==675000.00
    assert tiered['capital_by_tier']['low'] < tiered['capital_by_tier']['high']
    assert reversed_['capital_by_tier']['low'] > reversed_['capital_by_tier']['high']


def test_exposure_diagnostics_are_present():
    result=cma.mechanism_portfolio([row('mid')],date(2026,1,1),date(2026,1,10),10,cma.POLICIES['flat_075'])
    assert 0 <= result['avg_exposure_pct'] <= 100
    assert 0 <= result['avg_cash_pct'] <= 100
    assert result['allocation_ratio'] > 0
    assert result['avg_open_positions'] >= 0


def test_v1_and_production_are_untouched():
    source=open('capital_mechanism_audit.py',encoding='utf-8').read()
    assert 'priority_challenger_v1_state.json' not in source
    assert 'priority_challenger_v1_calibration.json' not in source
    assert 'submit_order' not in source
    assert "'grid_search': False" in source
    assert "'v1_untouched': True" in source
    assert "promotion_status': 'mechanism_diagnostic_only_not_fresh_holdout'" in source


def main():
    test_controls_are_pre_registered_and_not_grid()
    test_uniform_and_tiered_position_sizes_are_isolated()
    test_exposure_diagnostics_are_present()
    test_v1_and_production_are_untouched()
    print('capital mechanism audit PASS')


if __name__=='__main__':main()
