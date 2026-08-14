from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from pit_universe_audit import run_audit

ROOT = Path(__file__).parent
OUT = ROOT / 'static' / 'replay_backtest_pool_pit_v1.json'
LEGACY_POOL = ROOT / 'static' / 'replay_backtest_pool_v2.json'


def build_status() -> dict:
    audit = run_audit()
    if audit.get('ready'):
        status = 'PIT_SOURCE_READY_REPLAY_BUILDER_NEXT'
        reasons = [
            'Verified PIT source gate passed. Candidate replay generation is intentionally a separate next step so source ingestion can be audited before strategy execution.',
        ]
    else:
        status = 'BLOCKED_PIT_SOURCE'
        reasons = list(audit.get('blocking_reasons') or [])

    payload = {
        'version': 1,
        'ready': False,
        'status': status,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'pit_universe_status': audit.get('status'),
        'pit_universe_ready': bool(audit.get('ready')),
        'target_start': audit.get('target_start'),
        'target_end': audit.get('target_end'),
        'blocking_reasons': reasons,
        'output_isolated_from_current_replay': True,
        'current_replay_path': str(LEGACY_POOL.relative_to(ROOT)),
        'pit_replay_path': str(OUT.relative_to(ROOT)),
        'production_main_picker_mutated': False,
        'forward_challengers_mutated': False,
        'notes': [
            'This artifact never falls back to today\'s research_universe/prefilter_symbols.',
            'The existing replay_backtest_pool_v2.json remains the current-universe development baseline for comparison.',
            'ready stays false until both verified PIT data and the audited PIT candidate builder are present.',
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


if __name__ == '__main__':
    p = build_status()
    print(json.dumps({
        'status': p['status'],
        'ready': p['ready'],
        'pit_universe_ready': p['pit_universe_ready'],
    }, ensure_ascii=False, indent=2))
