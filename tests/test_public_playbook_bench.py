import json
from pathlib import Path

import numpy as np

import public_playbook_bench as pb
import strategy_evolution as se


def test_every_setup_names_its_public_source_and_a_swing_length_exit():
    assert len(pb.SETUPS) == 20
    for name, (label, source, family, kind, parameter, last_day, stop) in pb.SETUPS.items():
        assert label and source and family in ('reversion', 'breakout', 'momentum'), name
        assert kind in ('time', 'above_prev_high', 'above_sma5', 'rsi2_above', 'close_7d_high') and 3 <= last_day <= 10, name


def test_fresh_counts_a_lasting_condition_once():
    mask = np.zeros((30, 1), dtype=bool)
    mask[5:9, 0] = True; mask[10, 0] = True; mask[20, 0] = True
    assert list(np.flatnonzero(pb.fresh(mask, 5)[:, 0])) == [5, 20]


def test_shifted_and_rolling_never_look_ahead():
    a = np.arange(10, dtype=float)[:, None]
    assert np.isnan(pb.shifted(a)[0, 0]) and pb.shifted(a)[5, 0] == 4
    assert pb.rolling(a, 3, 'max')[5, 0] == 5


def test_summary_uses_one_number_per_signal_day():
    trades = [{'day': 1, 'return_pct': 2.0, 'entry_day': 2, 'exit_day': 4}, {'day': 1, 'return_pct': 4.0, 'entry_day': 2, 'exit_day': 4},
              {'day': 2, 'return_pct': -1.0, 'entry_day': 3, 'exit_day': 5}, {'day': 3, 'return_pct': 5.0, 'entry_day': 4, 'exit_day': 6}]
    s = pb.summary(trades)
    assert s['trades'] == 4 and s['signal_days'] == 3 and s['avg_return_pct'] == 2.5 and s['avg_days_held'] == 3.0
    assert pb.summary([]) == {'trades': 0}


def test_saved_reports_contract():
    bench = Path('static/public_playbook_bench.json')
    if bench.exists():
        d = json.loads(bench.read_text(encoding='utf-8'))
        assert d['status'] == 'RESEARCH_ONLY' and d['setups_tested'] == len(pb.SETUPS) == len(d['results'])
        assert d['t_required'] == round(se.required_t(len(pb.SETUPS)), 2)
        assert set(d['holding_up']) == {k for k, v in d['results'].items() if v['positive_in_every_period'] and v['all_years']['t_stat'] >= d['t_required']}
    ranker = Path('static/ml_ranker_research.json')
    if ranker.exists():
        d = json.loads(ranker.read_text(encoding='utf-8'))
        assert d['status'] == 'RESEARCH_ONLY' and set(d['periods']) == {'validation', 'lockbox'}
        assert d['passes'] == all(r['top_avg_return_pct'] > 0 and r['excess_t_stat'] >= 2.0 for r in d['periods'].values())
        for r in d['periods'].values():
            assert r['train'][1] < r['test'][0]


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
    print('public playbook bench PASS')
