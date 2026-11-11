import json
from pathlib import Path

import numpy as np

import washout_risk_research as wr


def test_stats_counts_big_losses_and_tail():
    s = wr.stats(np.array([5.0, 1.0, -2.0, -10.0, -30.0]))
    assert s['trades'] == 5 and s['win_rate_pct'] == 40.0 and s['big_loss_share_pct'] == 40.0 and s['worst_return_pct'] == -30.0
    assert wr.stats(np.array([])) == {'trades': 0}


def test_choose_takes_one_filter_per_feature_and_only_train_proven_ones():
    row = lambda feature, share, helps, cut: {'feature': feature, 'skip_share': share, 'train_helps_in_every_fold': helps,
                                              'train_worst_fold_big_loss_cut_pct': cut, 'train_worst_fold_avg_gain_pct': 0.1}
    picked = wr.choose([row('a', 0.1, True, 1.0), row('a', 0.2, True, 2.0), row('b', 0.1, False, 9.0), row('c', 0.1, True, 0.5)])
    assert [(f['feature'], f['skip_share']) for f in picked] == [('a', 0.2), ('c', 0.1)]


def test_judge_needs_fewer_big_losses_and_no_lower_average_in_both_unseen_periods():
    seg = lambda avg, big, n=100: {'trades': n, 'avg_return_pct': avg, 'big_loss_share_pct': big}
    base = {'validation': seg(1.0, 5.0), 'lockbox': seg(1.0, 5.0)}
    assert wr.judge(base, {'validation': seg(1.2, 3.0, 80), 'lockbox': seg(1.0, 4.0, 80)})['survives'] is True
    assert wr.judge(base, {'validation': seg(1.2, 3.0, 80), 'lockbox': seg(0.8, 4.0, 80)})['survives'] is False
    assert wr.judge(base, {'validation': seg(1.2, 5.0, 80), 'lockbox': seg(1.2, 4.0, 80)})['survives'] is False


def test_saved_report_contract():
    path = Path('static/washout_risk_research.json')
    if not path.exists():
        return
    d = json.loads(path.read_text(encoding='utf-8'))
    assert d['status'] == 'RESEARCH_ONLY' and d['production_rules_mutated'] is False and d['frozen_rules_mutated'] is False
    assert len(d['finalists']) <= wr.FINALISTS and set(d['survivors']) <= {f['feature'] for f in d['finalists']}
    assert all(f['train_helps_in_every_fold'] for f in d['finalists'])
    assert set(d['stops']) == {'none', '3_atr', '2_atr'}


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
    print('washout risk research PASS')
