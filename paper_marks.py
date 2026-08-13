from __future__ import annotations

from datetime import timezone
import math

import pandas as pd
import yfinance as yf

from backtest_engine import market_sell_fill
from market_data import fresh_price_history
from paper_broker import PaperBrokerStore
from paper_broker_service import current_fx_rate
from stock_names import canonical_symbol


def _f(value, default=None):
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _price_mark(symbol: str) -> tuple[float | None, str | None, str]:
    """Best-effort recent market mark without advancing Paper Broker lifecycle.

    Prefer a 1-minute quote so the Paper page can show a useful intraday mark. If
    Yahoo does not return intraday data, fall back to the latest daily close.
    """
    symbol = canonical_symbol(symbol)
    try:
        d = yf.Ticker(symbol).history(period='2d', interval='1m', auto_adjust=False, prepost=False)
        if d is not None and not d.empty and 'Close' in d:
            s = d['Close'].dropna()
            if len(s):
                idx = pd.Timestamp(s.index[-1])
                if idx.tzinfo is not None:
                    at = idx.tz_convert(timezone.utc).isoformat()
                else:
                    at = idx.isoformat()
                return float(s.iloc[-1]), at, '1m'
    except Exception:
        pass

    try:
        d = fresh_price_history(symbol, '5d')
        if d is not None and not d.empty:
            s = d['Close'].dropna()
            if len(s):
                idx = pd.Timestamp(s.index[-1])
                at = idx.isoformat()
                return float(s.iloc[-1]), at, 'daily'
    except Exception:
        pass
    return None, None, 'unavailable'


def current_marks(state_path) -> dict:
    state = PaperBrokerStore(state_path).load()
    active = [o for o in state.get('orders', []) if o.get('status') in {'PENDING', 'FILLED'}]
    if not active:
        cash = float(state.get('cash_krw') or 0.0)
        return {
            'orders': [],
            'fx_rate': None,
            'summary': {
                'cash_krw': round(cash, 2),
                'gross_market_value_krw': 0.0,
                'estimated_liquidation_value_krw': 0.0,
                'equity_krw': round(cash, 2),
                'unrealized_pnl_krw': 0.0,
            },
            'live_trading_enabled': False,
        }

    try:
        fx = float(current_fx_rate())
    except Exception:
        fx = None

    quote_cache: dict[str, tuple[float | None, str | None, str]] = {}
    rows = []
    gross_market_value = 0.0
    estimated_liquidation_value = 0.0
    unrealized_total = 0.0

    for order in active:
        symbol = str(order.get('symbol') or '').upper().strip()
        if symbol not in quote_cache:
            quote_cache[symbol] = _price_mark(symbol)
        price, price_at, price_source = quote_cache[symbol]

        row = {
            'order_id': order.get('id'),
            'symbol': symbol,
            'strategy_id': order.get('strategy_id'),
            'strategy_name': order.get('strategy_name'),
            'status': order.get('status'),
            'current_price_usd': None if price is None else round(float(price), 6),
            'price_at': price_at,
            'price_source': price_source,
            'fx_rate': None if fx is None else round(fx, 4),
            'market_value_krw': None,
            'unrealized_pnl_krw': None,
            'unrealized_return_pct': None,
        }

        if order.get('status') == 'FILLED' and price is not None and fx is not None:
            qty = int(order.get('qty') or 0)
            entry_cost = _f(order.get('entry_cost_krw'), 0.0) or 0.0
            commission = max(0.0, _f(order.get('commission_pct_per_side'), 0.0) or 0.0) / 100.0
            slippage = _f(order.get('slippage_bps'), 0.0) or 0.0
            half_spread = _f(order.get('half_spread_bps'), 0.0) or 0.0
            liquidation_fill = market_sell_fill(float(price), slippage, half_spread)
            gross_value = qty * float(price) * fx
            liquidation_value = qty * liquidation_fill * fx * (1.0 - commission)
            pnl = liquidation_value - entry_cost
            gross_market_value += gross_value
            estimated_liquidation_value += liquidation_value
            unrealized_total += pnl
            row.update({
                'market_value_krw': round(gross_value, 2),
                'estimated_liquidation_value_krw': round(liquidation_value, 2),
                'estimated_exit_fill_usd': round(liquidation_fill, 6),
                'unrealized_pnl_krw': round(pnl, 2),
                'unrealized_return_pct': round(pnl / entry_cost * 100.0, 3) if entry_cost > 0 else 0.0,
                'pnl_basis': 'estimated liquidation after configured spread/slippage/commission',
            })
        rows.append(row)

    cash = float(state.get('cash_krw') or 0.0)
    summary = {
        'cash_krw': round(cash, 2),
        'gross_market_value_krw': round(gross_market_value, 2),
        'estimated_liquidation_value_krw': round(estimated_liquidation_value, 2),
        'equity_krw': round(cash + estimated_liquidation_value, 2),
        'unrealized_pnl_krw': round(unrealized_total, 2),
    }
    return {'orders': rows, 'fx_rate': fx, 'summary': summary, 'live_trading_enabled': False}
