from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from paper_broker import new_state

ROOT = Path(__file__).parent
STATIC = ROOT / 'static'
OUT = STATIC / 'forward_review.json'
MIN_CLOSED_TRADES = 30

CHALLENGERS = (
    {
        'key': 'v1',
        'label': 'V1 · BASELINE',
        'state': STATIC / 'priority_challenger_v1_state.json',
        'thesis': '1.00% risk baseline',
        'baseline': None,
    },
    {
        'key': 'v2',
        'label': 'V2 · CAPITAL 0.75',
        'state': STATIC / 'priority_challenger_v2_state.json',
        'thesis': 'same signals, 0.75% risk budget',
        'baseline': 'v1',
    },
    {
        'key': 'v3',
        'label': 'V3 · CORR DAMP',
        'state': STATIC / 'priority_challenger_v3_state.json',
        'thesis': 'high-correlation fresh entries use half risk',
        'baseline': 'v2',
    },
    {
        'key': 'v4',
        'label': 'V4 · SAME-DAY RANK',
        'state': STATIC / 'priority_challenger_v4_state.json',
        'thesis': 'same-day rank1 keeps full risk, lower ranks use half risk',
        'baseline': 'v2',
    },
)

PAPER_REQUIRED_FILES = (
    ROOT / 'paper_broker.py',
    ROOT / 'paper_broker_service.py',
    ROOT / 'paper_entry.py',
    ROOT / 'paper_manual.py',
    ROOT / 'paper_marks.py',
    ROOT / 'paper_restore.py',
    ROOT / 'tests' / 'test_paper_broker.py',
    ROOT / 'tests' / 'test_paper_manual.py',
    ROOT / 'tests' / 'test_paper_marks.py',
    ROOT / 'tests' / 'test_paper_restore.py',
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _n(value, default=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _i(value, default=0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _state_row(spec: dict, state: dict) -> dict:
    summary = dict(state.get('summary') or {})
    meta = dict(state.get('meta') or {})
    decisions = dict(summary.get('decision_counts') or {})
    errors = list(state.get('errors') or [])
    safety = {
        'forward_shadow_only': state.get('status') == 'FORWARD_SHADOW',
        'live_trading_disabled': state.get('live_trading_enabled') is False,
        'production_mutation_disabled': state.get('production_mutation_enabled') is False,
        'auto_retune_disabled': meta.get('auto_retune') is False,
        'human_intervention_disabled': meta.get('human_intervention') is False,
        'no_state_errors': len(errors) == 0,
    }
    closed = _i(summary.get('closed_trades'))
    progress = min(100.0, closed / MIN_CLOSED_TRADES * 100.0)
    return {
        'key': spec['key'],
        'label': spec['label'],
        'challenger_id': state.get('challenger_id'),
        'thesis': spec['thesis'],
        'baseline': spec['baseline'],
        'status': state.get('status'),
        'freeze_date': state.get('freeze_date'),
        'forward_start_date': state.get('forward_start_date'),
        'updated_at': state.get('updated_at'),
        'return_pct': round(_n(summary.get('return_pct')), 4),
        'equity_krw': round(_n(summary.get('equity_krw')), 2),
        'cash_krw': round(_n(summary.get('cash_krw')), 2),
        'open_positions': _i(summary.get('open_positions')),
        'closed_trades': closed,
        'win_rate_pct': summary.get('win_rate_pct'),
        'filled': _i(decisions.get('FILLED')),
        'reject_cash': _i(decisions.get('REJECT_CASH')),
        'reject_gap': _i(decisions.get('REJECT_GAP')),
        'reject_max_positions': _i(decisions.get('REJECT_MAX_POSITIONS')),
        'sample_progress_pct': round(progress, 1),
        'sample_ready': closed >= MIN_CLOSED_TRADES,
        'safety': safety,
        'safety_pass': all(safety.values()),
        'error_count': len(errors),
    }


def _paper_infrastructure() -> dict:
    files = {str(p.relative_to(ROOT)): p.exists() for p in PAPER_REQUIRED_FILES}
    app_text = (ROOT / 'app.py').read_text(encoding='utf-8') if (ROOT / 'app.py').exists() else ''
    routes = {
        'status': '/api/paper/status' in app_text,
        'submit': '/api/paper/submit' in app_text,
        'refresh': '/api/paper/refresh' in app_text,
        'reset': '/api/paper/reset' in app_text,
    }
    safe_default = new_state().get('live_trading_enabled') is False
    ready = all(files.values()) and all(routes.values()) and safe_default
    return {
        'ready': ready,
        'mode': 'LOCAL_SIMULATED_ONLY',
        'real_broker_connected': False,
        'external_order_submission_enabled': False,
        'live_trading_default_disabled': safe_default,
        'required_files': files,
        'api_routes': routes,
        'ci_test_contract': [
            'tests/test_paper_broker.py',
            'tests/test_paper_manual.py',
            'tests/test_paper_marks.py',
            'tests/test_paper_restore.py',
        ],
    }


def _comparisons(rows: list[dict]) -> list[dict]:
    by_key = {row['key']: row for row in rows}
    out = []
    for row in rows:
        base_key = row.get('baseline')
        if not base_key or base_key not in by_key:
            continue
        base = by_key[base_key]
        out.append({
            'challenger': row['key'],
            'baseline': base_key,
            'label': f"{row['label']} vs {base['label']}",
            'return_delta_pct': round(row['return_pct'] - base['return_pct'], 4),
            'equity_delta_krw': round(row['equity_krw'] - base['equity_krw'], 2),
            'closed_trade_delta': row['closed_trades'] - base['closed_trades'],
            'cash_reject_delta': row['reject_cash'] - base['reject_cash'],
            'judgement_allowed': row['sample_ready'] and base['sample_ready'],
        })
    return out


def build_report() -> dict:
    rows = [_state_row(spec, _load(spec['state'])) for spec in CHALLENGERS]
    paper = _paper_infrastructure()
    safety_pass = all(row['safety_pass'] for row in rows)
    sample_ready = all(row['sample_ready'] for row in rows)
    min_closed = min((row['closed_trades'] for row in rows), default=0)
    min_progress = min((row['sample_progress_pct'] for row in rows), default=0.0)

    if not safety_pass:
        gate = 'BLOCKED_SAFETY'
        title = '안전조건부터 확인해야 해요'
        next_action = 'Forward state 오류/안전 플래그를 수정하고 전략 규칙은 동결 유지'
    elif not paper['ready']:
        gate = 'BLOCKED_PAPER_INFRA'
        title = 'PaperBroker 기반시설 점검이 필요해요'
        next_action = '가상체결/저장/복구/API 테스트를 먼저 통과'
    elif not sample_ready:
        gate = 'WAIT_FORWARD_SAMPLE'
        title = '기반시설은 준비 완료 · 미래 표본을 모으는 중'
        next_action = f'V1~V4 각각 종료 {MIN_CLOSED_TRADES}건까지 규칙 변경 없이 관찰'
    else:
        gate = 'HUMAN_REVIEW_READY'
        title = 'Forward 1차 심사 가능 · 자동 승격은 금지'
        next_action = 'V1~V4의 수익·낙폭·현금거절·체결 차이를 사람 검토 후 Paper 후보 1개만 지정'

    return {
        'version': 1,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'status': 'FORWARD_PROMOTION_REVIEW',
        'gate': gate,
        'headline': title,
        'recommended_next_action': next_action,
        'minimum_closed_trades_required': MIN_CLOSED_TRADES,
        'minimum_closed_trades_observed': min_closed,
        'sample_progress_pct': min_progress,
        'all_forward_safety_pass': safety_pass,
        'all_forward_sample_ready': sample_ready,
        'paper_infrastructure': paper,
        'official_paper_strategy_ready': gate == 'HUMAN_REVIEW_READY',
        'automatic_promotion_enabled': False,
        'production_main_picker_mutated': False,
        'live_order_submission_enabled': False,
        'challengers': rows,
        'comparisons': _comparisons(rows),
        'promotion_rules': [
            'V1~V4 must stay frozen; correctness/safety fixes only.',
            f'Every challenger needs at least {MIN_CLOSED_TRADES} closed Forward trades before comparative judgement.',
            'State errors or any live/production mutation flag block review immediately.',
            'PaperBroker infrastructure readiness does not mean the strategy is evidence-ready.',
            'Passing the gate never auto-selects a winner and never sends a real broker order.',
        ],
    }


def write_report(path: Path = OUT) -> dict:
    report = build_report()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main() -> None:
    report = write_report()
    print(json.dumps({
        'gate': report['gate'],
        'sample_progress_pct': report['sample_progress_pct'],
        'paper_infrastructure_ready': report['paper_infrastructure']['ready'],
        'official_paper_strategy_ready': report['official_paper_strategy_ready'],
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
