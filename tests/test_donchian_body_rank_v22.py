import donchian_body_rank_v22 as v22


def test_revised_quality_is_body_only_for_donchian():
    d={'strategy_id':'donchian_55','_quality':88,'quality_features':{'body_atr':1.25,'volume_ratio':3.0}}
    assert v22.revised_quality_raw(d)==1.25
    c={'strategy_id':'confirmed_pullback','_quality':77,'quality_features':{}}
    assert v22.revised_quality_raw(c)==77.0


def test_revised_rows_use_train_percentiles_and_keep_half_half():
    pairs=[]
    for i,(priority,body) in enumerate([(1.0,.5),(2.0,1.0),(3.0,1.5)]):
        candidate={'strategy_id':'donchian_55','_quality':80,'quality_features':{'body_atr':body}}
        row={'priority':priority,'_audit_current_priority':priority,'start_date':'2020-01-02','end_date':'2020-01-03','symbol':str(i),'key':str(i)}
        pairs.append((candidate,row))
    fold={'train_start':__import__('datetime').date(2020,1,1),'train_end':__import__('datetime').date(2020,12,31)}
    dist=v22.train_distributions(pairs,fold)
    rows=v22.revised_rows(pairs,dist)
    assert rows[0]['priority'] < rows[1]['priority'] < rows[2]['priority']
    assert all(0 <= r['priority'] <= 1 for r in rows)
    assert rows[-1]['_v2_tier']=='high'


def test_no_gate_change_grid_or_v1_mutation():
    source=open('donchian_body_rank_v22.py',encoding='utf-8').read()
    assert 'priority_challenger_v1_state.json' not in source
    assert 'priority_challenger_v1_calibration.json' not in source
    assert 'submit_order' not in source
    assert "'eligibility_gate_changed': False" in source
    assert "'grid_search': False" in source
    assert "promotion_status': 'posthoc_development_only_not_fresh_holdout'" in source


def main():
    test_revised_quality_is_body_only_for_donchian()
    test_revised_rows_use_train_percentiles_and_keep_half_half()
    test_no_gate_change_grid_or_v1_mutation()
    print('donchian body rank v2.2 PASS')


if __name__=='__main__':main()
