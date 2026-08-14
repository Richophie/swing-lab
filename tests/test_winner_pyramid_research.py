import winner_pyramid_research as wpr


def candidate(strategy='donchian_55'):
    return {
        'strategy_id':strategy,'entry_mode':'next_open','exit_mode':'donchian20_close' if strategy=='donchian_55' else 'sma20_close',
        'stop':95.0,'target':None,'path':[
            ['2026-01-02',100,102,99,101,100,100,90],
            ['2026-01-05',101,107,100,106,101,100,90],
            ['2026-01-06',107,109,104,108,102,100,90],
            ['2026-01-07',108,109,99,100,103,100,101],
        ]
    }


def base_row():
    return {'start_date':'2026-01-02','end_date':'2026-01-07','change':0.0,'risk_fraction':.05,'priority':.8,'key':'A','symbol':'A','strategy_id':'donchian_55','marks':[]}


def pool():
    return {'costs':{'commission_pct_per_side':.10,'slippage_bps':5,'half_spread_bps':2.5}}


def test_policy_set_is_small_and_preregistered():
    assert list(wpr.POLICIES)==['no_add','donchian_fresh_first','trend_fresh_first','all_fresh_first','trend_add_first']
    assert wpr.ADD_RISK_PCT==.25 and wpr.TRIGGER_R==1.0
    assert wpr.BASE_RISK_PCT==.75 and wpr.BASE_CAPACITY==10


def test_addon_waits_for_completed_plus_one_r_and_next_open():
    a=wpr.build_addon(candidate(),base_row(),pool())
    assert a is not None
    assert a['trigger_date']=='2026-01-05'
    assert a['start_date']=='2026-01-06'
    assert a['add_stop']==100.0
    assert a['trigger_r']==1.0


def test_no_averaging_down_path_exists():
    src=open('winner_pyramid_research.py',encoding='utf-8').read()
    assert "'no_averaging_down':True" in src
    assert "'addon_stop':'original base entry price'" in src
    assert 'priority_challenger_v1_state.json' not in src
    assert 'priority_challenger_v2_state.json' not in src
    assert 'submit_order' not in src
    assert "'grid_search':False" in src


def main():
    test_policy_set_is_small_and_preregistered();test_addon_waits_for_completed_plus_one_r_and_next_open();test_no_averaging_down_path_exists();print('winner pyramid research PASS')

if __name__=='__main__':main()
