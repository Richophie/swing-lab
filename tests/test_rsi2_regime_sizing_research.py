import rsi2_regime_sizing_research as research


def trade(symbol,state,entry,exit_,ret=.02,risk_pct=.05,rr=1.5):
    return {'symbol':symbol,'market_state':state,'entry_date':entry,'exit_date':exit_,'ret':ret,'risk_pct':risk_pct,'risk_reward':rr}


def test_neutral_half_risk_reduces_neutral_notional():
    trades=[trade('GOOD','좋음','2026-01-02','2026-01-05'),trade('NEUT','중립','2026-01-02','2026-01-05')]
    full=research.simulate_regime_portfolio(trades,1.0,False)
    half=research.simulate_regime_portfolio(trades,.5,False)
    assert full['accepted_trades']==2 and half['accepted_trades']==2
    assert half['avg_notional_by_market_state_krw']['중립'] < full['avg_notional_by_market_state_krw']['중립']
    assert half['avg_notional_by_market_state_krw']['좋음'] == full['avg_notional_by_market_state_krw']['좋음']


def test_neutral_zero_rejects_neutral_but_keeps_good():
    trades=[trade('GOOD','좋음','2026-01-02','2026-01-05'),trade('NEUT','중립','2026-01-02','2026-01-05')]
    out=research.simulate_regime_portfolio(trades,0.0,False)
    assert out['accepted_trades']==1
    assert out['accepted_by_market_state']=={'좋음':1}
    assert out['rejected_regime']==1


def test_good_first_can_change_capacity_selection_without_lookahead():
    trades=[
        trade('N1','중립','2026-01-02','2026-01-10',ret=-.02,rr=3.0),
        trade('N2','중립','2026-01-02','2026-01-10',ret=-.02,rr=2.8),
        trade('N3','중립','2026-01-02','2026-01-10',ret=-.02,rr=2.6),
        trade('G1','좋음','2026-01-02','2026-01-10',ret=.02,rr=1.2),
    ]
    rr_priority=research.simulate_regime_portfolio(trades,.5,False)
    good_priority=research.simulate_regime_portfolio(trades,.5,True)
    assert rr_priority['accepted_by_market_state'].get('좋음',0)==0
    assert good_priority['accepted_by_market_state'].get('좋음',0)==1
    assert good_priority['return_pct'] > rr_priority['return_pct']


def main():
    test_neutral_half_risk_reduces_neutral_notional()
    test_neutral_zero_rejects_neutral_but_keeps_good()
    test_good_first_can_change_capacity_selection_without_lookahead()
    print('RSI2 regime sizing research PASS')


if __name__=='__main__':main()
