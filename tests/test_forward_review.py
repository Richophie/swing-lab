from pathlib import Path
import json

import forward_review as fr


def _fake_state(closed=0, *, live=False, errors=None):
    return {
        'challenger_id': 'fake',
        'status': 'FORWARD_SHADOW',
        'freeze_date': '2026-08-14',
        'forward_start_date': '2026-08-14',
        'live_trading_enabled': live,
        'production_mutation_enabled': False,
        'errors': list(errors or []),
        'meta': {'auto_retune': False, 'human_intervention': False},
        'summary': {
            'return_pct': 1.25,
            'equity_krw': 3037500,
            'cash_krw': 1000000,
            'open_positions': 2,
            'closed_trades': closed,
            'win_rate_pct': 55.0,
            'decision_counts': {'FILLED': closed + 2, 'REJECT_CASH': 3, 'REJECT_GAP': 1, 'REJECT_MAX_POSITIONS': 0},
        },
    }


def test_current_forward_gate_waits_for_real_forward_sample():
    report = fr.build_report()
    assert report['status'] == 'FORWARD_PROMOTION_REVIEW'
    assert report['gate'] == 'WAIT_FORWARD_SAMPLE'
    assert report['minimum_closed_trades_required'] == 30
    assert report['minimum_closed_trades_observed'] == 0
    assert report['paper_infrastructure']['ready'] is True
    assert report['paper_infrastructure']['mode'] == 'LOCAL_SIMULATED_ONLY'
    assert report['paper_infrastructure']['real_broker_connected'] is False
    assert report['official_paper_strategy_ready'] is False
    assert report['automatic_promotion_enabled'] is False
    assert report['live_order_submission_enabled'] is False
    assert len(report['challengers']) == 4
    assert all(x['safety_pass'] for x in report['challengers'])
    assert not any(x['sample_ready'] for x in report['challengers'])
    assert {(x['challenger'], x['baseline']) for x in report['comparisons']} == {('v2', 'v1'), ('v3', 'v2'), ('v4', 'v2')}
    assert not any(x['judgement_allowed'] for x in report['comparisons'])


def test_sample_threshold_is_coarse_and_predeclared():
    spec = {'key': 'x', 'label': 'X', 'thesis': 'test', 'baseline': None}
    row29 = fr._state_row(spec, _fake_state(29))
    row30 = fr._state_row(spec, _fake_state(30))
    assert row29['sample_ready'] is False
    assert row29['sample_progress_pct'] == round(29 / 30 * 100, 1)
    assert row30['sample_ready'] is True
    assert row30['sample_progress_pct'] == 100.0


def test_live_or_error_state_blocks_safety():
    spec = {'key': 'x', 'label': 'X', 'thesis': 'test', 'baseline': None}
    assert fr._state_row(spec, _fake_state(30, live=True))['safety_pass'] is False
    assert fr._state_row(spec, _fake_state(30, errors=['boom']))['safety_pass'] is False


def test_write_report_is_read_only_to_forward_states(tmp_path):
    before = {spec['key']: spec['state'].read_bytes() for spec in fr.CHALLENGERS}
    out = tmp_path / 'forward_review.json'
    report = fr.write_report(out)
    loaded = json.loads(out.read_text(encoding='utf-8'))
    after = {spec['key']: spec['state'].read_bytes() for spec in fr.CHALLENGERS}
    assert before == after
    assert loaded['gate'] == report['gate']
    assert loaded['production_main_picker_mutated'] is False


def test_ui_is_review_only_and_wires_v4():
    js = Path('static/forward_review_ui.js').read_text(encoding='utf-8')
    html = Path('static/dashboard.html').read_text(encoding='utf-8')
    assert 'Forward 심사' in js
    assert 'PaperBroker' in js
    assert 'V4' not in js or 'forward_review.json' in js
    assert '/api/paper/submit' not in js
    assert 'forward_review_ui.js' in html
    assert 'forward_review.css' in html


if __name__ == '__main__':
    test_current_forward_gate_waits_for_real_forward_sample()
    test_sample_threshold_is_coarse_and_predeclared()
    test_live_or_error_state_blocks_safety()
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as d:
        test_write_report_is_read_only_to_forward_states(Path(d))
    test_ui_is_review_only_and_wires_v4()
    print('forward review PASS')
