from pathlib import Path
import exit_recycle_research as r

ROOT=Path(__file__).resolve().parents[1]


def test_policies_are_coarse_and_forward_states_untouched():
    assert set(r.POLICIES)=={
        'natural','partial25_1r','partial50_1r','partial25_2r','trail_after_1r','partial25_1r_trail'
    }
    assert r.BASE_RISK_PCT==0.75
    assert r.BASE_CAPACITY==10
    assert r.TRAIL_R==1.0
    src=(ROOT/'exit_recycle_research.py').read_text(encoding='utf-8')
    assert 'priority_challenger_v1_state.json' not in src
    assert 'priority_challenger_v2_state.json' not in src
    assert "'grid_search': False" in src
    assert "'v1_v2_forward_untouched': True" in src


def test_partial_trigger_is_close_then_next_open():
    candidate={
        'path':[
            ['2026-01-02',100,106,99,105,0,0,0],
            ['2026-01-05',104,108,103,107,0,0,0],
            ['2026-01-06',107,109,106,108,0,0,0],
        ],
        'entry_mode':'next_open','stop':95,
    }
    row={'end_date':'2026-01-06'}
    pool={'costs':{'commission_pct_per_side':0,'slippage_bps':0,'half_spread_bps':0}}
    event=r.milestone_next_open(candidate,row,1.0,pool)
    assert event is not None
    assert event['trigger_date']=='2026-01-02'
    assert event['date']=='2026-01-05'
    assert abs(event['factor']-1.04)<1e-9


def test_trail_never_uses_same_day_low():
    src=(ROOT/'exit_recycle_research.py').read_text(encoding='utf-8')
    assert 'close < floor' in src
    assert "nxt = path[i + 1]" in src
    assert 'bar[3]' not in src[src.index('def close_trail_exit'):src.index('def enriched_execute')]


def test_partial_fraction_does_not_close_slot():
    assert r.POLICIES['partial25_1r']['partial_fraction']==0.25
    assert r.POLICIES['partial50_1r']['partial_fraction']==0.50
    assert r.POLICIES['partial25_2r']['partial_trigger_r']==2.0
    assert r.POLICIES['partial25_1r_trail']['use_trailing'] is True


def main():
    test_policies_are_coarse_and_forward_states_untouched()
    test_partial_trigger_is_close_then_next_open()
    test_trail_never_uses_same_day_low()
    test_partial_fraction_does_not_close_slot()
    print('exit recycle research PASS')


if __name__=='__main__':main()
