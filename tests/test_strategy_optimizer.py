from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_strategy_optimizer_is_wired():
    script = (ROOT / 'strategy_optimizer_v2.py').read_text(encoding='utf-8')
    ui = (ROOT / 'static' / 'strategy_optimizer_ui.js').read_text(encoding='utf-8')
    loader = (ROOT / 'static' / 'lab_dashboard.js').read_text(encoding='utf-8')
    workflow = (ROOT / '.github' / 'workflows' / 'strategy-optimizer.yml').read_text(encoding='utf-8')

    assert "EXIT_PCTS = (None, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0)" in script
    assert "HOLD_CAPS = (None, 3, 5, 10)" in script
    assert "CAPACITIES = (1, 3, 5)" in script
    assert "rank on train only" in script
    assert "OOS is pass/fail validation" in script
    assert "promotion_status" in script and "research_only" in script
    assert "strategy_optimizer_results.json" in ui
    assert "자동 전략 최적화 연구소" in ui
    assert "OOS를 보고 순위를 다시 맞추지 않아요" in ui
    assert "strategy_optimizer_ui.js" in loader
    assert "python strategy_optimizer_v2.py" in workflow


if __name__ == '__main__':
    test_strategy_optimizer_is_wired()
    print('strategy optimizer wiring PASS')
