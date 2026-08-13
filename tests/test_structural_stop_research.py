import pandas as pd

from structural_stop_research import plan_from_row, selection_pass


def row():
    return pd.Series({'close':100.0,'atr':2.0,'recent_low':98.5,'recent_high':106.0,'s20':101.0,'s120':100.0})


def test_rsi2_baseline_forces_stop_to_1_5_atr():
    p=plan_from_row(row(),'rsi2_trend_reversion','force_1_50')
    assert round(p['raw_stop_atr_multiple'],2)==1.15
    assert round(p['stop_atr_multiple'],2)==1.50
    assert p['stop'] < p['raw_stop']


def test_structural_raw_keeps_chart_stop_without_forced_widening():
    p=plan_from_row(row(),'rsi2_trend_reversion','structural_raw')
    assert p['stop']==p['raw_stop']
    assert round(p['stop_atr_multiple'],2)==1.15
    assert p['structural_rejected'] is False


def test_structural_minimum_rejects_instead_of_widening():
    p=plan_from_row(row(),'rsi2_trend_reversion','structural_reject_lt_1_25')
    assert p['structural_rejected'] is True
    assert p['stop']==p['raw_stop']
    result=selection_pass(95,{'relative_volume':1,'volume_5d_vs_20d':.9,'up_down_volume_ratio':1.2,'avg_dollar_volume_20d':100_000_000},p,'좋음',False,100,'rsi2_trend_reversion')
    assert result['pass'] is False
    assert result['reason']=='structural_min_reject'


def test_force_1_25_is_tighter_than_current_baseline():
    base=plan_from_row(row(),'rsi2_trend_reversion','force_1_50')
    tight=plan_from_row(row(),'rsi2_trend_reversion','force_1_25')
    assert tight['stop'] > base['stop']
    assert round(tight['stop_atr_multiple'],2)==1.25


def main():
    test_rsi2_baseline_forces_stop_to_1_5_atr()
    test_structural_raw_keeps_chart_stop_without_forced_widening()
    test_structural_minimum_rejects_instead_of_widening()
    test_force_1_25_is_tighter_than_current_baseline()
    print('structural stop research PASS')


if __name__=='__main__':main()
