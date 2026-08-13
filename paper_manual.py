from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
from pathlib import Path
from zoneinfo import ZoneInfo

from backtest_engine import market_buy_fill, market_sell_fill
from paper_broker import PaperBrokerStore, _cancel_order, _close_order, _event, snapshot, submit_order
from paper_broker_service import (
    _latest_market_date,
    _tag_legacy_origins,
    current_fx_rate,
    latest_plan,
)
from paper_marks import _price_mark
from paper_plan import execution_plan_with_atr

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
            event['detail'] = f"사용자 즉시 가상매수 준비 · {qty}주"
            break


def _build_order(
    state: dict,
    *,
    symbol: str,
    strategy_id: str | None,
    requested_qty: int | None,
) -> dict:
    info = latest_plan(symbol, strategy_id)
    plan = execution_plan_with_atr(info['plan'])
    if not plan.get('atr'):
        raise ValueError('ATR 실행값을 복원할 수 없어 가상주문을 만들지 않았습니다')
    fx = current_fx_rate()
    market_date = _latest_market_date(info['symbol'])
    order = submit_order(
        state,
        symbol=info['symbol'],
        strategy_id=info['strategy_id'],
        strategy_name=info['strategy_name'],
        plan=plan,
        fx_rate=fx,
        submitted_market_date=market_date,
        signal_date=info.get('scan_date') or market_date,
    )
    max_qty = int(order.get('qty') or 0)
    order['max_allowed_qty'] = max_qty
    order['atr_source'] = plan.get('atr_source') or 'stored'
    if requested_qty is not None:
        _resize_order(order, state, int(requested_qty))
    order['order_origin'] = 'MANUAL_PAPER'
    order['signal_origin'] = 'user_selected_latest_scan'
    order['event_risk_snapshot'] = dict(info.get('event_risk_snapshot') or {})
    order['risk_observability_only'] = True
    order['manual_fill_policy'] = 'immediate_latest_available_quote'
    for event in reversed(state.get('events', [])):
        if event.get('order_id') == order.get('id') and event.get('event') == 'SUBMITTED':
            event['detail'] = f"사용자 즉시 가상매수 준비 · {order['qty']}주"
            break
    return order


def _fill_manual_now(state: dict, order: dict, *, allow_resize: bool = True) -> dict:
    price, price_at, price_source = _price_mark(str(order.get('symbol') or ''))
    if price is None:
        raise ValueError('현재 가상체결 기준가를 확인하지 못했습니다')
    fx = float(current_fx_rate())
    stop = float(order['stop'])
    target = float(order['target'])
    raw = float(price)
    if raw <= stop:
        raise ValueError(f'현재가 ${raw:.2f}가 STOP ${stop:.2f} 이하라 새 가상매수를 막았습니다')
    if raw >= target:
        raise ValueError(f'현재가 ${raw:.2f}가 TARGET ${target:.2f} 이상이라 새 가상매수를 막았습니다')

    fill = market_buy_fill(raw, float(order.get('slippage_bps') or 0.0), float(order.get('half_spread_bps') or 0.0))
    if not stop < fill < target:
        raise ValueError('체결비용 반영 후 STOP < 체결가 < TARGET 구조가 아닙니다')

    commission = max(0.0, float(order.get('commission_pct_per_side') or 0.0)) / 100.0
    per_share_cost = fill * fx * (1.0 + commission)
    cash = max(0.0, float(state.get('cash_krw') or 0.0))
    by_cash = math.floor(cash / per_share_cost)
    actual_risk_per_share = max((fill - stop) * fx, 0.0)
    risk_budget = max(0.0, float(order.get('risk_budget_krw') or 0.0))
    by_risk = math.floor(risk_budget / actual_risk_per_share) if actual_risk_per_share > 0 else 0
    allowed = max(0, min(by_cash, by_risk))
    requested = int(order.get('qty') or 0)
    if allowed < 1:
        raise ValueError('현재 가격·현금·리스크 기준으로 1주도 즉시 가상체결할 수 없습니다')
    if requested > allowed:
        if not allow_resize:
            raise ValueError(f'현재 가격 기준 최대 {allowed}주까지 즉시 가상체결 가능합니다')
        order['qty'] = allowed
    qty = int(order['qty'])

    gross = fill * qty * fx
    entry_commission = gross * commission
    entry_cost = gross + entry_commission
    state['cash_krw'] = round(cash - entry_cost, 2)
    order.update(
        {
            'status': 'FILLED',
            'entry_date': _market_date(),
            'entry_fill_usd': round(fill, 6),
            'entry_raw_open_usd': round(raw, 6),
            'entry_timestamp': price_at,
            'entry_resolution_quality': f'manual_{price_source}_quote',
            'entry_commission_krw': round(entry_commission, 2),
            'entry_cost_krw': round(entry_cost, 2),
            'fx_at_entry': round(fx, 4),
            'reserved_cash_krw': 0.0,
            'held_bars': 0,
            'last_close_usd': round(raw, 6),
            'last_fx': round(fx, 4),
            'last_processed_date': str(order.get('submitted_market_date') or _market_date())[:10],
            'filled_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'manual_fill_quote_source': price_source,
        }
    )
    _event(
        state,
        order,
        'FILLED',
        f"사용자 즉시 가상매수 · {qty}주 · ${fill:.4f} · 기준 {price_source} {price_at or ''}".strip(),
    )
    return order


def _legacy_submit_fill_values(order: dict) -> tuple[float, float, str, str]:
    raw = float(order.get('planned_entry_usd') or ((float(order['buy_low']) + float(order['buy_high'])) / 2.0))
    fx = float(order.get('fx_at_submit') or current_fx_rate())
    timestamp = str(order.get('created_at') or '') or datetime.now(timezone.utc).isoformat(timespec='seconds')
    market_date = str(order.get('submitted_market_date') or order.get('signal_date') or timestamp)[:10]
    return raw, fx, timestamp, market_date


def _apply_legacy_submit_fill(state: dict, order: dict, *, repair_existing_fill: bool = False) -> dict:
    """Honor the user's original click for pre-immediate-fill manual orders.

    Before manual paper buys became immediate, clicking "가상매수" created a
    PENDING next-open order. Those clicks should be interpreted as buys at the
    price shown/stored at that click, not at a later deployment-time quote.
    """
    raw, fx, timestamp, market_date = _legacy_submit_fill_values(order)
    stop = float(order['stop'])
    target = float(order['target'])
    if not stop < raw < target:
        raise ValueError('기존 주문의 저장 진입가가 STOP/TARGET 사이가 아닙니다')
    fill = market_buy_fill(raw, float(order.get('slippage_bps') or 0.0), float(order.get('half_spread_bps') or 0.0))
    if not stop < fill < target:
        raise ValueError('기존 주문의 체결비용 반영 진입가가 STOP/TARGET 사이가 아닙니다')

    qty = max(1, int(order.get('qty') or 0))
    commission = max(0.0, float(order.get('commission_pct_per_side') or 0.0)) / 100.0
    gross = fill * qty * fx
    entry_commission = gross * commission
    entry_cost = gross + entry_commission
    cash = float(state.get('cash_krw') or 0.0)
    if repair_existing_fill:
        cash += float(order.get('entry_cost_krw') or 0.0)
    if entry_cost > cash + 0.01:
        raise ValueError('기존 클릭시점 기준 체결금액이 가상계좌 현금을 초과합니다')
    state['cash_krw'] = round(cash - entry_cost, 2)

    order.update(
        {
            'status': 'FILLED',
            'entry_date': market_date,
            'entry_fill_usd': round(fill, 6),
            'entry_raw_open_usd': round(raw, 6),
            'entry_timestamp': timestamp,
            'entry_resolution_quality': 'manual_legacy_click_price',
            'entry_commission_krw': round(entry_commission, 2),
            'entry_cost_krw': round(entry_cost, 2),
            'fx_at_entry': round(fx, 4),
            'reserved_cash_krw': 0.0,
            'held_bars': int(order.get('held_bars') or 0),
            'last_close_usd': round(float(order.get('last_close_usd') or raw), 6),
            'last_fx': round(float(order.get('last_fx') or fx), 4),
            'last_processed_date': market_date,
            'filled_at': timestamp,
            'manual_fill_quote_source': 'legacy_planned_entry_at_click',
            'manual_immediate_upgrade': True,
            'manual_immediate_upgrade_repaired': True,
            'manual_immediate_upgrade_basis': 'stored_planned_entry_fx_and_created_at',
        }
    )
    _event(
        state,
        order,
        'MIGRATION_REPAIRED' if repair_existing_fill else 'FILLED',
        f"기존 수동 가상매수 · 클릭 당시 저장가 기준 {qty}주 · ${fill:.4f} · {timestamp}",
    )
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
    price, price_at, price_source = _price_mark(order['symbol'])
    return {
        'symbol': order['symbol'],
        'strategy_id': order['strategy_id'],
        'strategy_name': order['strategy_name'],
        'max_qty': int(order['qty']),
        'planned_entry_usd': order.get('planned_entry_usd'),
        'current_quote_usd': None if price is None else round(float(price), 6),
        'current_quote_at': price_at,
        'current_quote_source': price_source,
        'planned_notional_krw': order.get('planned_notional_krw'),
        'planned_risk_krw': order.get('planned_risk_krw'),
        'risk_budget_krw': order.get('risk_budget_krw'),
        'gap_guard': order.get('gap_guard'),
        'atr': order.get('atr'),
        'available_cash_krw': snapshot(state)['summary'].get('available_cash_krw'),
        'fill_policy': 'immediate_latest_available_quote',
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
    order = _build_order(state, symbol=symbol, strategy_id=strategy_id, requested_qty=requested_qty)
    _fill_manual_now(state, order, allow_resize=requested_qty is None)
    saved = store.save(state)
    out = snapshot(saved)
    out['submitted_order_id'] = order.get('id')
    out['submitted_qty'] = int(order.get('qty') or 0)
    out['max_allowed_qty'] = int(order.get('max_allowed_qty') or order.get('qty') or 0)
    out['filled_immediately'] = True
    out['entry_fill_usd'] = order.get('entry_fill_usd')
    return out


def upgrade_pending_manual_orders(*, state_path: str | Path) -> int:
    """Migrate pre-immediate-fill manual clicks without changing their original buy basis."""
    store = PaperBrokerStore(state_path)
    state = store.load()
    _tag_legacy_origins(state)
    changed = 0

    # Repair orders that the first immediate-fill migration may already have filled
    # using a later quote after deployment. Restore their original click-time basis.
    for order in state.get('orders', []):
        if order.get('order_origin') != 'MANUAL_PAPER' or order.get('status') != 'FILLED':
            continue
        if not order.get('manual_immediate_upgrade') or order.get('manual_immediate_upgrade_repaired'):
            continue
        try:
            _apply_legacy_submit_fill(state, order, repair_existing_fill=True)
            changed += 1
        except Exception as exc:
            order['manual_immediate_upgrade_repair_error'] = str(exc)

    # Orders that have not yet been touched by the first migration are filled at
    # the price/FX/timestamp that were stored when the user originally clicked buy.
    for order in state.get('orders', []):
        if order.get('status') != 'PENDING' or order.get('order_origin') != 'MANUAL_PAPER':
            continue
        if order.get('manual_immediate_upgrade_repaired'):
            continue
        try:
            _apply_legacy_submit_fill(state, order, repair_existing_fill=False)
            order['manual_immediate_upgrade_attempted'] = True
            changed += 1
        except Exception as exc:
            order['manual_immediate_upgrade_attempted'] = True
            order['manual_immediate_upgrade_error'] = str(exc)

    if changed or any(
        o.get('manual_immediate_upgrade_attempted') or o.get('manual_immediate_upgrade_repaired')
        for o in state.get('orders', [])
    ):
        store.save(state)
    return changed


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
