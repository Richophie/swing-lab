from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_loads_forward_lab_and_live_paper_marks():
    html = (ROOT / 'static' / 'dashboard.html').read_text(encoding='utf-8')
    assert '/static/lab_dashboard.css?v=' in html
    assert '/static/lab_dashboard.js?v=' in html
    assert '/static/paper_mark_to_market.js?v=' in html


def test_forward_lab_ui_explains_ab_and_has_no_manual_trade_buttons():
    js = (ROOT / 'static' / 'lab_dashboard.js').read_text(encoding='utf-8')
    for text in (
        'A · 다음 시가형',
        'B · BUY 상단 이하',
        '전략 튜닝 잠금',
        'A/B 자산곡선',
        '전략별',
        '시장상태별',
        '손익비 구간별',
        '종료 사유별',
        '보유기간별',
        'STOP/TARGET 동시 일봉',
    ):
        assert text in js
    assert '주문취소' not in js
    assert '지금 가상매도' not in js


def test_paper_mark_ui_turns_legacy_pending_manual_buy_into_visible_holding():
    js = (ROOT / 'static' / 'paper_mark_to_market.js').read_text(encoding='utf-8')
    assert "badge.textContent='보유중'" in js
    assert "label.textContent='진입가'" in js
    assert 'entry_fill_usd' in js
    assert 'unrealized_pnl_krw' in js


def main():
    test_dashboard_loads_forward_lab_and_live_paper_marks()
    test_forward_lab_ui_explains_ab_and_has_no_manual_trade_buttons()
    test_paper_mark_ui_turns_legacy_pending_manual_buy_into_visible_holding()
    print('lab ui PASS')


if __name__ == '__main__':
    main()
