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


def test_app_exposes_paper_and_signal_log_routes():
    text = (ROOT / 'app.py').read_text(encoding='utf-8')
    for route in ('/api/paper', '/api/paper/submit', '/api/paper/refresh', '/api/paper/reset', '/api/signal-events'):
        assert route in text
    assert 'X-Paper-Client' in text
    assert 'PAPER_CLIENT_DIR' in text


def main():
    test_detail_overlay_accepts_legacy_inline_open_contract()
    test_paper_ui_and_detail_explanation_are_wired()
    test_app_exposes_paper_and_signal_log_routes()
    print('ui wiring PASS')


if __name__ == '__main__':
    main()
