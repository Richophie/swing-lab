from __future__ import annotations

from collections import defaultdict
from statistics import mean

from backtest_engine import simulate
from config import (
    BACKTEST_INITIAL_CAPITAL_KRW,
    BACKTEST_MAX_POSITION_PCT,
    BACKTEST_MAX_POSITIONS,
    BACKTEST_RISK_PER_TRADE_PCT,
)
from market_data import load_price_history


def _position_notional(
    equity_krw: float,
    cash_krw: float,
    risk_pct: float,
    risk_per_trade_pct: float,
    max_position_pct: float,
) -> float:
    """Risk-based notional sizing in KRW without requiring a USD/KRW assumption."""
    if equity_krw <= 0 or cash_krw <= 0:
        return 0.0
    risk_fraction = max(float(risk_pct), 0.001)
    risk_budget = float(equity_krw) * float(risk_per_trade_pct) / 100.0
    risk_sized = risk_budget / risk_fraction
    position_cap = float(equity_krw) * float(max_position_pct) / 100.0
    return max(0.0, min(float(cash_krw), risk_sized, position_cap))


def _equity_at_cost(cash_krw: float, positions: dict) -> float:
    return float(cash_krw) + sum(float(p['notional_krw']) for p in positions.values())


def _stress_equity(cash_krw: float, positions: dict) -> float:
    """Conservative floor if every open position were marked to its planned stop simultaneously."""
    value = float(cash_krw)
    for position in positions.values():
        notional = float(position['notional_krw'])
        risk_pct = max(0.0, float(position['trade'].get('risk_pct') or 0.0))
        value += notional * max(0.0, 1.0 - risk_pct)
    return value


def simulate_portfolio(
    trades: list[dict],
    initial_capital_krw: float = BACKTEST_INITIAL_CAPITAL_KRW,
    max_positions: int = BACKTEST_MAX_POSITIONS,
    risk_per_trade_pct: float = BACKTEST_RISK_PER_TRADE_PCT,
    max_position_pct: float = BACKTEST_MAX_POSITION_PCT,
) -> dict:
    """Simulate overlapping trade candidates as one finite KRW account.

    Candidate selection never looks at future return. When more candidates arrive
    than the account can hold, higher ex-ante canonical risk/reward is preferred,
    then ticker as a deterministic tie-break. Entries are processed before exits
    on the same date so intraday exits cannot optimistically fund opening-auction
    entries from that same session.
    """
    initial_capital_krw = float(initial_capital_krw)
    max_positions = max(1, int(max_positions))
    risk_per_trade_pct = max(0.01, float(risk_per_trade_pct))
    max_position_pct = min(100.0, max(0.01, float(max_position_pct)))

    entries = defaultdict(list)
    exits = defaultdict(list)
    for seq, trade in enumerate(trades):
        t = dict(trade)
        t['_seq'] = seq
        if not t.get('entry_date') or not t.get('exit_date'):
            continue
        entries[str(t['entry_date'])].append(t)
        exits[str(t['exit_date'])].append(t)

    dates = sorted(set(entries) | set(exits))
    cash = initial_capital_krw
    positions = {}
    accepted = []
    rejected_capacity = 0
    rejected_cash = 0
    peak_equity = initial_capital_krw
    max_drawdown = 0.0
    stress_peak = initial_capital_krw
    stress_max_drawdown = 0.0
    max_concurrent = 0
    snapshots = []

    for day in dates:
        # Conservative ordering: reserve capital for today's opens before allowing
        # today's exits to replenish cash.
        todays_entries = sorted(
            entries.get(day, []),
            key=lambda t: (-float(t.get('risk_reward') or 0.0), str(t.get('symbol') or ''), int(t['_seq'])),
        )
        for trade in todays_entries:
            if len(positions) >= max_positions:
                rejected_capacity += 1
                continue

            equity = _equity_at_cost(cash, positions)
            notional = _position_notional(
                equity,
                cash,
                float(trade.get('risk_pct') or 0.0),
                risk_per_trade_pct,
                max_position_pct,
            )
            if notional < 1.0:
                rejected_cash += 1
                continue

            key = int(trade['_seq'])
            positions[key] = {'trade': trade, 'notional_krw': notional}
            cash -= notional
            accepted.append(
                {
                    'seq': key,
                    'symbol': trade.get('symbol'),
                    'strategy_id': trade.get('strategy_id'),
                    'entry_date': trade.get('entry_date'),
                    'exit_date': trade.get('exit_date'),
                    'notional_krw': round(notional, 0),
                    'risk_pct': round(float(trade.get('risk_pct') or 0.0) * 100, 3),
                    'risk_reward': round(float(trade.get('risk_reward') or 0.0), 3),
                    'ret_pct': round(float(trade.get('ret') or 0.0) * 100, 3),
                    'reason': trade.get('reason'),
                }
            )
            max_concurrent = max(max_concurrent, len(positions))

        for trade in sorted(exits.get(day, []), key=lambda t: int(t['_seq'])):
            key = int(trade['_seq'])
            position = positions.pop(key, None)
            if position is None:
                continue
            notional = float(position['notional_krw'])
            pnl = notional * float(trade.get('ret') or 0.0)
            cash += notional + pnl

        equity = _equity_at_cost(cash, positions)
        peak_equity = max(peak_equity, equity)
        if peak_equity > 0:
            max_drawdown = min(max_drawdown, equity / peak_equity - 1.0)

        stress_equity = _stress_equity(cash, positions)
        stress_peak = max(stress_peak, stress_equity)
        if stress_peak > 0:
            stress_max_drawdown = min(stress_max_drawdown, stress_equity / stress_peak - 1.0)

        snapshots.append(
            {
                'date': day,
                'equity_krw': round(equity, 0),
                'cash_krw': round(cash, 0),
                'open_positions': len(positions),
                'stress_equity_krw': round(stress_equity, 0),
            }
        )

    ending_equity = _equity_at_cost(cash, positions)
    # Every generated candidate should have a scheduled exit, but keep this safe
    # for malformed external inputs.
    if positions:
        for position in positions.values():
            notional = float(position['notional_krw'])
            pnl = notional * float(position['trade'].get('ret') or 0.0)
            cash += notional + pnl
        positions.clear()
        ending_equity = cash

    accepted_returns = [float(x['ret_pct']) for x in accepted]
    wins = sum(x > 0 for x in accepted_returns)
    avg_notional = mean(float(x['notional_krw']) for x in accepted) if accepted else 0.0

    return {
        'engine': 'Swing Lab Portfolio Backtest V2',
        'initial_capital_krw': round(initial_capital_krw, 0),
        'ending_capital_krw': round(ending_equity, 0),
        'realized_pnl_krw': round(ending_equity - initial_capital_krw, 0),
        'return_pct': round((ending_equity / initial_capital_krw - 1.0) * 100, 2) if initial_capital_krw > 0 else None,
        'max_drawdown_pct': round(max_drawdown * 100, 2),
        'stress_drawdown_pct': round(stress_max_drawdown * 100, 2),
        'accepted_trades': len(accepted),
        'win_rate_pct': round(wins / len(accepted) * 100, 1) if accepted else 0.0,
        'avg_position_krw': round(avg_notional, 0),
        'max_concurrent_positions': max_concurrent,
        'rejected_capacity': rejected_capacity,
        'rejected_cash': rejected_cash,
        'settings': {
            'max_positions': max_positions,
            'risk_per_trade_pct': risk_per_trade_pct,
            'max_position_pct': max_position_pct,
            'position_unit': 'KRW notional; fractional exposure model; no historical FX/share-rounding assumption',
            'same_day_cash_rule': 'entries before exits; same-day exit proceeds are not reused for opening entries',
            'candidate_priority': 'higher ex-ante canonical risk/reward, then ticker',
        },
        'trades': accepted,
        'equity_curve': snapshots,
    }


def build_trade_candidates(symbols: list[str], strategy_id: str, period: str = '10y') -> list[dict]:
    candidates = []
    for symbol in list(dict.fromkeys(str(s).upper().strip() for s in symbols if s)):
        try:
            d = load_price_history(symbol, period)
            candidates.extend(simulate(d, strategy_id, symbol=symbol))
        except Exception:
            continue
    candidates.sort(key=lambda t: (str(t.get('entry_date')), -float(t.get('risk_reward') or 0.0), str(t.get('symbol') or '')))
    return candidates


def run_portfolio_backtest(symbols: list[str], strategy_id: str, period: str = '10y') -> dict:
    candidates = build_trade_candidates(symbols, strategy_id, period)
    result = simulate_portfolio(candidates)
    result['strategy_id'] = strategy_id
    result['symbols'] = list(dict.fromkeys(str(s).upper().strip() for s in symbols if s))
    result['candidate_trades'] = len(candidates)
    return result
