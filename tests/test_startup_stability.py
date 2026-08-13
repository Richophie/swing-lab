from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app


def test_first_load_uses_persisted_fx_without_network():
    data = json.loads((ROOT / 'static' / 'fx_cache.json').read_text(encoding='utf-8'))
    assert 500 < float(data['usdkrw']) < 3000

    def boom(*args, **kwargs):
        raise AssertionError('first-load FX lookup must not require network when cache exists')

    original_fresh = app.fresh_price_history
    original_download = app.yf.download
    try:
        app.fresh_price_history = boom
        app.yf.download = boom
        assert app.usdkrw_rate() == float(data['usdkrw'])
    finally:
        app.fresh_price_history = original_fresh
        app.yf.download = original_download


def test_market_scan_data_commit_skips_render_redeploy():
    workflow = (ROOT / '.github' / 'workflows' / 'market-scan.yml').read_text(encoding='utf-8')
    assert 'python refresh_fx_cache.py' in workflow
    assert 'static/fx_cache.json' in workflow
    assert '[skip render]' in workflow


def test_fx_refresh_is_bounded_and_keeps_previous_cache():
    text = (ROOT / 'refresh_fx_cache.py').read_text(encoding='utf-8')
    assert 'timeout=8' in text
    assert 'keeping previous cache' in text


def main():
    test_first_load_uses_persisted_fx_without_network()
    test_market_scan_data_commit_skips_render_redeploy()
    test_fx_refresh_is_bounded_and_keeps_previous_cache()
    print('startup stability PASS')


if __name__ == '__main__':
    main()
