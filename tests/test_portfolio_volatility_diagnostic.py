from pathlib import Path

import portfolio_volatility_diagnostic as v


def test_classifier():
    assert v.classify_snapshot(110,100,210,200,.10)=='green_low_vol'
    assert v.classify_snapshot(110,100,210,200,.50)=='green_mid_vol'
    assert v.classify_snapshot(110,100,210,200,.90)=='green_high_vol'
    assert v.classify_snapshot(110,100,190,200,.90)=='mixed'
    assert v.classify_snapshot(90,100,190,200,.10)=='risk_off'


def test_source_is_diagnostic_not_gate_search():
    src=Path('portfolio_volatility_diagnostic.py').read_text(encoding='utf-8')
    assert 'trailing 252 observations only' in src
    assert 'No state is excluded' in src
    choose=src[src.index('def choose_quality_intensity'):src.index('def state_breakdown')]
    assert '_vol_state' not in choose
    assert 'train_pick_score' in choose
    assert 'test_full_no_market_filter' in src
    assert 'state_only_sleeve' in src


def main():
    test_classifier();test_source_is_diagnostic_not_gate_search();print('volatility diagnostic PASS')


if __name__=='__main__':main()
