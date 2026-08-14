from pathlib import Path

import portfolio_regime_research as r


def test_regime_classifier():
    assert r.classify_snapshot(110, 100, 210, 200) == 'risk_on'
    assert r.classify_snapshot(90, 100, 190, 200) == 'risk_off'
    assert r.classify_snapshot(110, 100, 190, 200) == 'mixed'
    assert r.classify_snapshot(float('nan'), 100, 190, 200) == 'unknown'


def test_gate_semantics():
    assert r.gate_accepts('all', 'risk_on')
    assert r.gate_accepts('all', 'risk_off')
    assert r.gate_accepts('avoid_risk_off', 'risk_on')
    assert r.gate_accepts('avoid_risk_off', 'mixed')
    assert not r.gate_accepts('avoid_risk_off', 'risk_off')
    assert r.gate_accepts('risk_on_only', 'risk_on')
    assert not r.gate_accepts('risk_on_only', 'mixed')
    assert not r.gate_accepts('risk_on_only', 'risk_off')


def test_gate_score_prefers_simpler_on_exact_tie():
    x={'trades':40,'cagr':.10,'mdd':-.10}
    assert r.gate_score(x, 40, 0.0) > r.gate_score(x, 40, 0.3)


def test_source_guards_train_only_selection():
    src=Path('portfolio_regime_research.py').read_text(encoding='utf-8')
    family=src[src.index('def family_fold'):src.index('def summarize')]
    choose=family[family.index('chosen = max'):family.index('chosen_intensity')]
    assert 'train_objects' in choose
    assert 'test_selected' not in choose
    assert 'test_baseline' not in choose
    assert 'test_delta_return_pct' not in choose
    assert 'signal-day close regime is known before' in src
    assert 'SPY and QQQ close vs trailing SMA200' in src


def main():
    test_regime_classifier()
    test_gate_semantics()
    test_gate_score_prefers_simpler_on_exact_tie()
    test_source_guards_train_only_selection()
    print('portfolio regime research PASS')


if __name__=='__main__':
    main()
