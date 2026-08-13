from __future__ import annotations

import json
from pathlib import Path

from baseline_rules import BASELINE_VERSION
from config import APP_VERSION, CORE_VERSION

ROOT = Path(__file__).parent
STATIC = ROOT / 'static'
SCAN_FILE = STATIC / 'latest_scan.json'
HISTORY_FILE = STATIC / 'trade_history.json'


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def _save(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def annotate(history: dict, scan: dict) -> int:
    publish = history.get('last_publish_check') or {}
    day = str(publish.get('market_date') or '')[:10]
    if not day:
        return 0
    market = scan.get('market') or {}
    signal_index = {}
    for row in scan.get('results') or []:
        symbol = str(row.get('symbol') or '').upper().strip()
        for sig in row.get('strategy_signals') or []:
            sid = str(sig.get('strategy_id') or '')
            if symbol and sid:
                signal_index[f'{symbol}|{sid}'] = sig
    changed = 0
    for block in history.get('days') or []:
        if str(block.get('date') or '')[:10] != day:
            continue
        for item in block.get('items') or []:
            key = f"{str(item.get('symbol') or '').upper()}|{item.get('strategy_id') or ''}"
            sig = signal_index.get(key) or {}
            before = dict(item)
            item.setdefault('baseline_version', BASELINE_VERSION)
            item.setdefault('app_version', APP_VERSION)
            item.setdefault('core_version', CORE_VERSION)
            item.setdefault('market_state', market.get('state') or 'UNTRACKED')
            item.setdefault('market_score', market.get('score'))
            item.setdefault('flow_score', sig.get('flow_score'))
            item.setdefault('elite_score_at_close', sig.get('elite_score'))
            if item != before:
                changed += 1
    history['baseline_annotation_policy'] = (
        'official close recommendations freeze baseline/app/core/market/flow context; '
        'later engine changes must not rewrite prior snapshots'
    )
    return changed


def main():
    history = _load(HISTORY_FILE, {'days': []})
    scan = _load(SCAN_FILE, {'results': []})
    changed = annotate(history, scan)
    _save(HISTORY_FILE, history)
    print('baseline journal annotations', changed)


if __name__ == '__main__':
    main()
