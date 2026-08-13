from execution_quality import plan_execution_quality
from net_rr_research import VARIANTS, _bucket, _passes, pooled_stats


def test_zero_cost_net_rr_matches_gross_rr():
    plan = {'entry_low':99.0,'entry_high':101.0,'target':105.0,'stop':95.0}
    q = plan_execution_quality(plan, commission_pct=0, slippage_bps=0, half_spread_bps=0)
    assert q['gross_risk_reward'] == 1.0
    assert q['net_risk_reward'] == 1.0
    assert q['cost_rr_drag'] == 0.0


def test_configured_costs_reduce_rr_before_trade():
    plan = {'entry_low':99.0,'entry_high':101.0,'target':106.0,'stop':95.0}
    q = plan_execution_quality(plan)
    assert q['gross_risk_reward'] == 1.2
    assert q['net_risk_reward'] < q['gross_risk_reward']
    assert q['net_target_return_pct'] < 6.0
    assert q['net_stop_return_pct'] < -5.0
    assert q['cost_rr_drag'] > 0


def test_rr_variant_gate_uses_pretrade_metric():
    q = {'gross_risk_reward':1.25,'net_risk_reward':1.12}
    assert _passes(q, VARIANTS['gross_1_20'])
    assert _passes(q, VARIANTS['net_1_10'])
    assert not _passes(q, VARIANTS['net_1_20'])


def test_oos_buckets_are_per_symbol_index_not_shared_calendar():
    trades = [
        {'signal_i':210,'ret':.01,'reason':'목표달성','gross_risk_reward':1.3,'net_risk_reward':1.2,'cost_rr_drag':.1},
        {'signal_i':700,'ret':-.01,'reason':'손절','gross_risk_reward':1.4,'net_risk_reward':1.3,'cost_rr_drag':.1},
        {'signal_i':900,'ret':.005,'reason':'기간종료','gross_risk_reward':1.5,'net_risk_reward':1.4,'cost_rr_drag':.1},
    ]
    b = _bucket(trades, split_i=700, recent_start_i=850)
    assert len(b['is_first_70pct']) == 1
    assert len(b['oos_last_30pct']) == 2
    assert len(b['recent_2y']) == 1
    assert pooled_stats(b['oos_last_30pct'])['trades'] == 2


def main():
    test_zero_cost_net_rr_matches_gross_rr()
    test_configured_costs_reduce_rr_before_trade()
    test_rr_variant_gate_uses_pretrade_metric()
    test_oos_buckets_are_per_symbol_index_not_shared_calendar()
    print('net RR research PASS')


if __name__=='__main__':main()
