from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_lab_loader_and_paper_marks():
    html=(ROOT/'static'/'dashboard.html').read_text(encoding='utf-8')
    assert '/static/lab_dashboard.js?v=' in html
    assert '/static/paper_mark_to_market.js?v=' in html


def test_replay_lab_wiring():
    loader=(ROOT/'static'/'lab_dashboard.js').read_text(encoding='utf-8')
    boot=(ROOT/'static'/'lab_replay_boot.js').read_text(encoding='utf-8')
    ui=(ROOT/'static'/'lab_replay_ui.js').read_text(encoding='utf-8')
    math=(ROOT/'static'/'replay_math.js').read_text(encoding='utf-8')
    for name in ('replay_math.js','lab_data.js','lab_replay_ui.js','lab_run_core.js','lab_result_ui.js','lab_replay_boot.js'):
        assert name in loader
    assert '백테스트연구소' in boot
    assert 'capacity:3' in math
    assert 'riskBudget:.01' in math
    assert 'maxShare:.40' in math
    assert 'btLabStart' in ui and 'btLabEnd' in ui and 'btLabCapital' in ui


def test_paper_mark_ui_keeps_holding_visible():
    js=(ROOT/'static'/'paper_mark_to_market.js').read_text(encoding='utf-8')
    assert "badge.textContent='보유중'" in js
    assert 'entry_fill_usd' in js
    assert 'unrealized_pnl_krw' in js


def main():
    test_lab_loader_and_paper_marks();test_replay_lab_wiring();test_paper_mark_ui_keeps_holding_visible();print('lab ui PASS')


if __name__=='__main__':main()
