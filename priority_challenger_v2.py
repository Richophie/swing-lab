from __future__ import annotations

from datetime import datetime, timezone
import argparse
import json
from pathlib import Path

import priority_challenger_v1 as engine

ROOT = Path(__file__).parent
STATIC = ROOT / 'static'
V1_CALIBRATION = STATIC / 'priority_challenger_v1_calibration.json'
CALIBRATION = STATIC / 'priority_challenger_v2_calibration.json'
STATE = STATIC / 'priority_challenger_v2_state.json'

CHALLENGER_ID = 'priority_challenger_v2_capital075'
FREEZE_DATE = '2026-08-13'
FORWARD_START_DATE = '2026-08-14'
RISK_BUDGET = 0.0075
RISK_BUDGET_PCT = 0.75
COMPARISON_BASELINE = 'priority_challenger_v1'


def configure_engine() -> None:
    """Reuse V1 execution logic while isolating V2 files and risk size."""
    engine.CALIBRATION = CALIBRATION
    engine.STATE = STATE
    engine.CHALLENGER_ID = CHALLENGER_ID
    engine.FREEZE_DATE = FREEZE_DATE
    engine.FORWARD_START_DATE = FORWARD_START_DATE
    engine.RISK_BUDGET = RISK_BUDGET


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def freeze_calibration() -> dict:
    """Clone V1's immutable calibration exactly, then change only risk metadata."""
    configure_engine()
    if CALIBRATION.exists():
        data = _load(CALIBRATION)
        if data.get('challenger_id') != CHALLENGER_ID or data.get('freeze_date') != FREEZE_DATE:
            raise RuntimeError('Existing V2 calibration has different freeze metadata')
        if float(data.get('risk_budget_pct') or 0.0) != RISK_BUDGET_PCT:
            raise RuntimeError('Existing V2 calibration has a different risk budget')
        if data.get('comparison_baseline') != COMPARISON_BASELINE:
            raise RuntimeError('Existing V2 calibration has different A/B metadata')
        return data

    if not V1_CALIBRATION.exists():
        raise RuntimeError('Frozen V1 calibration is required before creating V2 A/B')
    v1 = _load(V1_CALIBRATION)
    if v1.get('challenger_id') != COMPARISON_BASELINE or v1.get('status') != 'FROZEN_FORWARD_ONLY':
        raise RuntimeError('V1 calibration is not the expected frozen baseline')
    if v1.get('freeze_date') != FREEZE_DATE or v1.get('forward_start_date') != FORWARD_START_DATE:
        raise RuntimeError('V1 and V2 must share the exact same forward boundary')

    # JSON round-trip gives a deep copy so V1's in-memory object is never mutated.
    data = json.loads(json.dumps(v1))
    data['challenger_id'] = CHALLENGER_ID
    data['created_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    data['risk_budget_pct'] = RISK_BUDGET_PCT
    data['comparison_baseline'] = COMPARISON_BASELINE
    data['source_v1_calibration_created_at'] = v1.get('created_at')
    data['ab_isolation'] = {
        'same_family': True,
        'same_frozen_universe': True,
        'same_reference_distributions': True,
        'same_quality_filter': True,
        'same_priority_formula': True,
        'same_execution_and_exits': True,
        'only_changed_variable': 'risk_budget_pct',
        'baseline_risk_budget_pct': 1.0,
        'challenger_risk_budget_pct': RISK_BUDGET_PCT,
    }
    data.setdefault('notes', []).append(
        'V2는 V1 calibration의 종목·품질분포·priority분포를 그대로 복제하고 계좌위험만 1.00%→0.75%로 변경한 forward A/B입니다.'
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
