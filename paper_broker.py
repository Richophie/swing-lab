from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import threading
import uuid

from backtest_engine import exit_fill_for_bar, market_buy_fill, market_sell_fill
from config import (
    BACKTEST_COMMISSION_PCT,
    BACKTEST_HALF_SPREAD_BPS,
    BACKTEST_INITIAL_CAPITAL_KRW,
    BACKTEST_MAX_POSITION_PCT,
    BACKTEST_MAX_POSITIONS,
    BACKTEST_RISK_PER_TRADE_PCT,
    BACKTEST_SLIPPAGE_BPS,
)
from strategy_rules import ENTRY_GAP_ATR, ENTRY_GAP_PCT

PAPER_STATE_VERSION = 1
ACTIVE_STATUSES = {'PENDING', 'FILLED'}
TERMINAL_STATUSES = {'CLOSED', 'CANCELLED', 'REJECTED'}


def _now_iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec='seconds')


def _f(value, default=None):
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _date_text(value) -> str:
    if hasattr(value, 'strftime'):
        return value.strftime('%Y-%m-%d')
    text = str(value or '').strip()
    if 'T' in text:
        text = text.split('T', 1)[0]
    return text[:10]


def new_state(initial_cash_krw: float = BACKTEST_INITIAL_CAPITAL_KRW) -> dict:
    cash = max(0.0, float(initial_cash_krw))
    now = _now_iso()
    return {
        'version': PAPER_STATE_VERSION,
        'starting_cash_krw': round(cash, 2),
        'cash_krw': round(cash, 2),
        'orders': [],
        'events': [],
        'created_at': now,
        'updated_at': now,
        'live_trading_enabled': False,
    }


def _active_orders(state: dict) -> list[dict]:
    return [o for o in state.get('orders', []) if o.get('status') in ACTIVE_STATUSES]


def _reserved_cash_krw(state: dict) -> float:
    return sum(float(o.get('reserved_cash_krw') or 0.0) for o in state.get('orders', []) if o.get('status') == 'PENDING')


def _open_market_value_krw(state: dict) -> float:
    total = 0.0
    for order in state.get('orders', []):
        if order.get('status') != 'FILLED':
            continue
        qty = int(order.get('qty') or 0)
        px = _f(order.get('last_close_usd'), _f(order.get('entry_fill_usd'), 0.0)) or 0.0
        fx = _f(order.get('last_fx'), _f(order.get('fx_at_entry'), 0.0)) or 0.0
        total += qty * px * fx
    return total


def state_summary(state: dict) -> dict:
    cash = float(state.get('cash_krw') or 0.0)
    reserved = _reserved_cash_krw(state)
    market_value = _open_market_value_krw(state)
    equity = cash + market_value
    closed = [o for o in state.get('orders', []) if o.get('status') == 'CLOSED']
    realized = sum(float(o.get('pnl_krw') or 0.0) for o in closed)
    unrealized = 0.0
    for order in state.get('orders', []):
        if order.get('status') != 'FILLED':
            continue
        qty = int(order.get('qty') or 0)
        px = _f(order.get('last_close_usd'), _f(order.get('entry_fill_usd'), 0.0)) or 0.0
        fx = _f(order.get('last_fx'), _f(order.get('fx_at_entry'), 0.0)) or 0.0
        current_value = qty * px * fx
        unrealized += current_value - float(order.get('entry_cost_krw') or 0.0)
    wins = sum(1 for o in closed if float(o.get('pnl_krw') or 0.0) > 0)
    return {
        'starting_cash_krw': round(float(state.get('starting_cash_krw') or 0.0), 2),
        'cash_krw': round(cash, 2),
        'reserved_cash_krw': round(reserved, 2),
        'available_cash_krw': round(max(0.0, cash - reserved), 2),
        'open_market_value_krw': round(market_value, 2),
        'equity_krw': round(equity, 2),
        'realized_pnl_krw': round(realized, 2),
        'unrealized_pnl_krw': round(unrealized, 2),
        'pending_orders': sum(1 for o in state.get('orders', []) if o.get('status') == 'PENDING'),
        'open_positions': sum(1 for o in state.get('orders', []) if o.get('status') == 'FILLED'),
        'closed_trades': len(closed),
        'win_rate_pct': round(wins / len(closed) * 100.0, 1) if closed else 0.0,
        'live_trading_enabled': False,
    }


def snapshot(state: dict) -> dict:
    out = deepcopy(state)
    out['summary'] = state_summary(out)
    return out


def _event(state: dict, order: dict, event: str, detail: str, at: str | None = None) -> None:
    state.setdefault('events', []).append(
        {
            'at': at or _now_iso(),
            'order_id': order.get('id'),
            'symbol': order.get('symbol'),
            'strategy_id': order.get('strategy_id'),
            'event': event,
            'detail': detail,
        }
    )
    # Keep the local paper ledger compact while retaining recent audit history.
    if len(state['events']) > 1000:
        state['events'] = state['events'][-1000:]


def submit_order(
    state: dict,
    *,
    symbol: str,
    strategy_id: str,
    strategy_name: str,
    plan: dict,
    fx_rate: float,
    submitted_market_date: str,
    signal_date: str | None = None,
    max_positions: int = BACKTEST_MAX_POSITIONS,
    risk_per_trade_pct: float = BACKTEST_RISK_PER_TRADE_PCT,
    max_position_pct: float = BACKTEST_MAX_POSITION_PCT,
    commission_pct: float = BACKTEST_COMMISSION_PCT,
    order_id: str | None = None,
    now: datetime | None = None,
) -> dict:
    symbol = str(symbol or '').upper().strip()
    strategy_id = str(strategy_id or '').strip()
    if not symbol or not strategy_id:
        raise ValueError('symbol과 strategy_id가 필요합니다')
    if any(o.get('symbol') == symbol and o.get('strategy_id') == strategy_id and o.get('status') in ACTIVE_STATUSES for o in state.get('orders', [])):
        raise ValueError('같은 종목·전략의 가상 주문이 이미 진행 중입니다')
    if len(_active_orders(state)) >= int(max_positions):
        raise ValueError('가상계좌 최대 동시 포지션 수에 도달했습니다')

    buy_low = _f(plan.get('entry_low', plan.get('buy_low')))
    buy_high = _f(plan.get('entry_high', plan.get('buy_high')))
    target = _f(plan.get('target'))
    stop = _f(plan.get('stop'))
    atr = _f(plan.get('atr'))
    if None in (buy_low, buy_high, target, stop):
        raise ValueError('BUY/TARGET/STOP 계획이 완전하지 않습니다')
    if buy_low > buy_high:
        buy_low, buy_high = buy_high, buy_low
    entry_ref = (buy_low + buy_high) / 2.0
    if not stop < entry_ref < target:
        raise ValueError('STOP < BUY < TARGET 구조가 아닙니다')
    fx = _f(fx_rate)
    if fx is None or fx <= 0:
        raise ValueError('유효한 USD/KRW 환율이 필요합니다')

    summary = state_summary(state)
    equity = max(float(summary['equity_krw']), 1.0)
    available_cash = max(float(summary['available_cash_krw']), 0.0)
    risk_budget = equity * max(0.0, float(risk_per_trade_pct)) / 100.0
    position_cap = min(available_cash, equity * max(0.0, float(max_position_pct)) / 100.0)
    risk_per_share_krw = max((entry_ref - stop) * fx, 0.0)
    commission = max(0.0, float(commission_pct)) / 100.0
    per_share_budget = entry_ref * fx * (1.0 + commission)
    if risk_per_share_krw <= 0 or per_share_budget <= 0 or position_cap <= 0:
        raise ValueError('가상 주문 수량을 계산할 수 없습니다')
    by_risk = math.floor(risk_budget / risk_per_share_krw) if risk_budget > 0 else 0
    by_cash = math.floor(position_cap / per_share_budget)
    qty = int(min(by_risk, by_cash))
    if qty < 1:
        raise ValueError('현재 가상계좌 자금/리스크 한도에서 1주도 진입할 수 없습니다')

    max_hold = plan.get('days_max')
    if max_hold is None and isinstance(plan.get('target_days'), dict):
        max_hold = plan['target_days'].get('days_high')
    if max_hold is None and isinstance(plan.get('days'), (list, tuple)) and len(plan['days']) >= 2:
        max_hold = plan['days'][1]
    max_hold = max(1, int(max_hold or 5))
    gap_guard = max(
        ENTRY_GAP_ATR * atr if atr is not None and atr > 0 else 0.0,
        ENTRY_GAP_PCT * entry_ref,
    )
    reserved = qty * per_share_budget
    created = _now_iso(now)
    order = {
        'id': order_id or f"PAPER-{uuid.uuid4().hex[:12].upper()}",
        'symbol': symbol,
        'strategy_id': strategy_id,
        'strategy_name': strategy_name or strategy_id,
        'status': 'PENDING',
        'created_at': created,
        'submitted_market_date': _date_text(submitted_market_date),
        'signal_date': _date_text(signal_date or submitted_market_date),
        'buy_low': round(buy_low, 6),
        'buy_high': round(buy_high, 6),
        'target': round(target, 6),
        'stop': round(stop, 6),
        'atr': None if atr is None else round(atr, 6),
        'gap_guard': round(gap_guard, 6),
        'max_hold_bars': max_hold,
        'held_bars': 0,
        'qty': qty,
        'planned_entry_usd': round(entry_ref, 6),
        'planned_notional_krw': round(qty * entry_ref * fx, 2),
        'risk_budget_krw': round(risk_budget, 2),
        'planned_risk_krw': round(qty * risk_per_share_krw, 2),
        'reserved_cash_krw': round(reserved, 2),
        'fx_at_submit': round(fx, 4),
        'last_processed_date': _date_text(submitted_market_date),
        'commission_pct_per_side': float(commission_pct),
        'slippage_bps': float(BACKTEST_SLIPPAGE_BPS),
        'half_spread_bps': float(BACKTEST_HALF_SPREAD_BPS),
        'live_order_sent': False,
    }
    state.setdefault('orders', []).append(order)
    state['updated_at'] = created
    _event(state, order, 'SUBMITTED', f"다음 거래일 시가 대기 · {qty}주 · BUY {buy_low:.2f}~{buy_high:.2f}", created)
    return order


def _close_order(
    state: dict,
    order: dict,
    *,
    date: str,
    exit_fill_usd: float,
    reason: str,
    fx_rate: float,
    raw_trigger_usd: float | None = None,
) -> None:
    qty = int(order.get('qty') or 0)
    fx = float(fx_rate)
    commission = max(0.0, float(order.get('commission_pct_per_side') or 0.0)) / 100.0
    gross_proceeds = float(exit_fill_usd) * qty * fx
    exit_commission = gross_proceeds * commission
    net_proceeds = gross_proceeds - exit_commission
    entry_cost = float(order.get('entry_cost_krw') or 0.0)
    state['cash_krw'] = round(float(state.get('cash_krw') or 0.0) + net_proceeds, 2)
    pnl = net_proceeds - entry_cost
    order.update(
        {
            'status': 'CLOSED',
            'exit_date': _date_text(date),
            'exit_fill_usd': round(float(exit_fill_usd), 6),
            'exit_raw_trigger_usd': None if raw_trigger_usd is None else round(float(raw_trigger_usd), 6),
            'exit_reason': reason,
            'exit_commission_krw': round(exit_commission, 2),
            'exit_proceeds_krw': round(net_proceeds, 2),
            'pnl_krw': round(pnl, 2),
            'return_pct': round(pnl / entry_cost * 100.0, 3) if entry_cost > 0 else 0.0,
            'last_close_usd': round(float(exit_fill_usd), 6),
            'last_fx': round(fx, 4),
            'last_processed_date': _date_text(date),
            'reserved_cash_krw': 0.0,
            'closed_at': _now_iso(),
        }
    )
    _event(state, order, 'CLOSED', f"{reason} · {order['return_pct']:+.3f}% · {pnl:+,.0f}원")


def _cancel_order(state: dict, order: dict, date: str, reason: str) -> None:
    order.update(
        {
            'status': 'CANCELLED',
            'cancel_date': _date_text(date),
            'cancel_reason': reason,
            'last_processed_date': _date_text(date),
            'reserved_cash_krw': 0.0,
            'closed_at': _now_iso(),
        }
    )
    _event(state, order, 'CANCELLED', reason)


def process_bar(
    state: dict,
    *,
    symbol: str,
    date: str,
    open_px: float,
    high_px: float,
    low_px: float,
    close_px: float,
    fx_rate: float,
) -> list[dict]:
    symbol = str(symbol or '').upper().strip()
    date = _date_text(date)
    o = float(open_px); h = float(high_px); l = float(low_px); c = float(close_px); fx = float(fx_rate)
    if min(o, h, l, c, fx) <= 0:
        raise ValueError('OHLC와 환율은 양수여야 합니다')
    touched = []
    for order in state.get('orders', []):
        if order.get('symbol') != symbol or order.get('status') not in ACTIVE_STATUSES:
            continue
        if date <= _date_text(order.get('last_processed_date')):
            continue

        if order.get('status') == 'PENDING':
            lower = float(order['buy_low']) - float(order.get('gap_guard') or 0.0)
            upper = float(order['buy_high']) + float(order.get('gap_guard') or 0.0)
            if o < lower or o > upper:
                _cancel_order(state, order, date, f"다음 시가 {o:.2f}가 허용 진입범위 {lower:.2f}~{upper:.2f} 이탈")
                touched.append(order)
                continue
            entry_fill = market_buy_fill(o, float(order['slippage_bps']), float(order['half_spread_bps']))
            if not float(order['stop']) < entry_fill < float(order['target']):
                _cancel_order(state, order, date, '체결비용 반영 후 STOP < 체결가 < TARGET 구조가 깨짐')
                touched.append(order)
                continue
            commission = max(0.0, float(order['commission_pct_per_side'])) / 100.0
            per_share_cost = entry_fill * fx * (1.0 + commission)
            affordable = math.floor(float(state.get('cash_krw') or 0.0) / per_share_cost)
            qty = min(int(order.get('qty') or 0), int(affordable))
            if qty < 1:
                _cancel_order(state, order, date, '실제 가상 체결시점 현금 부족')
                touched.append(order)
                continue
            order['qty'] = qty
            gross_cost = entry_fill * qty * fx
            entry_commission = gross_cost * commission
            entry_cost = gross_cost + entry_commission
            state['cash_krw'] = round(float(state.get('cash_krw') or 0.0) - entry_cost, 2)
            order.update(
                {
                    'status': 'FILLED',
                    'entry_date': date,
                    'entry_fill_usd': round(entry_fill, 6),
                    'entry_raw_open_usd': round(o, 6),
                    'entry_commission_krw': round(entry_commission, 2),
                    'entry_cost_krw': round(entry_cost, 2),
                    'fx_at_entry': round(fx, 4),
                    'reserved_cash_krw': 0.0,
                    'held_bars': 0,
                    'last_close_usd': round(c, 6),
                    'last_fx': round(fx, 4),
                    'last_processed_date': date,
                    'filled_at': _now_iso(),
                }
            )
            _event(state, order, 'FILLED', f"{qty}주 · ${entry_fill:.4f} · {entry_cost:,.0f}원")
            # Conservative daily-bar convention: once the next-open entry is accepted,
            # the entry candle may immediately hit the stop/target. If both are touched,
            # exit_fill_for_bar intentionally resolves to stop first.
            outcome = exit_fill_for_bar(
                o, h, l,
                float(order['target']), float(order['stop']),
                float(order['slippage_bps']), float(order['half_spread_bps']),
            )
            if outcome is not None:
                exit_fill, reason, raw_trigger = outcome
                _close_order(state, order, date=date, exit_fill_usd=exit_fill, reason=reason, fx_rate=fx, raw_trigger_usd=raw_trigger)
            touched.append(order)
            continue

        # Existing filled position: first honor stop/target for the day, then time exit.
        outcome = exit_fill_for_bar(
            o, h, l,
            float(order['target']), float(order['stop']),
            float(order['slippage_bps']), float(order['half_spread_bps']),
        )
        if outcome is not None:
            exit_fill, reason, raw_trigger = outcome
            _close_order(state, order, date=date, exit_fill_usd=exit_fill, reason=reason, fx_rate=fx, raw_trigger_usd=raw_trigger)
            touched.append(order)
            continue

        order['held_bars'] = int(order.get('held_bars') or 0) + 1
        order['last_close_usd'] = round(c, 6)
        order['last_fx'] = round(fx, 4)
        order['last_processed_date'] = date
        if int(order['held_bars']) >= int(order.get('max_hold_bars') or 1):
            exit_fill = market_sell_fill(c, float(order['slippage_bps']), float(order['half_spread_bps']))
            _close_order(state, order, date=date, exit_fill_usd=exit_fill, reason='기간종료', fx_rate=fx, raw_trigger_usd=c)
        touched.append(order)

    state['updated_at'] = _now_iso()
    return touched


class PaperBrokerStore:
    """Small atomic JSON ledger for paper trading only.

    This class intentionally has no brokerage client, HTTP client, API key, or live-order
    method. It is a local simulation boundary that can later be compared with a Toss
    adapter without sharing execution permissions.
    """

    def __init__(self, path: str | Path, initial_cash_krw: float = BACKTEST_INITIAL_CAPITAL_KRW):
        self.path = Path(path)
        self.initial_cash_krw = float(initial_cash_krw)
        self._lock = threading.RLock()

    def load(self) -> dict:
        with self._lock:
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(data, dict) or 'orders' not in data:
                    raise ValueError('invalid paper state')
                data['live_trading_enabled'] = False
                return data
            except FileNotFoundError:
                return new_state(self.initial_cash_krw)

    def save(self, state: dict) -> dict:
        with self._lock:
            state = deepcopy(state)
            state['version'] = PAPER_STATE_VERSION
            state['live_trading_enabled'] = False
            state['updated_at'] = _now_iso()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(self.path.suffix + '.tmp')
            temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
            temp.replace(self.path)
            return state

    def reset(self, initial_cash_krw: float | None = None) -> dict:
        state = new_state(self.initial_cash_krw if initial_cash_krw is None else initial_cash_krw)
        return self.save(state)

    def get_snapshot(self) -> dict:
        return snapshot(self.load())
