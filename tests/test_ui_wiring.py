from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_detail_overlay_accepts_legacy_inline_open_contract():
    text = (ROOT / 'static' / 'detail_overlay.js').read_text(encoding='utf-8')
    assert "detail.style.display==='block'" in text
    assert "attributeFilter:['class','style']" in text
    assert "overlay.classList.add('open')" in text
    assert "detail.style.display='none'" in text


def test_paper_ui_and_detail_explanation_are_wired():
    text = (ROOT / 'static' / 'detail_overlay.js').read_text(encoding='utf-8')
    assert "data-page=\"paper\"" in text
    assert "가상계좌" in text
    assert "'/api/paper/submit'" in text
    assert "'/api/paper/refresh'" in text
    assert "X-Paper-Client" in text
    assert "detail-insight" in text
    assert "점수는 성공확률이 아니라" in text
    assert ".pick .reason>span{display:none!important}" in text
    assert "오늘 장중 포착 · 이탈" in text
    assert "마감 확정 추천 기록" in text


def test_product_controls_split_manual_paper_and_shadow_lab():
    text = (ROOT / 'static' / 'ui_controls.js').read_text(encoding='utf-8')
    for label in ('실시간후보', '사라마라', '엔진', '가상계좌', '자동거래연구소'):
        assert label in text
    assert '/api/engine-status' in text
    assert '/api/shadow' in text
    assert '/api/paper/manual-preview' in text
    assert '/api/paper/manual-submit' in text
    assert '/api/paper/close' in text
    assert 'manualQty' in text
    assert '주문취소' in text
    assert '지금 가상매도' in text
    assert '사람 개입 없음' in text


def test_dashboard_loads_backtest_v2_paper_indie_and_event_ui_helpers():
    html = (ROOT / 'static' / 'dashboard.html').read_text(encoding='utf-8')
    assert '/static/dashboard.js?v=' in html
    assert '/static/chart_guides.js?v=' in html
    assert '/static/detail_overlay.js?v=' in html
    assert '/static/backtest_compat.js?v=' in html
    assert '/static/backtest_results.css?v=' in html
    assert '/static/paper_persistence.js?v=' in html
    assert '/static/indie_finance_theme.css?v=' in html
    assert '/static/indie_finance_ui.js?v=' in html
    assert '/static/pop_indie_polish.css?v=' in html
    assert '/static/pop_indie_polish.js?v=' in html
    assert '/static/semantic_palette.css?v=' in html
    assert '/static/signal_event_polish.js?v=' in html
    assert '/static/event_risk.css?v=' in html
    assert '/static/event_risk_ui.js?v=' in html
    assert '/static/ui_controls.js' in html

    event_ui = (ROOT / 'static' / 'event_risk_ui.js').read_text(encoding='utf-8')
    assert 'EVENT RISK' in event_ui
    assert '보유기간 중 실적' in event_ui
    assert '추천 점수나 BUY/TARGET/STOP에 영향을 주지 않는 참고 경고' in event_ui

    event_css = (ROOT / 'static' / 'event_risk.css').read_text(encoding='utf-8')
    assert '.event-risk-badge' in event_css
    assert '.detail-event-risk' in event_css

    backtest = (ROOT / 'static' / 'backtest_compat.js').read_text(encoding='utf-8')
    assert 'full_10y' in backtest
    assert 'recent_2y' in backtest
    assert 'return_pct??x.total_return_pct' in backtest
    assert 'max_drawdown??x.max_drawdown_pct' in backtest
    assert '검증 데이터가 충분하지 않습니다' in backtest

    backtest_css = (ROOT / 'static' / 'backtest_results.css').read_text(encoding='utf-8')
    assert '#btArea .metrics' in backtest_css
    assert 'grid-template-columns:repeat(3' in backtest_css
    assert '@media(max-width:720px)' in backtest_css

    theme = (ROOT / 'static' / 'indie_finance_theme.css').read_text(encoding='utf-8')
    assert '--acid:#dfff57' in theme
    assert '.market-panel' in theme
    assert '.paper-summary' in theme
    assert '.detail-overlay' in theme

    microcopy = (ROOT / 'static' / 'indie_finance_ui.js').read_text(encoding='utf-8')
    assert '오늘, 들어갈 만한 자리' in microcopy
    assert '⚡ 실시간 후보' in microcopy
    assert '🧪 가상계좌' in microcopy
    assert '🧭 이 자리를 어떻게 읽었는지' in microcopy
    assert '💸 내 돈으로 계산' in microcopy

    pop_css = (ROOT / 'static' / 'pop_indie_polish.css').read_text(encoding='utf-8')
    pop_js = (ROOT / 'static' / 'pop_indie_polish.js').read_text(encoding='utf-8')
    assert 'Black Han Sans' in pop_css
    assert '.live-static-copy' in pop_css
    assert 'background:#f2f3ef!important' in pop_css
    assert 'background:#151714!important' in pop_css
    assert 'clip-path:none!important' in pop_css
    assert '👌 지금 볼 만한 자리' in pop_js
    assert 'entry-sticker-card' in pop_js
    assert 'live-static-copy' in pop_js
    assert 'live-marquee-track' not in pop_js

    palette = (ROOT / 'static' / 'semantic_palette.css').read_text(encoding='utf-8')
    assert '--up:#ff7d88' in palette
    assert '--down:#76a1ff' in palette
    assert 'stroke:#ff7d88!important' in palette
    assert 'stroke:#76a1ff!important' in palette
    assert '.signal-event.exit .event-badge' in palette
    assert 'color:#fff!important' in palette
    assert '.signal-event:not(.exit) .event-badge' in palette

    signal_ui = (ROOT / 'static' / 'signal_event_polish.js').read_text(encoding='utf-8')
    assert '/api/signal-events?limit=50' in signal_ui
    assert '이탈 이유' in signal_ui
    assert 'exit_reason' in signal_ui
    assert '👀 S 포착' in signal_ui
    assert '엄선 승격' in signal_ui
    assert '엄선 해제' in signal_ui
    assert '재포착' in signal_ui

    guides = (ROOT / 'static' / 'chart_guides.js').read_text(encoding='utf-8')
    assert "PLOT_LEFT='48'" in guides
    assert "PLOT_RIGHT='900'" in guides
    assert 'line[stroke="#d94b4b"][stroke-dasharray]' in guides
    assert 'line[stroke="#3777d0"][stroke-dasharray]' in guides
    assert 'line[stroke="#17191c"][stroke-dasharray]' in guides
    assert 'now.remove()' in guides

    persistence = (ROOT / 'static' / 'paper_persistence.js').read_text(encoding='utf-8')
    assert 'swingLabPaperStateBackupV1' in persistence
    assert '/api/paper/restore' in persistence
    assert "path==='/api/paper'" in persistence


def test_app_exposes_manual_paper_shadow_engine_and_signal_routes():
    text = (ROOT / 'app.py').read_text(encoding='utf-8')
    for route in ('/api/paper', '/api/paper/submit', '/api/paper/refresh', '/api/paper/reset', '/api/signal-events'):
        assert route in text
    assert 'X-Paper-Client' in text
    assert 'PAPER_CLIENT_DIR' in text

    entry = (ROOT / 'paper_entry.py').read_text(encoding='utf-8')
    for route in (
        '/api/paper/restore',
        '/api/paper/manual-preview',
        '/api/paper/manual-submit',
        '/api/paper/close',
        '/api/shadow',
        '/api/engine-status',
    ):
        assert route in entry
    assert 'restore_browser_backup' in entry
    assert 'app_module.load_json = load_json' in entry
    assert 'paper_service._load_json = load_json' in entry


def main():
    test_detail_overlay_accepts_legacy_inline_open_contract()
    test_paper_ui_and_detail_explanation_are_wired()
    test_product_controls_split_manual_paper_and_shadow_lab()
    test_dashboard_loads_backtest_v2_paper_indie_and_event_ui_helpers()
    test_app_exposes_manual_paper_shadow_engine_and_signal_routes()
    print('ui wiring PASS')


if __name__ == '__main__':
    main()
