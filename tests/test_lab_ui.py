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
    deep=(ROOT/'static'/'backtest_result_tabs.js').read_text(encoding='utf-8')
    core=(ROOT/'static'/'replay_v2_core.js').read_text(encoding='utf-8')
    for name in ('replay_math.js','lab_data.js','lab_replay_ui.js','lab_run_core.js','lab_result_ui.js','lab_replay_boot.js','backtest_result_tabs.js','lab_nav_hotfix.js'):
        assert name in loader
    assert '백테스트연구소' in boot
    assert 'capacity:3' in math
    assert 'riskBudget:.01' in math
    assert 'maxShare:.40' in math
    assert 'btLabStart' in ui and 'btLabEnd' in ui and 'btLabCapital' in ui
    for tab in ('요약','전략기여','연도·구간','체결내역','진단'):
        assert tab in deep
    assert '전략 제거 실험' in deep
    assert '계좌수익률' in deep and '연중 MDD' in deep
    assert '당일 종가 청산 · 일봉순서 안전판' in core
    assert "filter(x=>String(x?.[0]||'')<=b)" in core


def test_lab_sections_are_hoisted_out_of_detail_overlay():
    js=(ROOT/'static'/'lab_nav_hotfix.js').read_text(encoding='utf-8')
    assert "['lab','backtestlab']" in js
    assert "document.querySelector('main.shell')" in js
    assert 'shell.appendChild(section)' in js
    assert "page==='lab'" in js and "page==='backtestlab'" in js
    assert 'MutationObserver' in js


def test_paper_mark_ui_keeps_holding_visible():
    js=(ROOT/'static'/'paper_mark_to_market.js').read_text(encoding='utf-8')
    assert "badge.textContent='보유중'" in js
    assert 'entry_fill_usd' in js
    assert 'unrealized_pnl_krw' in js


def main():
    test_lab_loader_and_paper_marks();test_replay_lab_wiring();test_lab_sections_are_hoisted_out_of_detail_overlay();test_paper_mark_ui_keeps_holding_visible();print('lab ui PASS')


if __name__=='__main__':main()
