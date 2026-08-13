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


def test_dashboard_loads_backtest_v2_paper_and_indie_ui_helpers():
    html = (ROOT / 'static' / 'dashboard.html').read_text(encoding='utf-8')
    assert '/static/dashboard.js?v=' in html
    assert '/static/detail_overlay.js?v=' in html
    assert '/static/backtest_compat.js?v=' in html
    assert '/static/backtest_results.css?v=' in html
    assert '/static/paper_persistence.js?v=' in html
    assert '/static/indie_finance_theme.css?v=' in html
    assert '/static/indie_finance_ui.js?v=' in html
    assert '/static/pop_indie_polish.css?v=' in html
    assert '/static/pop_indie_polish.js?v=' in html

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
    assert '.live-marquee-track' in pop_css
    assert 'clip-path:polygon' in pop_css
    assert '#5cff77' in pop_css
    assert '👌 지금 볼 만한 자리' in pop_js
    assert 'entry-sticker-card' in pop_js
    assert 'live-marquee-track' in pop_js

    persistence = (ROOT / 'static' / 'paper_persistence.js').read_text(encoding='utf-8')
    assert 'swingLabPaperStateBackupV1' in persistence
    assert '/api/paper/restore' in persistence
    assert "path==='/api/paper'" in persistence


def test_app_exposes_paper_and_signal_log_routes():
    text = (ROOT / 'app.py').read_text(encoding='utf-8')
    for route in ('/api/paper', '/api/paper/submit', '/api/paper/refresh', '/api/paper/reset', '/api/signal-events'):
        assert route in text
    assert 'X-Paper-Client' in text
    assert 'PAPER_CLIENT_DIR' in text

    entry = (ROOT / 'paper_entry.py').read_text(encoding='utf-8')
    assert '/api/paper/restore' in entry
    assert 'restore_browser_backup' in entry


def main():
    test_detail_overlay_accepts_legacy_inline_open_contract()
    test_paper_ui_and_detail_explanation_are_wired()
    test_dashboard_loads_backtest_v2_paper_and_indie_ui_helpers()
    test_app_exposes_paper_and_signal_log_routes()
    print('ui wiring PASS')


if __name__ == '__main__':
    main()
