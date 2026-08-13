import pandas as pd

import momentum_regime_research as research


def test_classify_trade_uses_expected_regime_buckets():
    idx=pd.DatetimeIndex([pd.Timestamp('2026-01-05')])
    f=pd.DataFrame({'spy_ret5':[.04],'spy_ret20':[-.06],'spy_dd20':[-.07],'spy_rv20':[.30],'spy_vol_pct_252':[.90]},index=idx)
    out=research.classify_trade({'signal_date':'2026-01-05'},f)
    assert out['vol_bucket']=='vol_high_80p'
    assert out['dd_bucket']=='dd_deep_5pct'
    assert out['ret5_bucket']=='ret5_rebound_ge3pct'
    assert out['deep_drawdown_rebound'] is True


def test_nonpanic_normal_market_is_not_deep_rebound():
    idx=pd.DatetimeIndex([pd.Timestamp('2026-01-05')])
    f=pd.DataFrame({'spy_ret5':[.01],'spy_ret20':[.03],'spy_dd20':[-.01],'spy_rv20':[.12],'spy_vol_pct_252':[.50]},index=idx)
    out=research.classify_trade({'signal_date':'2026-01-05'},f)
    assert out['vol_bucket']=='vol_mid'
    assert out['dd_bucket']=='dd_shallow_lt2pct'
    assert out['ret5_bucket']=='ret5_up_0_3pct'
    assert out['deep_drawdown_rebound'] is False


def main():
    test_classify_trade_uses_expected_regime_buckets()
    test_nonpanic_normal_market_is_not_deep_rebound()
    print('momentum regime research PASS')


if __name__=='__main__':main()
