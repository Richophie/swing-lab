from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_replay_v2_controls_are_wired():
    html = (ROOT / 'static' / 'dashboard.html').read_text(encoding='utf-8')
    loader = (ROOT / 'static' / 'lab_dashboard.js').read_text(encoding='utf-8')
    core = (ROOT / 'static' / 'replay_v2_core.js').read_text(encoding='utf-8')
    css = (ROOT / 'static' / 'lab_dashboard.css').read_text(encoding='utf-8')
    builder = (ROOT / 'replay_pool_v2.py').read_text(encoding='utf-8')

    assert 'btForceProfit' in html and 'btForceProfitPct' in html
    assert 'sma200_20_squeeze' in html
    assert 'replay_v2_core.js' in loader
    assert 'replay_backtest_pool_v2.json' in core
    assert 'bt-packs{display:none!important}' in css
    assert "SMA_ID = 'sma200_20_squeeze'" in builder
    assert "'exit_mode': 'sma20_close'" in builder


if __name__ == '__main__':
    test_replay_v2_controls_are_wired()
    print('replay V2 controls PASS')
