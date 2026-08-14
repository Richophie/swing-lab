from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from pit_universe import audit_dataset, load_manifest, load_membership_csv

ROOT = Path(__file__).parent
MANIFEST = ROOT / 'data' / 'pit_universe' / 'source_manifest.json'
MEMBERSHIP = ROOT / 'data' / 'pit_universe' / 'membership_windows.csv'
OUT = ROOT / 'static' / 'pit_universe_status.json'


def run_audit() -> dict:
    manifest = load_manifest(MANIFEST)
    missing_files = []
    if MEMBERSHIP.exists():
        windows = load_membership_csv(MEMBERSHIP)
    else:
        windows = []
        missing_files.append(str(MEMBERSHIP.relative_to(ROOT)))

    report = audit_dataset(manifest, windows)
    report['generated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    report['manifest_path'] = str(MANIFEST.relative_to(ROOT))
    report['membership_path'] = str(MEMBERSHIP.relative_to(ROOT))
    report['missing_files'] = missing_files
    if missing_files:
        report['ready'] = False
        report['status'] = 'BLOCKED_INCOMPLETE_PIT_DATA'
        report['blocking_reasons'] = list(dict.fromkeys([
            *report.get('blocking_reasons', []),
            *[f'missing required PIT input: {path}' for path in missing_files],
        ]))

    report['forward_challengers_mutated'] = False
    report['production_main_picker_mutated'] = False
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    result = run_audit()
    print(json.dumps({
        'status': result['status'],
        'ready': result['ready'],
        'window_count': result['window_count'],
        'blocking_reasons': result['blocking_reasons'][:8],
    }, ensure_ascii=False, indent=2))
