from pathlib import Path
import json

import forward_diagnostics as fd


def _item(code, ret, *, strategy='rsi2_trend_reversion', score=84.0, target_pct=6.0, best_pct=2.0,
          mark=None, state='좋음', day='2026-09-01'):
    return {
        'symbol': 'TEST', 'strategy_id': strategy, 'status_code': code, 'outcome_return_pct': ret,
        'performance_bucket': 'official_public', 'experimental': False, 'market_date': day,
        'entry_low': 99.0, 'entry_high': 101.0, 'best_high': 100.0 * (1 + best_pct / 100.0),
        'target_pct': target_pct, 'risk_reward': 2.0, 'bars_observed': 5,
        'elite_score_at_close': score, 'market_state': state,
        'current_return_pct': mark, 'current_price_market_date': '2026-11-10',
    }


def _history(items):
    days = {}
    for item in items:
        days.setdefault(item['market_date'], []).append(item)
    return {'days': [{'date': d, 'items': v} for d, v in days.items()]}


def test_metrics_profit_factor_and_realized_reward_risk():
    rows = [_item('SUCCESS', 6.0), _item('EXPIRED_GAIN', 2.0), _item('STOP', -4.0), _item('STOP', -4.0)]
    m = fd.metrics(rows)
    assert m['closed'] == 4
    assert m['win_rate_pct'] == 50.0
    assert m['profit_factor'] == 1.0
    assert m['realized_reward_risk'] == 1.0
    assert m['target_hit_pct'] == 25.0
    assert m['stop_pct'] == 50.0
    assert m['time_exit_pct'] == 25.0


def test_open_and_research_items_are_excluded():
    open_item = _item('OPEN', None)
    research = dict(_item('STOP', -3.0), performance_bucket='research', experimental=True)
    report = fd.build_report(_history([open_item, research, _item('STOP', -3.0)]))
    assert report['total_signals'] == 2
    assert report['open_signals'] == 1
    assert report['overall']['closed'] == 1


def test_mfe_uses_buy_zone_midpoint():
    assert round(fd.mfe_pct(_item('STOP', -3.0, best_pct=2.5)), 6) == 2.5


def test_spearman_handles_monotonic_and_ties():
    assert round(fd.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 6) == 1.0
    assert round(fd.spearman([1, 2, 3, 4], [40, 30, 20, 10]), 6) == -1.0
    assert fd.spearman([1, 1, 1], [1, 2, 3]) is None


def test_no_findings_before_formal_review_sample():
    items = [_item('STOP', -4.0, mark=3.0) for _ in range(fd.MIN_REVIEW_CLOSED - 1)]
    report = fd.build_report(_history(items))
    assert report['review_ready'] is False
    assert report['findings'] == []


def test_unreachable_targets_and_recovered_stops_are_flagged():
    items = [_item('STOP', -4.0, mark=3.0) for _ in range(30)] + [_item('EXPIRED_GAIN', 2.0, mark=5.0) for _ in range(30)]
    codes = {x['code'] for x in fd.build_report(_history(items))['findings']}
    assert 'TARGET_OUT_OF_REACH' in codes
    assert 'REWARD_RISK_GAP' in codes
    assert 'STOPPED_THEN_RECOVERED' in codes
    assert 'MARKET_STATE_NOT_DISCRIMINATING' in codes
    assert 'MORE_SIGNALS_THAN_SLOTS' in codes


def test_healthy_sample_raises_no_target_or_strategy_flags():
    items = [_item('SUCCESS', 6.0, best_pct=6.5, mark=7.0) for _ in range(40)] + [_item('STOP', -3.0, best_pct=1.0, mark=-5.0) for _ in range(20)]
    codes = {x['code'] for x in fd.build_report(_history(items))['findings']}
    assert 'TARGET_OUT_OF_REACH' not in codes
    assert 'REWARD_RISK_GAP' not in codes
    assert 'STOPPED_THEN_RECOVERED' not in codes
    assert not any(c.startswith('STRATEGY_NEGATIVE') for c in codes)


def test_write_report_is_read_only_to_journal(tmp_path):
    before = fd.HISTORY.read_bytes()
    out = tmp_path / 'forward_diagnostics.json'
    report = fd.write_report(out)
    loaded = json.loads(out.read_text(encoding='utf-8'))
    assert fd.HISTORY.read_bytes() == before
    assert loaded['read_only'] is True
    assert loaded['production_rules_mutated'] is False
    assert loaded['overall']['closed'] == report['overall']['closed']


def test_ui_is_wired_and_read_only():
    js = Path('static/forward_diagnostics_ui.js').read_text(encoding='utf-8')
    html = Path('static/dashboard.html').read_text(encoding='utf-8')
    assert 'forward_diagnostics.json' in js
    assert '/api/' not in js
    assert 'forward_diagnostics_ui.js' in html
    assert 'forward_diagnostics.css' in html


if __name__ == '__main__':
    test_metrics_profit_factor_and_realized_reward_risk()
    test_open_and_research_items_are_excluded()
    test_mfe_uses_buy_zone_midpoint()
    test_spearman_handles_monotonic_and_ties()
    test_no_findings_before_formal_review_sample()
    test_unreachable_targets_and_recovered_stops_are_flagged()
    test_healthy_sample_raises_no_target_or_strategy_flags()
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as d:
        test_write_report_is_read_only_to_journal(Path(d))
    test_ui_is_wired_and_read_only()
    print('forward diagnostics PASS')
