import gap_guard_research as gap
import rsi2_upside_gap_research as research


def test_only_rsi2_changes_in_focused_policies():
    base=research.POLICIES['baseline_current']
    mid=research.POLICIES['rsi2_up_0_50']
    tight=research.POLICIES['rsi2_up_0_25']
    for sid in ('confirmed_pullback','momentum_pullback'):
        assert base[sid]=='current'
        assert mid[sid]=='current'
        assert tight[sid]=='current'
    assert base['rsi2_trend_reversion']=='current'
    assert mid['rsi2_trend_reversion']=='down_current_up_0_50'
    assert tight['rsi2_trend_reversion']=='down_current_up_0_25'


def test_rsi2_intermediate_guard_preserves_downside_and_sets_half_atr_upside():
    p={'atr':2.0,'buy_low':99.0,'buy_high':101.0}
    current=gap.guard_sides(p,100.0,'current')
    down,up=gap.guard_sides(p,100.0,'down_current_up_0_50')
    assert down==current[0]
    assert up==1.0
    assert up < current[1]


def main():
    test_only_rsi2_changes_in_focused_policies()
    test_rsi2_intermediate_guard_preserves_downside_and_sets_half_atr_upside()
    print('RSI2 upside gap research PASS')


if __name__=='__main__':main()
