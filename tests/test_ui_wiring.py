from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_detail_overlay_accepts_legacy_inline_open_contract():
    text = (ROOT / 'static' / 'detail_overlay.js').read_text(encoding='utf-8')
    assert "detail.style.display==='block'" in text
    assert "attributeFilter:['class','style']" in text
    assert "overlay.classList.add('open')" in text
    assert "detail.style.display='none'" in text


def main():
    test_detail_overlay_accepts_legacy_inline_open_contract()
    print('ui wiring PASS')


if __name__ == '__main__':
    main()
