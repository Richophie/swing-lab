from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import json

from config import PUBLIC_STRATEGIES, S_THRESHOLD

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


def _number(value):
    try:
        return float(value)
    except Exception:
        return None


def _signal_item(row: dict, sig: dict, plan: dict, day: str) -> dict:
    symbol = str(row.get('symbol') or '').upper().strip()
    sid = sig.get('strategy_id')
    elite_pass = bool(sig.get('elite_pass'))
    strategy_score = float(sig.get('strategy_score', 0) or 0)
    elite_score = _number(sig.get('elite_score'))
    display_score = elite_score if elite_pass and elite_score is not None else strategy_score
    return {
        'key': f'{symbol}|{sid}',
        'symbol': symbol,
        'name_ko': row.get('name_ko'),
        'security_name': row.get('security_name'),
        'strategy_id': sid,
        'strategy_name': sig.get('strategy_name') or sid,
        'score': display_score,
        'strategy_score': strategy_score,
        'elite_score': elite_score,
        'elite_pass': elite_pass,
        'tier': 'ELITE' if elite_pass else 'S',
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


def _current_sets(scan: dict) -> tuple[dict[str, dict], dict[str, dict]]:
    s_out = {}
    elite_out = {}
    at = scan.get('scanned_at') or datetime.now(timezone.utc).isoformat(timespec='seconds')
    day = _market_date(at)
    for row in scan.get('results') or []:
        plans = row.get('strategy_trade_plans') or {}
        for sig in row.get('strategy_signals') or []:
            sid = sig.get('strategy_id')
            if sid not in PUBLIC_STRATEGIES:
                continue
            if float(sig.get('strategy_score', 0) or 0) < S_THRESHOLD:
                continue
            symbol = str(row.get('symbol') or '').upper().strip()
            if not symbol:
                continue
            plan = plans.get(sid) or row.get('trade_plan') or {}
            item = _signal_item(row, sig, plan, day)
            s_out[item['key']] = item
            if bool(sig.get('elite_pass')):
                elite_out[item['key']] = item
    return s_out, elite_out


def _strategy_lookup(scan: dict) -> dict[str, dict]:
    """Return every currently scanned public strategy, including failed S/elite checks."""
    lookup = {}
    for row in scan.get('results') or []:
        symbol = str(row.get('symbol') or '').upper().strip()
        if not symbol:
            continue
        plans = row.get('strategy_trade_plans') or {}
        for sig in row.get('strategy_signals') or []:
            sid = sig.get('strategy_id')
            if sid not in PUBLIC_STRATEGIES:
                continue
            lookup[f'{symbol}|{sid}'] = {
                'row': row,
                'signal': sig,
                'plan': plans.get(sid) or {},
            }
    return lookup


def _exit_reason(previous: dict, current: dict | None, scan: dict) -> tuple[str, str, dict]:
    if current is None:
        return (
            '현재 스캔에서 해당 전략 S 신호를 확인할 수 없음',
            'signal_missing',
            {'previous_score': previous.get('score')},
        )

    sig = current.get('signal') or {}
    plan = current.get('plan') or {}
    row = current.get('row') or {}
    checks = sig.get('checks') or {}
    reasons = []
    codes = []

    strategy_score = _number(sig.get('strategy_score'))
    if strategy_score is not None and strategy_score < S_THRESHOLD:
        reasons.append(f'전략 S 점수 {strategy_score:.1f} < {S_THRESHOLD:.0f}')
        codes.append('strategy_score')
    elif checks.get('current_signal') is False:
        reasons.append('전략 S 조건 이탈')
        codes.append('strategy_score')

    if checks.get('flow') is False:
        flow_score = _number(sig.get('flow_score'))
        reasons.append(f'수급 점수 {flow_score:.0f} < 42' if flow_score is not None else '수급 기준 미달')
        codes.append('flow')

    if checks.get('risk_reward') is False:
        rr = _number(plan.get('risk_reward_gate'))
        if rr is None:
            rr = _number(sig.get('gross_risk_reward_gate'))
        if rr is None:
            rr = _number(plan.get('risk_reward'))
        reasons.append(f'손익비 {rr:.2f}:1 < 1.20:1' if rr is not None else '손익비 1.20:1 기준 미달')
        codes.append('risk_reward')

    if checks.get('market') is False:
        market_state = (scan.get('market') or {}).get('state') or '조심'
        reasons.append(f'시장 상태 {market_state} · 엄선 제외')
        codes.append('market')

    if checks.get('entry_viable') is False:
        reasons.append(plan.get('entry_status') or '진입구간 이탈')
        codes.append('entry_viable')

    if checks.get('atr_stop_margin') is False:
        atr = _number(plan.get('stop_atr_multiple'))
        minimum = _number(plan.get('min_stop_atr')) or 1.5
        reasons.append(f'ATR 손절여유 {atr:.2f} < {minimum:.1f}' if atr is not None else 'ATR 손절여유 부족')
        codes.append('atr_stop_margin')

    elite_score = _number(sig.get('elite_score'))
    if not reasons and elite_score is not None and elite_score < 72:
        reasons.append(f'엄선 점수 {elite_score:.1f} < 72')
        codes.append('elite_score')

    if not reasons:
        reasons.append('엄선 복합조건 미충족')
        codes.append('elite_rules')

    details = {
        'previous_score': previous.get('score'),
        'current_elite_score': elite_score,
        'current_strategy_score': sig.get('strategy_score'),
        'flow_score': sig.get('flow_score'),
        'risk_reward': plan.get('risk_reward'),
        'risk_reward_gate': plan.get('risk_reward_gate', sig.get('gross_risk_reward_gate')),
        'net_risk_reward': plan.get('net_risk_reward', sig.get('net_risk_reward')),
        'entry_status': plan.get('entry_status'),
        'stop_atr_multiple': plan.get('stop_atr_multiple'),
        'market_state': (scan.get('market') or {}).get('state'),
        'rsi': row.get('rsi'),
        'd120': row.get('d120'),
        'bb_pos': row.get('bb_pos'),
        'checks': checks,
    }
    return ' · '.join(reasons), '+'.join(codes), details


def _seen_today(events: list[dict], key: str, day: str) -> int:
    return sum(
        1
        for event in events
        if event.get('key') == key
        and event.get('market_date') == day
        and event.get('event') in {'ENTER', 'REENTER'}
    )


def update_log(scan: dict, log: dict) -> dict:
    if scan.get('status') != 'ready':
        return log
    at = scan.get('scanned_at') or datetime.now(timezone.utc).isoformat(timespec='seconds')
    day = _market_date(at)
    current_s, current_elite = _current_sets(scan)
    strategy_lookup = _strategy_lookup(scan)
    active = dict(log.get('active') or {})
    # Only v2 logs lacked elite_active. An explicit empty v3 map means there are
    # currently no elite signals and must not be back-filled from active S signals.
    if 'elite_active' in log:
        elite_active = dict(log.get('elite_active') or {})
    else:
        elite_active = dict(active)
    old_active_keys = set(active)
    events = list(log.get('events') or [])

    for key, item in current_s.items():
        if key not in active:
            prior = _seen_today(events, key, day)
            event_name = 'REENTER' if prior else 'ENTER'
            active[key] = {**item, 'first_seen': at, 'last_seen': at, 'capture_count': prior + 1}
            events.append(
                {
                    **item,
                    'event': event_name,
                    'at': at,
                    'first_seen': at,
                    'capture_count': prior + 1,
                }
            )
        else:
            first_seen = active[key].get('first_seen') or at
            active[key] = {**active[key], **item, 'first_seen': first_seen, 'last_seen': at}

    for key, item in current_elite.items():
        if key not in elite_active:
            elite_active[key] = {**item, 'elite_first_seen': at, 'last_seen': at}
            if key in old_active_keys:
                events.append({**item, 'event': 'ELITE_ENTER', 'at': at})
        else:
            first_seen = elite_active[key].get('elite_first_seen') or at
            elite_active[key] = {**elite_active[key], **item, 'elite_first_seen': first_seen, 'last_seen': at}

    for key in list(elite_active):
        if key in current_elite:
            continue
        previous = elite_active.pop(key)
        if key not in current_s:
            continue
        reason, reason_code, details = _exit_reason(previous, strategy_lookup.get(key), scan)
        events.append(
            {
                **previous,
                **current_s[key],
                'event': 'ELITE_EXIT',
                'at': at,
                'exit_reason': reason,
                'exit_reason_code': reason_code,
                'exit_details': details,
            }
        )

    for key in list(active):
        if key in current_s:
            continue
        previous = active.pop(key)
        elite_active.pop(key, None)
        reason, reason_code, details = _exit_reason(previous, strategy_lookup.get(key), scan)
        events.append(
            {
                **previous,
                'event': 'EXIT',
                'at': at,
                'last_seen': previous.get('last_seen'),
                'exit_reason': reason,
                'exit_reason_code': reason_code,
                'exit_details': details,
            }
        )

    log.update(
        {
            'version': 3,
            'updated_at': at,
            'market_date': day,
            'active': active,
            'elite_active': elite_active,
            'active_s_count': len(active),
            'active_elite_count': len(elite_active),
            'events': events[-MAX_EVENTS:],
        }
    )
    return log


def main():
    scan = load(SCAN_FILE, {})
    log = load(OUT_FILE, {'version': 3, 'active': {}, 'elite_active': {}, 'events': []})
    log = update_log(scan, log)
    save(OUT_FILE, log)
    print(
        'saved signal log',
        {
            'active_s': len(log.get('active') or {}),
            'active_elite': len(log.get('elite_active') or {}),
            'events': len(log.get('events') or []),
        },
    )


if __name__ == '__main__':
    main()
