from __future__ import annotations

import argparse
import json
from pathlib import Path

import priority_challenger_v1 as engine

ROOT = Path(__file__).parent
STATIC = ROOT / 'static'
CALIBRATION = STATIC / 'priority_challenger_v2_calibration.json'
STATE = STATIC / 'priority_challenger_v2_state.json'

CHALLENGER_ID = 'priority_challenger_v2_capital075'
FREEZE_DATE = '2026-08-13'
FORWARD_START_DATE = '2026-08-14'
RISK_BUDGET = 0.0075
RISK_BUDGET_PCT = 0.75
COMPARISON_BASELINE = 'priority_challenger_v1'


def configure_engine() -> None:
    """Reuse the frozen V1 signal engine while isolating V2 files and risk size.

    This process-local configuration does not rewrite V1 calibration/state. All
    signal, quality, ranking, entry, exit, and cost rules remain identical; only
    the risk budget changes from 1.00% to 0.75%.
    """
    engine.CALIBRATION = CALIBRATION
    engine.STATE = STATE
    engine.CHALLENGER_ID = CHALLENGER_ID
    engine.FREEZE_DATE = FREEZE_DATE
    engine.FORWARD_START_DATE = FORWARD_START_DATE
    engine.RISK_BUDGET = RISK_BUDGET


def freeze_calibration() -> dict:
    configure_engine()
    existed = CALIBRATION.exists()
    data = engine.freeze_calibration()
    if existed:
        if float(data.get('risk_budget_pct') or 0.0) != RISK_BUDGET_PCT:
            raise RuntimeError('Existing V2 calibration has a different risk budget')
        if data.get('comparison_baseline') != COMPARISON_BASELINE:
            raise RuntimeError('Existing V2 calibration has different A/B metadata')
        return data

    data = dict(data)
    data['risk_budget_pct'] = RISK_BUDGET_PCT
    data['comparison_baseline'] = COMPARISON_BASELINE
    data['ab_isolation'] = {
        'same_family': True,
        'same_frozen_universe': True,
        'same_quality_filter': True,
        'same_priority_formula': True,
        'same_execution_and_exits': True,
        'only_changed_variable': 'risk_budget_pct',
        'baseline_risk_budget_pct': 1.0,
        'challenger_risk_budget_pct': RISK_BUDGET_PCT,
    }
    data.setdefault('notes', []).append(
        'V2는 V1과 동일한 후보·엄선·우선순위·진입·청산 규칙을 사용하고 계좌위험만 1.00%→0.75%로 변경한 forward A/B입니다.'
    )
    CALIBRATION.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return data


def run_forward() -> dict:
    configure_engine()
    calibration = freeze_calibration()
    state = engine.run_forward()
    state['challenger_id'] = CHALLENGER_ID
    state['comparison_baseline'] = COMPARISON_BASELINE
    state['risk_budget_pct'] = RISK_BUDGET_PCT
    state.setdefault('meta', {})['risk_budget_pct'] = RISK_BUDGET_PCT
    state['meta']['comparison_baseline'] = COMPARISON_BASELINE
    state['meta']['ab_only_changed_variable'] = 'risk_budget_pct'
    state['meta']['calibration_created_at'] = calibration.get('created_at')
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    return state


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('freeze', 'run'), nargs='?', default='run')
    args = parser.parse_args()
    if args.command == 'freeze':
        d = freeze_calibration()
        print('frozen', d['challenger_id'], 'risk', d['risk_budget_pct'], 'symbols', len(d.get('frozen_symbols') or []))
    else:
        s = run_forward()
        print(json.dumps({'summary': s.get('summary'), 'meta': s.get('meta')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
