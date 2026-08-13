from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from config import PUBLIC_STRATEGIES
from market_data import fresh_price_history
from paper_broker import PaperBrokerStore, process_bar, snapshot, submit_order
from paper_broker_service import current_fx_rate
from risk_observability import snapshot_event_risk

ROOT = Path(__file__).parent
STATIC = ROOT / 'static'
HISTORY_FILE = STATIC / 'trade_history.json'
SCAN_FILE = STATIC / 'latest_scan.json'
STATE_FILE = STATIC / 'shadow_portfolio.json'
LAB_START_DATE = '2026-08-13'
LAB_VERSION = 1


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def _number(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _scan_plan_index(scan: dict) -> dict[str, dict]:
    out = {}
    for row in scan.get('results') or []:
        symbol = str(row.get('symbol') or '').upper().strip()
        plans = row.get('strategy_trade_plans') or {}
        for sid, plan in plans.items():
            if symbol and sid in PUBLIC_STRATEGIES and isinstance(plan, dict):
                out[f'{symbol}|{sid}'] = plan
    return out


def _plan_from_item(item: dict, current_plan: dict | None = None) -> dict:
    source = current_plan or {}
    atr = item.get('atr')
    if atr is None:
        atr = source.get('atr')
    if atr is None or _number(atr, 0.0) <= 0:
        raise ValueError('공식 추천 ATR 스냅샷이 없어 canonical gap guard를 계산할 수 없습니다')
    return {
        'entry_low': item.get('entry_low'),
        'entry_high': item.get('entry_high'),
        'target': item.get('target'),
        'stop': item.get('stop'),
        'atr': float(atr),
        'days_min': item.get('target_days_low'),
        'days_max': item.get('target_days_high'),
        'target_days': {
            'days_low': item.get('target_days_low'),
            'days_high': item.get('target_days_high'),
        },
    }


def _signal_key(item: dict) -> str:
    day = str(item.get('market_date') or item.get('date') or '')[:10]
    symbol = str(item.get('symbol') or '').upper().strip()
    strategy = str(item.get('strategy_id') or '').strip()
    return f'{day}|{symbol}|{strategy}'


def _eligible_items(history: dict) -> list[dict]:
    rows = []
    for day in history.get('days') or []:
        for item in day.get('items') or []:
            market_date = str(item.get('market_date') or day.get('date') or '')[:10]
            if not market_date or market_date < LAB_START_DATE:
                continue
            if item.get('strategy_id') not in PUBLIC_STRATEGIES:
                continue
            if bool(item.get('experimental')):
                continue
            if item.get('performance_bucket') not in {None, 'official_public'}:
                continue
            if not item.get('entry_low') or not item.get('entry_high') or not item.get('target') or not item.get('stop'):
                continue
            row = dict(item)
            row['market_date'] = market_date
            rows.append(row)
    rows.sort(
        key=lambda x: (
            x.get('market_date') or '',
            -_number(x.get('risk_reward'), 0.0),
            -_number(x.get('score'), 0.0),
            str(x.get('symbol') or ''),
        )
    )
    return rows


def _ensure_meta(state: dict) -> None:
    state['live_trading_enabled'] = False
    state.setdefault('shadow_decisions', [])
    state.setdefault('lab_meta', {})
    state['lab_meta'].update(
        {
            'version': LAB_VERSION,
            'lab_start_date': LAB_START_DATE,
            'mode': 'AUTO_CONFIRMED_CLOSE',
            'allocator': 'risk_reward_priority',
            'human_intervention': False,
            'live_trading_enabled': False,
        }
    )


def _seen_keys(state: dict) -> set[str]:
    out = set()
    for order in state.get('orders') or []:
        key = order.get('shadow_signal_key')
        if key:
            out.add(str(key))
    for row in state.get('shadow_decisions') or []:
        key = row.get('signal_key')
        if key:
            out.add(str(key))
    return out


def ingest_confirmed_signals(
    state: dict,
    history: dict,
    *,
    fx_rate: float,
    live_scan: dict | None = None,
) -> dict:
    _ensure_meta(state)
    seen = _seen_keys(state)
    scan_plans = _scan_plan_index(live_scan or {})
    submitted = 0
    skipped = 0

    for item in _eligible_items(history):
        key = _signal_key(item)
        if key in seen:
            continue
        decision = {
            'signal_key': key,
            'market_date': item.get('market_date'),
            'symbol': item.get('symbol'),
            'strategy_id': item.get('strategy_id'),
            'strategy_name': item.get('strategy_name'),
            'score': item.get('score'),
            'risk_reward': item.get('risk_reward'),
            'at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        }
        try:
            symbol = str(item.get('symbol') or '').upper().strip()
            sid = str(item.get('strategy_id') or '')
            plan = _plan_from_item(item, scan_plans.get(f'{symbol}|{sid}'))
            order = submit_order(
                state,
                symbol=symbol,
                strategy_id=sid,
                strategy_name=item.get('strategy_name') or sid,
                plan=plan,
                fx_rate=float(fx_rate),
                submitted_market_date=item.get('market_date'),
                signal_date=item.get('market_date'),
            )
            order['order_origin'] = 'AUTO_CONFIRMED_CLOSE'
            order['signal_origin'] = 'official_close_confirmed'
            order['shadow_signal_key'] = key
            order['official_score'] = item.get('score')
            order['official_risk_reward'] = item.get('risk_reward')
            order['official_selection_reason'] = item.get('selection_reason')
            order['event_risk_snapshot'] = snapshot_event_risk(
                item.get('event_risk_snapshot') or item.get('event_risk')
            )
            order['risk_observability_only'] = True
            decision.update(
                {
                    'decision': 'SUBMITTED',
                    'order_id': order.get('id'),
                    'atr': order.get('atr'),
                    'gap_guard': order.get('gap_guard'),
                }
            )
            submitted += 1
        except Exception as exc:
            decision.update({'decision': 'SKIPPED', 'reason': str(exc)})
            skipped += 1
        state['shadow_decisions'].append(decision)
        seen.add(key)

    if len(state['shadow_decisions']) > 2000:
        state['shadow_decisions'] = state['shadow_decisions'][-2000:]
    return {'submitted': submitted, 'skipped': skipped}


def refresh_active(state: dict) -> int:
    active_symbols = sorted(
        {
            o.get('symbol')
            for o in state.get('orders', [])
            if o.get('status') in {'PENDING', 'FILLED'} and o.get('symbol')
        }
    )
    if not active_symbols:
        return 0
    fx = current_fx_rate()
    touched = 0
    for symbol in active_symbols:
        try:
            data = fresh_price_history(symbol, '1mo')
        except Exception:
            continue
        if data is None or data.empty:
            continue
        for idx, bar in data.iterrows():
            changed = process_bar(
                state,
                symbol=symbol,
                date=idx.strftime('%Y-%m-%d'),
                open_px=float(bar['Open']),
                high_px=float(bar['High']),
                low_px=float(bar['Low']),
                close_px=float(bar['Close']),
                fx_rate=fx,
            )
            touched += len(changed)
    return touched


def _bucket_stats(rows: list[dict], key_name: str) -> dict:
    out = {}
    for order in rows:
        key = str(order.get(key_name) or 'UNKNOWN')
        bucket = out.setdefault(key, {'closed': 0, 'wins': 0, 'pnl_krw': 0.0, 'returns': []})
        bucket['closed'] += 1
        pnl = _number(order.get('pnl_krw'), 0.0)
        ret = _number(order.get('return_pct'), 0.0)
        bucket['pnl_krw'] += pnl
        bucket['returns'].append(ret)
        if pnl > 0:
            bucket['wins'] += 1
    for bucket in out.values():
        closed = bucket['closed']
        bucket['win_rate_pct'] = round(bucket['wins'] / closed * 100.0, 1) if closed else 0.0
        bucket['avg_return_pct'] = round(sum(bucket['returns']) / closed, 3) if closed else None
        bucket['pnl_krw'] = round(bucket['pnl_krw'], 2)
        del bucket['returns']
    return out


def lab_snapshot(state: dict) -> dict:
    _ensure_meta(state)
    base = snapshot(state)
    closed = [o for o in base.get('orders', []) if o.get('status') == 'CLOSED']
    event_rows = []
    for order in closed:
        row = dict(order)
        risk = order.get('event_risk_snapshot') or {}
        row['event_risk_code'] = risk.get('risk_code') or 'UNKNOWN'
        event_rows.append(row)
    base['lab_summary'] = {
        'total_orders': len(base.get('orders') or []),
        'closed_orders': len(closed),
        'submitted_decisions': sum(1 for x in base.get('shadow_decisions', []) if x.get('decision') == 'SUBMITTED'),
        'skipped_decisions': sum(1 for x in base.get('shadow_decisions', []) if x.get('decision') == 'SKIPPED'),
        'by_strategy': _bucket_stats(closed, 'strategy_id'),
        'by_event_risk': _bucket_stats(event_rows, 'event_risk_code'),
    }
    return base


def status(*, state_path: str | Path = STATE_FILE) -> dict:
    store = PaperBrokerStore(state_path)
    state = store.load()
    _ensure_meta(state)
    return lab_snapshot(state)


def run(*, state_path: str | Path = STATE_FILE) -> dict:
    store = PaperBrokerStore(state_path)
    state = store.load()
    _ensure_meta(state)
    refresh_active(state)
    history = _load_json(HISTORY_FILE, {'days': []})
    scan = _load_json(SCAN_FILE, {'results': []})
    fx = current_fx_rate()
    result = ingest_confirmed_signals(state, history, fx_rate=fx, live_scan=scan)
    state['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    state['lab_meta']['last_run_at'] = state['updated_at']
    state['lab_meta']['last_ingest'] = result
    saved = store.save(state)
    return lab_snapshot(saved)


def main():
    result = run()
    print(
        json.dumps(
            {
                'summary': result.get('summary'),
                'lab_summary': result.get('lab_summary'),
                'lab_meta': result.get('lab_meta'),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == '__main__':
    main()
