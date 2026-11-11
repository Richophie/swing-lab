import numpy as np
import pandas as pd

import regime_rank_research as rr


def _frames(closes):
    index = pd.bdate_range('2020-01-01', periods=len(closes))
    close = pd.Series(closes, index=index, dtype=float)
    frame = pd.DataFrame({'Open': close, 'High': close * 1.01, 'Low': close * 0.99, 'Close': close, 'Volume': 1_000_000.0})
    return {'SPY': frame, 'QQQ': frame.copy()}


def _trade(day, ret, *, elite=80.0, rr_value=1.5, liquidity=1e9, symbol='AAA', state='좋음'):
    candidate = {'market_state': state, 'elite_score': elite, 'net_risk_reward': rr_value, 'smart_money_flow': {'avg_dollar_volume_20d': liquidity}}
    return {'signal_date': day, 'symbol': symbol, 'strategy_id': 'confirmed_pullback', 'return_pct': ret, 'reason': 'time', 'held_bars': 3, 'candidate': candidate}


def test_index_features_use_only_data_up_to_that_close():
    rising = list(np.linspace(100, 160, 260))
    base = rr.index_features(_frames(rising))
    crashed = rr.index_features(_frames(rising + [80.0]))
    shared = base.index[-1]
    assert bool(base.loc[shared, 'SPY_above50']) is True
    # Appending a later crash must not change any earlier row.
    assert base.loc[shared].equals(crashed.loc[shared])
    assert bool(crashed.iloc[-1]['SPY_above20']) is False
    assert crashed.iloc[-1]['SPY_ret5'] < -0.02


def test_gates_read_the_signal_day_row():
    up = {'SPY_above20': True, 'QQQ_above20': True, 'SPY_above50': True, 'QQQ_above50': False, 'SPY_ret20': 0.03, 'SPY_ret5': -0.03}
    c = {'market_state': '중립'}
    assert rr.gate_allows('current', c, None) is True
    assert rr.gate_allows('good_only', c, up) is False
    assert rr.gate_allows('above_sma20', c, up) is True
    assert rr.gate_allows('below_sma20', c, up) is False
    assert rr.gate_allows('above_sma50', c, up) is False
    assert rr.gate_allows('ret20_positive', c, up) is True
    assert rr.gate_allows('not_sliding', c, up) is False
    assert rr.gate_allows('above_sma20', c, None) is False


def test_top_n_per_day_ranks_inside_each_day_only():
    trades = [_trade('2020-01-02', 1.0, elite=90, symbol='A'), _trade('2020-01-02', -1.0, elite=70, symbol='B'),
              _trade('2020-01-02', 2.0, elite=80, symbol='C'), _trade('2020-01-03', -5.0, elite=10, symbol='D')]
    kept = rr.top_n_per_day(trades, 'elite_score', n=2)
    assert [t['symbol'] for t in kept] == ['A', 'C', 'D']
    assert [t['symbol'] for t in rr.top_n_per_day(trades, 'avg_dollar_volume_20d', n=1)] == ['A', 'D']


def test_judge_blocks_thin_or_unprofitable_gates():
    base = {'train': {'trades': 100, 'avg_return_pct': 0.0}, 'oos': {'trades': 50, 'avg_return_pct': 0.1}}
    good = {'train': {'trades': 80, 'avg_return_pct': 0.5}, 'oos': {'trades': 40, 'avg_return_pct': 0.4, 'profit_factor': 1.3}}
    assert rr.judge(good, base, 0.8)[0] is True
    assert rr.judge(good, base, 0.2)[0] is False
    flipped = {'train': good['train'], 'oos': {'trades': 40, 'avg_return_pct': -0.2, 'profit_factor': 0.8}}
    assert rr.judge(flipped, base, 0.8)[0] is False


def test_saved_report_contract():
    import json
    from pathlib import Path
    d = json.loads(Path('static/regime_rank_research.json').read_text(encoding='utf-8'))
    assert d['research_only'] is True and d['production_rules_mutated'] is False
    assert set(d['regime_all_strategies']['gates']) == set(rr.GATES)
    assert set(d['ranking']['rankers']) == set(rr.RANKERS)
    assert d['regime_all_strategies']['train_pick'] != 'current'


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
    print('regime rank research PASS')
