from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_lab_loader_and_paper_marks():
    html=(ROOT/'static'/'dashboard.html').read_text(encoding='utf-8')
    assert '/static/lab_dashboard.js?v=' in html
    assert '/static/paper_mark_to_market.js?v=' in html


def test_replay_lab_wiring():
    loader=(ROOT/'static'/'lab_dashboard.js').read_text(encoding='utf-8')
    archive=(ROOT/'static'/'lab_research_archive.js').read_text(encoding='utf-8')
    boot=(ROOT/'static'/'lab_replay_boot.js').read_text(encoding='utf-8')
    ui=(ROOT/'static'/'lab_replay_ui.js').read_text(encoding='utf-8')
    math=(ROOT/'static'/'replay_math.js').read_text(encoding='utf-8')
    deep=(ROOT/'static'/'backtest_result_tabs.js').read_text(encoding='utf-8')
    css=(ROOT/'static'/'backtest_result_tabs.css').read_text(encoding='utf-8')
    core=(ROOT/'static'/'replay_v2_core.js').read_text(encoding='utf-8')
    for name in ('replay_math.js','lab_data.js','lab_replay_ui.js','lab_run_core.js','lab_result_ui.js','lab_replay_boot.js','backtest_result_tabs.js','lab_nav_hotfix.js','global_flow_map.js','lab_front_simplify.js','lab_research_archive.js'):
        assert name in loader
    for name in ('strategy_optimizer_ui.js','selection_filter_ui.js','walkforward_ui.js','regime_walkforward_ui.js','volatility_regime_ui.js','priority_audit_ui.js','priority_challenger_v1.js','priority_challenger_ab.js','candidate_capital_v2_ui.js'):
        assert name not in loader
        assert name in archive
    assert '백테스트 연구소' in boot
    assert 'US STOCKS' in boot and 'DAILY MTM' in boot
    assert '최대 동시보유' in boot and '<option selected>10</option>' in boot
    assert '고급 민감도 실험 · 고정익절/강제 보유상한' in boot
    assert 'capacity:3' in math
    assert 'riskBudget:.01' in math
    assert 'maxShare:.40' in math
    assert 'markUpdates' in math
    assert 'underwaterDays' in math and 'worstMonth' in math
    assert '어떤 조건으로 돌려볼까요?' in ui
    assert 'btLabStart' in ui and 'btLabEnd' in ui and 'btLabCapital' in ui
    assert 'bt-strategy-grid' in ui and 'DAILY MTM' in ui
    for tab in ('한눈에','전략','기간','체결','진단'):
        assert tab in deep
    assert '전략 하나씩 빼보기' in deep
    assert '월별 수익률' in deep
    assert '계좌수익률' in deep and '연중 MDD' in deep
    assert 'data-label=' in deep
    assert '.bt-result-layout' in css
    assert 'grid-template-columns:155px minmax(0,1fr)' in css
    assert '@media(max-width:900px)' in css
    assert 'span[data-label]::before' in css
    assert '.bt-month-grid' in css
    assert '당일 종가 청산 · 일봉순서 안전판' in core
    assert 'const marks=' in core and 'stress_factor:stressFactor' in core
    assert "filter(x=>String(x?.[0]||'')<=b)" in core


def test_beginner_front_and_korean_market_palette():
    front=(ROOT/'static'/'lab_front_simplify.js').read_text(encoding='utf-8')
    front_css=(ROOT/'static'/'lab_front_simplify.css').read_text(encoding='utf-8')
    flow=(ROOT/'static'/'global_flow_map.js').read_text(encoding='utf-8')
    flow_css=(ROOT/'static'/'global_flow_map.css').read_text(encoding='utf-8')
    archive=(ROOT/'static'/'lab_research_archive.js').read_text(encoding='utf-8')
    assert '처음이면 기본 3개 그대로' in front
    assert '최대 낙폭' in front and '손익비(PF)' in front
    assert '실험 전략 더 보기' in front
    assert '.bt-internal-only' in front_css
    assert '빨강 = 상대적 유입 강함 · 파랑 = 상대적 이탈' in flow
    assert 'flow-map-collapsible' in flow
    assert '.flow-score.up{color:#e43d49}' in flow_css
    assert '.flow-score.down{color:#4b78d7}' in flow_css
    assert '.flow-dot.hot,.flow-dot.warm{background:#ff5b65}' in flow_css
    assert '.flow-dot.cold,.flow-dot.cool{background:#76a1ff}' in flow_css
    assert '일반 백테스트에는 필요 없는 연구 패널' in archive
    assert 'loadNext' in archive


def test_walkforward_ui_is_loaded():
    ui=(ROOT/'static'/'walkforward_ui.js').read_text(encoding='utf-8')
    css=(ROOT/'static'/'walkforward_ui.css').read_text(encoding='utf-8')
    assert 'portfolio_walkforward_results.json' in ui
    assert '여러 시장 구간에서 다시 살아남는지' in ui
    assert 'NO RETUNE' in ui and 'RESEARCH ONLY' in ui
    assert '4년 학습 → 다음 1년 시험' in ui
    assert '.wf-folds' in css and '.wf-kpis' in css


def test_regime_walkforward_ui_is_loaded():
    ui=(ROOT/'static'/'regime_walkforward_ui.js').read_text(encoding='utf-8')
    css=(ROOT/'static'/'regime_walkforward_ui.css').read_text(encoding='utf-8')
    assert 'portfolio_regime_results.json' in ui
    assert '전략이 좋은 건지, 장이 좋았던 건지' in ui
    assert 'TRAIN ONLY' in ui and 'RESEARCH ONLY' in ui
    assert '게이트 없음' in ui
    assert '.rg-current' in css and '.rg-folds' in css


def test_volatility_diagnostic_ui_is_loaded():
    ui=(ROOT/'static'/'volatility_regime_ui.js').read_text(encoding='utf-8')
    css=(ROOT/'static'/'volatility_regime_ui.css').read_text(encoding='utf-8')
    assert 'portfolio_volatility_diagnostic.json' in ui
    assert '초록장도 다 같은 초록장이 아니네' in ui
    assert 'REPORT ONLY' in ui and '아직 필터 아님' in ui
    assert '상태슬리브' in ui
    assert '.vr-current' in css and '.vr-states' in css


def test_priority_audit_ui_is_loaded():
    ui=(ROOT/'static'/'priority_audit_ui.js').read_text(encoding='utf-8')
    css=(ROOT/'static'/'priority_audit_ui.css').read_text(encoding='utf-8')
    assert 'portfolio_priority_audit.json' in ui
    assert '좋은 후보가 먼저 슬롯을 먹고 있었나?' in ui
    assert 'REPORT ONLY' in ui and 'RESEARCH ONLY' in ui
    assert '전략별 품질순' in ui and '현재+품질 50:50' in ui
    assert '.pa-rules' in css and '.pa-audit' in css


def test_frozen_priority_challenger_ui_is_loaded():
    ui=(ROOT/'static'/'priority_challenger_v1.js').read_text(encoding='utf-8')
    css=(ROOT/'static'/'priority_challenger_v1.css').read_text(encoding='utf-8')
    assert 'priority_challenger_v1_state.json' in ui
    assert 'priority_challenger_v1_calibration.json' in ui
    assert '과거는 여기서 끝. 이제 앞으로만 본다' in ui
    assert 'NO RETUNE · NO LIVE ORDER' in ui
    assert '최대 10개 · 위험기준 순차 사이징' in ui
    assert '현금부족 탈락' in ui
    assert '.pcv1-kpis' in css and '.pcv1-grid' in css


def test_candidate_capital_v2_ui_is_loaded():
    ui=(ROOT/'static'/'candidate_capital_v2_ui.js').read_text(encoding='utf-8')
    css=(ROOT/'static'/'candidate_capital_v2_ui.css').read_text(encoding='utf-8')
    assert 'portfolio_candidate_capital_v2.json' in ui
    assert '좋은 후보에게 돈을 더 주면 진짜 나아질까?' in ui
    assert 'DEVELOPMENT ONLY' in ui
    assert '0.5%·0.75%·1.0%' in ui
    assert '그날 1순위' in ui and '상위 75%+' in ui
    assert '.ccv2-policies' in css and '.ccv2-dna' in css


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
    test_lab_loader_and_paper_marks();test_replay_lab_wiring();test_beginner_front_and_korean_market_palette();test_walkforward_ui_is_loaded();test_regime_walkforward_ui_is_loaded();test_volatility_diagnostic_ui_is_loaded();test_priority_audit_ui_is_loaded();test_frozen_priority_challenger_ui_is_loaded();test_candidate_capital_v2_ui_is_loaded();test_lab_sections_are_hoisted_out_of_detail_overlay();test_paper_mark_ui_keeps_holding_visible();print('lab ui PASS')


if __name__=='__main__':main()
