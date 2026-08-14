import json
from pathlib import Path

import priority_challenger_v1 as c


def fake_candidate(sid, symbol='AAA'):
    base={
        'symbol':symbol,'strategy_id':sid,'signal_date':'2026-08-12','entry_date':'2026-08-13',
        'elite_score':80.0,'net_risk_reward':2.0,'market_state':'좋음','quality_features':{},
    }
    if sid=='sma200_20_squeeze':
        base['quality_features']={'body_atr':1.0,'ma_spread_pct':.01,'crosses_30':1,'volume_ratio':1.0,'ma_clearance_atr':.5,'sma200_slope_20d_pct':.03,'atr_pct':.02}
    if sid=='donchian_55':
        base['quality_features']={'breakout_atr':.5,'volume_ratio':1.2,'close_position':.8,'body_atr':.7,'sma200_slope_20d_pct':.03,'atr_pct':.02}
    return base


def test_percentile_ties_and_fixed_formula():
    assert c.empirical_percentile([2.0,2.0,2.0],2.0)==.5
    cal={'reference':{'donchian_55':{'quality':[0,50,100],'current_priority':[2,2,2]}}}
    x=fake_candidate('donchian_55')
    r=c._quality_and_priority(x,cal)
    assert r['current_priority_percentile']==.5
    assert 0<=r['quality_percentile']<=1
    assert abs(r['challenger_priority']-(r['current_priority_percentile']+r['quality_percentile'])/2)<1e-6


def test_freeze_is_create_once(tmp_path):
    old_pool,old_cal=c.POOL,c.CALIBRATION
    try:
        c.POOL=tmp_path/'pool.json';c.CALIBRATION=tmp_path/'cal.json'
        trades=[]
        for sid in c.FAMILY:
            trades.extend([fake_candidate(sid,'AAA'),fake_candidate(sid,'BBB')])
        c.POOL.write_text(json.dumps({'ready':True,'version':4,'generated_at':'x','eligible_symbols':['AAA','BBB'],'trades':trades}),encoding='utf-8')
        a=c.freeze_calibration()
        assert a['mutable'] is False
        assert a['freeze_date']=='2026-08-13'
        assert a['forward_start_date']=='2026-08-14'
        assert a['family']==list(c.FAMILY)
        assert all(a['reference_counts'][sid]==2 for sid in c.FAMILY)
        # A later source pool must not rewrite the frozen reference.
        c.POOL.write_text(json.dumps({'ready':True,'version':4,'generated_at':'later','eligible_symbols':['ZZZ'],'trades':trades}),encoding='utf-8')
        b=c.freeze_calibration()
        assert b==a
        assert b['frozen_symbols']==['AAA','BBB']
    finally:
        c.POOL=old_pool;c.CALIBRATION=old_cal


def test_default_state_cannot_trade_live():
    s=c._default_state({'priority':{'current_weight':.5,'quality_weight':.5},'created_at':'x'})
    assert s['live_trading_enabled'] is False
    assert s['production_mutation_enabled'] is False
    assert s['meta']['auto_retune'] is False
    assert s['meta']['max_positions']==10
    assert s['meta']['quality_min_percentile']==.5


def test_source_guards_no_outcome_rank_or_live_broker():
    src=Path('priority_challenger_v1.py').read_text(encoding='utf-8')
    rank=src[src.index('def _quality_and_priority'):src.index('def _market_state')]
    for forbidden in ('pnl_krw','return_pct','exit_date','future'):
        assert forbidden not in rank, forbidden
    assert 'submit_order' not in src
    assert 'live_trading_enabled' in src and "'live_trading_enabled': False" in src
    assert "MIN_QUALITY_PERCENTILE = 0.50" in src
    assert "CURRENT_WEIGHT = 0.50" in src and "QUALITY_WEIGHT = 0.50" in src
    assert "FORWARD_START_DATE = '2026-08-14'" in src
    assert 'Refusing to mutate a state created by another challenger version' in src


def main():
    test_percentile_ties_and_fixed_formula()
    import tempfile
    with tempfile.TemporaryDirectory() as d:test_freeze_is_create_once(Path(d))
    test_default_state_cannot_trade_live()
    test_source_guards_no_outcome_rank_or_live_broker()
    print('priority challenger v1 PASS')


if __name__=='__main__':main()
