from __future__ import annotations

from copy import deepcopy
import json
import math
import re
from pathlib import Path

from paper_broker import PaperBrokerStore, new_state, snapshot

ALLOWED_STATUSES = {'PENDING', 'FILLED', 'CLOSED', 'CANCELLED', 'REJECTED'}
SYMBOL_RE = re.compile(r'^[A-Z0-9.\-]{1,15}$')
MAX_BACKUP_BYTES = 2_000_000
MAX_ORDERS = 500
MAX_EVENTS = 1000
MAX_CASH_KRW = 1_000_000_000


def _money(value, *, default=0.0):
    try:
        out = float(value)
    except Exception:
        return float(default)
    if not math.isfinite(out) or out < 0 or out > MAX_CASH_KRW:
        raise ValueError('가상계좌 금액 값이 올바르지 않습니다')
    return round(out, 2)


def sanitize_browser_backup(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError('복원할 가상계좌 데이터가 없습니다')
    try:
        payload_size = len(json.dumps(raw, ensure_ascii=False).encode('utf-8'))
    except Exception as exc:
        raise ValueError('가상계좌 백업 형식이 올바르지 않습니다') from exc
    if payload_size > MAX_BACKUP_BYTES:
        raise ValueError('가상계좌 백업이 너무 큽니다')

    orders = raw.get('orders') or []
    events = raw.get('events') or []
    if not isinstance(orders, list) or len(orders) > MAX_ORDERS:
        raise ValueError('가상 주문 백업 형식이 올바르지 않습니다')
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise ValueError('가상 이벤트 백업 형식이 올바르지 않습니다')

    starting = _money(raw.get('starting_cash_krw', 3_000_000), default=3_000_000)
    cash = _money(raw.get('cash_krw', starting), default=starting)
    state = new_state(starting)
    state['cash_krw'] = cash
    state['created_at'] = str(raw.get('created_at') or state['created_at'])[:64]

    safe_orders = []
    for source in orders:
        if not isinstance(source, dict):
            raise ValueError('가상 주문 백업 항목이 올바르지 않습니다')
        order = deepcopy(source)
        symbol = str(order.get('symbol') or '').upper().strip()
        status = str(order.get('status') or '').upper().strip()
        if not SYMBOL_RE.match(symbol) or status not in ALLOWED_STATUSES:
            raise ValueError('가상 주문의 종목 또는 상태가 올바르지 않습니다')
        try:
            qty = int(order.get('qty') or 0)
        except Exception as exc:
            raise ValueError('가상 주문 수량이 올바르지 않습니다') from exc
        if qty < 0 or qty > 1_000_000:
            raise ValueError('가상 주문 수량 범위를 벗어났습니다')
        order['symbol'] = symbol
        order['status'] = status
        order['qty'] = qty
        order['live_order_sent'] = False
        safe_orders.append(order)

    safe_events = [deepcopy(e) for e in events if isinstance(e, dict)][-MAX_EVENTS:]
    state['orders'] = safe_orders
    state['events'] = safe_events
    state['live_trading_enabled'] = False
    return state


def restore_browser_backup(raw: dict, *, state_path: str | Path) -> dict:
    store = PaperBrokerStore(state_path)
    current = store.load()
    # Never overwrite a server ledger that already contains activity. Browser backup is
    # only a recovery path for ephemeral-host redeploys where the server file vanished.
    if current.get('orders') or current.get('events'):
        out = snapshot(current)
        out['browser_restore'] = 'server_state_kept'
        return out
    restored = store.save(sanitize_browser_backup(raw))
    out = snapshot(restored)
    out['browser_restore'] = 'restored'
    return out
