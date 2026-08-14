from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_strategy_optimizer_is_wired():
    script = (ROOT / 'strategy_optimizer_v2.py').read_text(encoding='utf-8')
    runner = (ROOT / 'strategy_optimizer_runner.py').read_text(encoding='utf-8')
    ui = (ROOT / 'static' / 'strategy_optimizer_ui.js').read_text(encoding='utf-8')
    loader = (ROOT / 'static' / 'lab_dashboard.js').read_text(encoding='utf-8')
    workflow = (ROOT / '.github' / 'workflows' / 'strategy-optimizer.yml').read_text(encoding='utf-8')

    assert "CAPACITIES = (1, 3, 5, 7, 10)" in script
    assert "MAX_STRATEGIES_PER_COMBO = 5" in script
    assert 'AUTO_SEARCH_EXCLUDE = {"larry_williams_vb"}' in script
    assert "rank on train only" in script
    assert "OOS is pass/fail validation" in script
    assert "promotion_status" in script and "research_only" in script
    assert '"ablation"' in script and '"full"' in script

    assert "execute_candidate_mtm" in runner
    assert "mtm_portfolio" in runner
    assert "opt.EXIT_PCTS = (None,)" in runner
    assert "opt.HOLD_CAPS = (None,)" in runner
    assert "daily_close_mark_to_market" in runner
    assert '"underwater_days"' in runner

    assert "strategy_optimizer_results.json" in ui
    assert "자동 전략 최적화 연구소" in ui
    assert "MTM MDD" in ui
    assert "고정 +N% 익절과 강제 보유기간은 메인 탐색에서 내렸어요" in ui
    assert "strategy_optimizer_ui.js" in loader

    assert "python strategy_optimizer_runner.py" in workflow
    assert "daily_close_mark_to_market" in workflow
    assert "forced_profit_pct') == [None]" in workflow
    assert "hold_cap_days') == [None]" in workflow


if __name__ == '__main__':
    test_strategy_optimizer_is_wired()
    print('strategy optimizer wiring PASS')
