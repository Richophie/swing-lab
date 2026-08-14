from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_experimental_strategy_library_is_backtest_only_and_wired():
    builder = (ROOT / 'replay_pool_v2.py').read_text(encoding='utf-8')
    ui = (ROOT / 'static' / 'lab_replay_ui.js').read_text(encoding='utf-8')
    core = (ROOT / 'static' / 'replay_v2_core.js').read_text(encoding='utf-8')
    boot = (ROOT / 'static' / 'lab_replay_boot.js').read_text(encoding='utf-8')

    ids = ('sma200_20_squeeze', 'breakout_20d', 'volume_breakout', 'donchian_55', 'larry_williams_vb')
    for sid in ids:
        assert sid in builder
        assert sid in ui

    assert "entry_mode='intraday_trigger'" in builder
    assert "exit_mode='day_close'" in builder
    assert "exit_mode='donchian20_close'" in builder
    assert "K=0.50" in builder
    assert "mode==='intraday_trigger'" in core
    assert "exitMode==='day_close'" in core
    assert "exitMode==='donchian20_close'" in core
    assert 'data-p=' not in boot
    assert "document.querySelectorAll('.bt-packs').forEach(x=>x.remove())" in boot


if __name__ == '__main__':
    test_experimental_strategy_library_is_backtest_only_and_wired()
    print('replay strategy library PASS')
