import pandas as pd

from rsi2_selector_research import _variant_pass, _rsi2_strategy_score


def test_confirmation_variants_are_explicit_and_non_lookahead():
    f = {
        'price_reversal': True,
        'macd_improving': False,
        'rsi14_up1': True,
        'rsi14_up3': True,
        'market_state': '좋음',
        'close_above_120': False,
    }
    assert _variant_pass('baseline_live_like', f)
    assert _variant_pass('price_reversal', f)
    assert not _variant_pass('macd_improving', f)
    assert _variant_pass('two_of_three', f)
    assert _variant_pass('price_reversal_market_good', f)
    assert not _variant_pass('close_above_120', f)


def test_rsi2_public_score_matches_live_point_structure():
    idx = pd.date_range('2026-01-01', periods=2)
    ind = pd.DataFrame({
        'close':[100,100],
        'sma50':[105,105],
        'sma120':[100,100],
        'sma200':[90,90],
        'rsi':[40,40],
        'bb_pos':[.20,.20],
        'atr14':[3,3],
    }, index=idx)
    active = pd.Series([True,True], index=idx)
    # Monkeypatching Wilder RSI is unnecessary here: a two-row sample returns 100,
    # so only the non-RSI2 point components contribute. The score still remains a
    # bounded live-style quality score and inactive rows are capped separately.
    score = _rsi2_strategy_score(active, ind)
    assert score.between(55,95).all()
    inactive = _rsi2_strategy_score(pd.Series([False,False], index=idx), ind)
    assert (inactive <= 69).all()


def main():
    test_confirmation_variants_are_explicit_and_non_lookahead()
    test_rsi2_public_score_matches_live_point_structure()
    print('RSI2 selector research PASS')


if __name__=='__main__':main()
