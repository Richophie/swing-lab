import json
from pathlib import Path

import daytrade_evolution as de
import strategy_evolution as se
import washout_refine_research as wr


def _trade(day, col, r, score=0.0):
    return {'day': day, 'col': col, 'entry_day': day + 1, 'exit_day': day + wr.HOLD, 'return_pct': r, 'score': score}


def test_account_fills_slots_in_priority_order_and_frees_them_after_exit():
    trades = [_trade(0, 0, 10.0, 1.0), _trade(0, 1, -10.0, 2.0), _trade(3, 2, 5.0, 0.0), _trade(20, 3, 5.0, 0.0)]
    best_first = wr.account(trades, lambda t: t['score'], slots=1)
    assert best_first['trades_taken'] == 2 and best_first['total_return_pct'] == -5.5     # the higher score (-10%) wins the only slot
    worst_first = wr.account(trades, lambda t: -t['score'], slots=1)
    assert worst_first['total_return_pct'] == 15.5


def test_sector_cap_skips_a_third_name_from_one_sector_but_not_unknown_ones():
    trades = [_trade(0, c, 1.0) for c in range(4)]
    sector = {0: 'Tech', 1: 'Tech', 2: 'Tech', 3: None}
    assert wr.account(trades, lambda t: -t['col'], sector, slots=5)['trades_taken'] == 3
    assert wr.account(trades, lambda t: -t['col'], None, slots=5)['trades_taken'] == 4


def test_judge_needs_more_return_without_a_deeper_drawdown_in_both_unseen_periods():
    seg = lambda r, dd: {'total_return_pct': r, 'max_drawdown_pct': dd}
    base = {'validation': seg(50, -10), 'lockbox': seg(20, -15)}
    assert wr.judge(base, {'validation': seg(55, -11), 'lockbox': seg(21, -15)})['survives'] is True
    assert wr.judge(base, {'validation': seg(55, -11), 'lockbox': seg(19, -15)})['survives'] is False
    assert wr.judge(base, {'validation': seg(55, -13), 'lockbox': seg(21, -15)})['survives'] is False


def test_daytrade_search_uses_its_own_ledger_and_short_holds_only():
    saved = (se.HOLDS, se.STOPS_ATR, se.TARGETS_ATR, se.SPLIT_VERSION, se.OUT)
    try:
        de.configure()
        assert se.HOLDS == (1, 2) and se.OUT == de.OUT and se.OUT != saved[4] and se.SPLIT_VERSION != saved[3]
    finally:
        se.HOLDS, se.STOPS_ATR, se.TARGETS_ATR, se.SPLIT_VERSION, se.OUT = saved


def test_saved_reports_contract():
    refine = Path('static/washout_refine_research.json')
    if refine.exists():
        d = json.loads(refine.read_text(encoding='utf-8'))
        assert d['status'] == 'RESEARCH_ONLY' and d['frozen_rules_mutated'] is False
        assert set(d['survivors']) <= {'ordering', 'sector_cap', 'confirmation', 'score'}
        assert d['score']['fitted_on'] == 'train folds only'
    day = Path('static/daytrade_evolution.json')
    if day.exists():
        d = json.loads(day.read_text(encoding='utf-8'))
        assert d['research_only'] is True and d['split_version'] == de.SPLIT_VERSION and list(d['search_space']['holds']) == [1, 2]


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
    print('washout refine research PASS')
