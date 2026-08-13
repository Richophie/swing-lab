import rsi2_broad_regime_research as broad


def _trade(symbol, ret):
    return {
        'symbol':symbol,'ret':ret,'reason':'기간종료',
        'gross_risk_reward':1.3,'net_risk_reward':1.15,'cost_rr_drag':.15,
    }


def test_symbol_robustness_detects_concentration_and_leave_one_out():
    data={
        'AAA':[_trade('AAA',.02),_trade('AAA',.01)],
        'BBB':[_trade('BBB',-.01)],
        'CCC':[_trade('CCC',.005)],
    }
    r=broad._symbol_robustness(data)
    assert r['active_symbols']==3
    assert 0 < r['positive_avg_symbol_pct'] < 100
    assert r['top5_trade_share_pct']==100.0
    assert r['leave_one_symbol_out_avg_return_pct_min'] is not None
    assert r['leave_one_symbol_out_avg_return_pct_max'] is not None


def test_research_universe_has_deterministic_fallback():
    old_load=broad.load_us_universe
    broad.load_us_universe=lambda: (_ for _ in ()).throw(RuntimeError('offline'))
    try:
        symbols,source=broad.research_universe()
    finally:
        broad.load_us_universe=old_load
    assert source=='static_liquid_fallback'
    assert len(symbols)==broad.TARGET_SYMBOLS
    assert 'AAPL' in symbols


def main():
    test_symbol_robustness_detects_concentration_and_leave_one_out()
    test_research_universe_has_deterministic_fallback()
    print('RSI2 broad regime research PASS')


if __name__=='__main__':main()
