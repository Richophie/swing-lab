from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backtest_engine import market_sell_fill
from paper_broker import PaperBrokerStore, _cancel_order, _close_order, snapshot, submit_order
from paper_broker_service import (
    _latest_market_date,
    _tag_legacy_origins,
    current_fx_rate,
    latest_plan,
)
from paper_marks import _price_mark

NY = ZoneInfo('America/New_York')


def _market_date() -> str:
    return datetime.now(NY).date().isoformat()


def _resize_order(order: dict, state: dict, requested_qty: int) -> None:
    max_qty = int(order.get('qty') or 0)
    qty = int(requested_qty)
    if qty < 1:
        raise ValueError('수량은 1주 이상이어야 합니다')
    if qty > max_qty:
        raise ValueError(f'현재 계좌 리스크/현금 기준 최대 {max_qty}주까지 가능합니다')
    if qty == max_qty:
        order['max_allowed_qty'] = max_qty
        return

    entry = float(order['planned_entry_usd'])
    stop = float(order['stop'])
    fx = float(order['fx_at_submit'])
    commission = max(0.0, float(order.get('commission_pct_per_side') or 0.0)) / 100.0
    order['qty'] = qty
    order['max_allowed_qty'] = max_qty
    order['planned_notional_krw'] = round(qty * entry * fx, 2)
    order['planned_risk_krw'] = round(qty * max(entry - stop, 0.0) * fx, 2)
    order['reserved_cash_krw'] = round(qty * entry * fx * (1.0 + commission), 2)

    for event in reversed(state.get('events', [])):
        if event.get('order_id') == order.get('id') and event.get('event') == 'SUBMITTED':
            event['detail'] = f"다음 거래일 시가 대기 · {qty}주 · BUY {order['buy_low']:.2f}~{order['buy_high']:.2f}"
            break


def _build_order(
    state: dict,
    *,
    symbol: str,
    strategy_id: str | None,
    requested_qty: int | None,
) -> dict:
    info = latest_plan(symbol, strategy_id)
    fx = current_fx_rate()
    market_date = _latest_market_date(info['symbol'])
    order = submit_order(
        state,
        symbol=info['symbol'],
        strategy_id=info['strategy_id'],
        strategy_name=info['strategy_name'],
        plan=info['plan'],
        fx_rate=fx,
        submitted_market_date=market_date,
        signal_date=info.get('scan_date') or market_date,
    )
    max_qty = int(order.get('qty') or 0)
    order['max_allowed_qty'] = max_qty
    if requested_qty is not None:
        _resize_order(order, state, int(requested_qty))
    order['order_origin'] = 'MANUAL_PAPER'
    order['signal_origin'] = 'user_selected_latest_scan'
    order['event_risk_snapshot'] = dict(info.get('event_risk_snapshot') or {})
    order['risk_observability_only'] = True
    return order


def preview_manual(
    symbol: str,
    strategy_id: str | None = None,
    *,
    state_path: str | Path,
) -> dict:
    store = PaperBrokerStore(state_path)
    state = store.load()
    _tag_legacy_origins(state)
    trial = deepcopy(state)
    order = _build_order(trial, symbol=symbol, strategy_id=strategy_id, requested_qty=None)
    return {
        'symbol': order['symbol'],
        'strategy_id': order['strategy_id'],
        'strategy_name': order['strategy_name'],
        'max_qty': int(order['qty']),
        'planned_entry_usd': order.get('planned_entry_usd'),
        'planned_notional_krw': order.get('planned_notional_krw'),
        'planned_risk_krw': order.get('planned_risk_krw'),
        'risk_budget_krw': order.get('risk_budget_krw'),
        'available_cash_krw': snapshot(state)['summary'].get('available_cash_krw'),
        'live_trading_enabled': False,
    }


def submit_manual(
    symbol: str,
    strategy_id: str | None = None,
    *,
    requested_qty: int | None = None,
    state_path: str | Path,
) -> dict:
    store = PaperBrokerStore(state_path)
    state = store.load()
    _tag_legacy_origins(state)
    order = _build_order(
        state,
        symbol=symbol,
        strategy_id=strategy_id,
        requested_qty=requested_qty,
    )
    saved = store.save(state)
    out = snapshot(saved)
    out['submitted_order_id'] = order.get('id')
    out['submitted_qty'] = int(order.get('qty') or 0)
    out['max_allowed_qty'] = int(order.get('max_allowed_qty') or order.get('qty') or 0)
    return out


def close_or_cancel_manual(order_id: str, *, state_path: str | Path) -> dict:
    order_id = str(order_id or '').strip()
    if not order_id:
        raise ValueError('order_id가 필요합니다')

    store = PaperBrokerStore(state_path)
    state = store.load()
    _tag_legacy_origins(state)
    order = next((o for o in state.get('orders', []) if o.get('id') == order_id), None)
    if order is None:
        raise ValueError('가상주문을 찾지 못했습니다')
    if order.get('order_origin') not in {'MANUAL_PAPER', 'LIVE_CANDIDATE'}:
        raise ValueError('자동거래연구소 주문은 수동으로 종료할 수 없습니다')

    status = order.get('status')
    if status == 'PENDING':
        _cancel_order(state, order, _market_date(), '사용자 주문취소')
    elif status == 'FILLED':
        price, _, _ = _price_mark(str(order.get('symbol') or ''))
        if price is None:
            raise ValueError('현재 시장가격을 확인하지 못해 가상매도를 처리할 수 없습니다')
        fx = current_fx_rate()
        fill = market_sell_fill(
            float(price),
            float(order.get('slippage_bps') or 0.0),
            float(order.get('half_spread_bps') or 0.0),
        )
        _close_order(
            state,
            order,
            date=_market_date(),
            exit_fill_usd=fill,
            reason='사용자 가상매도',
            fx_rate=fx,
            raw_trigger_usd=float(price),
        )
    else:
        raise ValueError('이미 종료된 가상주문입니다')

    return snapshot(store.save(state))
