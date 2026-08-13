from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import json

from config import PUBLIC_STRATEGIES

ROOT = Path(__file__).parent
SCAN_FILE = ROOT / 'static' / 'latest_scan.json'
OUT_FILE = ROOT / 'static' / 'signal_events.json'
NY = ZoneInfo('America/New_York')
MAX_EVENTS = 1500


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def save(path: Path, data: dict):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _market_date(at: str | None) -> str:
    try:
        value = datetime.fromisoformat(str(at).replace('Z', '+00:00'))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(NY).date().isoformat()
    except Exception:
        return datetime.now(timezone.utc).astimezone(NY).date().isoformat()


def _current_price(row: dict):
    values = row.get('sparkline') or []
    try:
        return float(values[-1]) if values else None
    except Exception:
        return None


def _qualified(scan: dict) -> dict[str, dict]:
    out = {}
    at = scan.get('scanned_at') or datetime.now(timezone.utc).isoformat(timespec='seconds')
    day = _market_date(at)
    for row in scan.get('results') or []:
        plans = row.get('strategy_trade_plans') or {}
        for sig in row.get('strategy_signals') or []:
            sid = sig.get('strategy_id')
            if sid not in PUBLIC_STRATEGIES or not bool(sig.get('elite_pass')):
                continue
            symbol = str(row.get('symbol') or '').upper().strip()
            if not symbol:
                continue
            plan = plans.get(sid) or row.get('trade_plan') or {}
            key = f'{symbol}|{sid}'
            out[key] = {
                'key': key,
                'symbol': symbol,
                'name_ko': row.get('name_ko'),
                'security_name': row.get('security_name'),
                'strategy_id': sid,
                'strategy_name': sig.get('strategy_name') or sid,
                'score': float(sig.get('elite_score', sig.get('strategy_score', row.get('score', 0))) or 0),
                'strategy_score': float(sig.get('strategy_score', 0) or 0),
                'market_date': day,
                'current_price': _current_price(row),
                'entry_low': plan.get('entry_low'),
                'entry_high': plan.get('entry_high'),
                'target': plan.get('target'),
                'stop': plan.get('stop'),
                'rsi': row.get('rsi'),
                'd120': row.get('d120'),
                'bb_pos': row.get('bb_pos'),
            }
    return out


def update_log(scan: dict, log: dict) -> dict:
    if scan.get('status') != 'ready':
        return log
    at = scan.get('scanned_at') or datetime.now(timezone.utc).isoformat(timespec='seconds')
    current = _qualified(scan)
    active = dict(log.get('active') or {})
    events = list(log.get('events') or [])

    for key, item in current.items():
        if key not in active:
            active[key] = {**item, 'first_seen': at, 'last_seen': at}
            events.append({**item, 'event': 'ENTER', 'at': at, 'first_seen': at})
        else:
            first_seen = active[key].get('first_seen') or at
            active[key] = {**active[key], **item, 'first_seen': first_seen, 'last_seen': at}

    for key in list(active):
        if key in current:
            continue
        previous = active.pop(key)
        events.append({
            **previous,
            'event': 'EXIT',
            'at': at,
            'last_seen': previous.get('last_seen'),
            'exit_reason': '현재 엄선 조건에서 이탈',
        })

    log.update({
        'version': 1,
        'updated_at': at,
        'market_date': _market_date(at),
        'active': active,
        'events': events[-MAX_EVENTS:],
    })
    return log


def main():
    scan = load(SCAN_FILE, {})
    log = load(OUT_FILE, {'version': 1, 'active': {}, 'events': []})
    log = update_log(scan, log)
    save(OUT_FILE, log)
    print('saved signal log', {'active': len(log.get('active') or {}), 'events': len(log.get('events') or [])})


if __name__ == '__main__':
    main()
