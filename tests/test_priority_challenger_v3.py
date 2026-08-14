from pathlib import Path

import pandas as pd

import priority_challenger_v1 as v1
import priority_challenger_v2 as v2
import priority_challenger_v3 as v3


def _frame(values):
    idx = pd.date_range('2026-03-01', periods=len(values), freq='B')
    s = pd.Series(values, index=idx, dtype=float)
    return pd.DataFrame({'Close': s, 'Adj Close': s})


def test_v3_is_frozen_forward_sibling_of_v2():
    assert v3.CHALLENGER_ID == 'priority_challenger_v3_corr075_half'
    assert v3.COMPARISON_BASELINE == v2.CHALLENGER_ID
    assert v3.FORWARD_START_DATE == v2.FORWARD_START_DATE == '2026-08-14'
    assert v3.HYPOTHESIS_FREEZE_DATE == '2026-08-14'
    assert v3.BASE_RISK_BUDGET == v2.RISK_BUDGET == 0.0075
    assert v3.DAMPED_RISK_BUDGET == 0.00375
    assert v3.CORR_THRESHOLD == 0.75
    assert v3.LOOKBACK_SESSIONS == 60
    assert v3.MIN_OVERLAP_SESSIONS == 40


def test_paths_are_isolated():
    assert v3.CALIBRATION.name == 'priority_challenger_v3_calibration.json'
    assert v3.STATE.name == 'priority_challenger_v3_state.json'
    assert v3.CALIBRATION not in {v1.CALIBRATION, v2.CALIBRATION}
    assert v3.STATE not in {v1.STATE, v2.STATE}


def test_correlation_context_halves_only_high_corr_fresh_entry():
    # Build non-constant price paths with nearly identical returns.
    base = [100.0]
    peer = [80.0]
    low = [50.0]
    for i in range(1, 90):
        r = 0.012 if i % 2 else -0.008
        base.append(base[-1] * (1 + r))
        peer.append(peer[-1] * (1 + r * 0.98))
        r2 = 0.003 if i % 3 else -0.004
        low.append(low[-1] * (1 + r2))
    frames = {'AAA': _frame(base), 'BBB': _frame(peer), 'CCC': _frame(low)}
    asof = frames['AAA'].index[-1].strftime('%Y-%m-%d')

    empty = v3.correlation_risk_context({'symbol': 'AAA', 'signal_date': asof}, {'positions': []}, frames)
    assert empty['risk_budget_pct'] == 0.75
    assert empty['corr_reduced'] is False

    high = v3.correlation_risk_context({'symbol': 'AAA', 'signal_date': asof}, {'positions': [{'symbol': 'BBB'}]}, frames)
    assert high['max_peer_corr'] is not None and high['max_peer_corr'] >= 0.75
    assert high['risk_budget_pct'] == 0.375
    assert high['corr_reduced'] is True
    assert high['corr_peer'] == 'BBB'

    low_ctx = v3.correlation_risk_context({'symbol': 'AAA', 'signal_date': asof}, {'positions': [{'symbol': 'CCC'}]}, frames)
    assert low_ctx['risk_budget_pct'] == 0.75
    assert low_ctx['corr_reduced'] is False


def test_insufficient_history_defaults_to_full_risk_not_rejection():
    idx = pd.date_range('2026-07-01', periods=20, freq='B')
    frames = {
        'AAA': pd.DataFrame({'Close': range(100, 120)}, index=idx),
        'BBB': pd.DataFrame({'Close': range(200, 220)}, index=idx),
    }
    ctx = v3.correlation_risk_context(
        {'symbol': 'AAA', 'signal_date': idx[-1].strftime('%Y-%m-%d')},
        {'positions': [{'symbol': 'BBB'}]},
        frames,
    )
    assert ctx['risk_budget_pct'] == 0.75
    assert ctx['corr_reduced'] is False
    assert ctx['corr_coverage'] == 'INSUFFICIENT_HISTORY'


def test_v3_does_not_mutate_production_or_tune_thresholds():
    src = Path('priority_challenger_v3.py').read_text(encoding='utf-8')
    assert 'submit_order' not in src
    assert 'CORR_THRESHOLD = 0.75' in src
    assert 'LOOKBACK_SESSIONS = 60' in src
    assert 'DAMPED_RISK_BUDGET = 0.00375' in src
    assert "'production_main_picker_mutated'] = False" in src
    assert 'grid' not in src.lower()


def main():
    test_v3_is_frozen_forward_sibling_of_v2()
    test_paths_are_isolated()
    test_correlation_context_halves_only_high_corr_fresh_entry()
    test_insufficient_history_defaults_to_full_risk_not_rejection()
    test_v3_does_not_mutate_production_or_tune_thresholds()
    print('priority challenger v3 PASS')


if __name__ == '__main__':
    main()
