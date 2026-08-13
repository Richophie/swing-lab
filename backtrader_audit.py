from __future__ import annotations

import json
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd

from backtest_engine import _historical_market_state, simulate
from config import BACKTEST_COMMISSION_PCT, BACKTEST_HALF_SPREAD_BPS, BACKTEST_SLIPPAGE_BPS
from market_data import load_price_history
from strategy_rules import ENTRY_GAP_ATR, ENTRY_GAP_PCT, canonical_signal_frame, trade_levels_from_row


class SwingAuditData(bt.feeds.PandasData):
    lines = ('signal', 'buy_low', 'buy_high', 'target', 'stop', 'max_hold', 'gap_guard')
    params = (
        ('signal', -1),
        ('buy_low', -1),
        ('buy_high', -1),
        ('target', -1),
        ('stop', -1),
        ('max_hold', -1),
        ('gap_guard', -1),
    )


def prepare_audit_frame(d: pd.DataFrame, strategy_id: str, market_state: pd.Series | None = None) -> pd.DataFrame:
    """Attach canonical signal/plan inputs to OHLCV without reusing Swing Lab execution logic."""
    state = _historical_market_state(d.index) if market_state is None else market_state
    canonical = canonical_signal_frame(d, state)
    if strategy_id not in canonical.columns:
        raise ValueError('알 수 없는 전략')

    out = pd.DataFrame(index=d.index)
    out['open'] = d['Open'].astype(float)
    out['high'] = d['High'].astype(float)
    out['low'] = d['Low'].astype(float)
    out['close'] = d['Close'].astype(float)
    out['volume'] = d['Volume'].astype(float) if 'Volume' in d else 0.0
    out['openinterest'] = 0.0
    out['signal'] = 0.0
    for col in ('buy_low', 'buy_high', 'target', 'stop', 'max_hold', 'gap_guard'):
        out[col] = np.nan

    for i in range(205, len(d) - 1):
        if not bool(canonical[strategy_id].iloc[i]):
            continue
        plan = trade_levels_from_row(canonical.iloc[i], strategy_id)
        close = float(canonical['close'].iloc[i])
        gap_guard = max(ENTRY_GAP_ATR * float(plan['atr']), ENTRY_GAP_PCT * close)
        idx = d.index[i]
        out.at[idx, 'signal'] = 1.0
        out.at[idx, 'buy_low'] = float(plan['buy_low'])
        out.at[idx, 'buy_high'] = float(plan['buy_high'])
        out.at[idx, 'target'] = float(plan['target'])
        out.at[idx, 'stop'] = float(plan['stop'])
        out.at[idx, 'max_hold'] = float(plan['days'][1])
        out.at[idx, 'gap_guard'] = float(gap_guard)
    return out


class BacktraderAuditStrategy(bt.Strategy):
    params = dict(strategy_id='')

    def __init__(self):
        self.pending = None
        self.entry_order = None
        self.stop_order = None
        self.limit_order = None
        self.time_exit_order = None
        self.active = None
        self.entry_bar = None
        self.block_signal_bar = None
        self.audit_trades = []
        self.gap_rejections = []

    def _date(self):
        return self.data.datetime.date(0).isoformat()

    def _clear_orders(self):
        self.entry_order = None
        self.stop_order = None
        self.limit_order = None
        self.time_exit_order = None

    def next_open(self):
        if self.pending is None or self.position or self.entry_order is not None:
            return
        plan = self.pending
        self.pending = None
        open_px = float(self.data.open[0])
        lower = float(plan['buy_low']) - float(plan['gap_guard'])
        upper = float(plan['buy_high']) + float(plan['gap_guard'])
        if open_px < lower or open_px > upper:
            self.gap_rejections.append(
                {
                    'signal_date': plan['signal_date'],
                    'entry_date': self._date(),
                    'open': open_px,
                    'allowed_low': lower,
                    'allowed_high': upper,
                }
            )
            return

        orders = self.buy_bracket(
            size=1,
            exectype=bt.Order.Market,
            stopprice=float(plan['stop']),
            stopexec=bt.Order.Stop,
            limitprice=float(plan['target']),
            limitexec=bt.Order.Limit,
        )
        self.entry_order, self.stop_order, self.limit_order = orders
        self.active = dict(plan)
        self.active['entry_date_requested'] = self._date()

    def next(self):
        if self.position:
            if self.active is not None and self.entry_bar is not None and self.time_exit_order is None:
                held = len(self) - self.entry_bar
                if held >= int(self.active['max_hold']):
                    if self.stop_order is not None and self.stop_order.alive():
                        self.cancel(self.stop_order)
                    if self.limit_order is not None and self.limit_order.alive():
                        self.cancel(self.limit_order)
                    self.time_exit_order = self.close(exectype=bt.Order.Close)
            return

        if self.entry_order is not None or self.pending is not None:
            return
        if self.block_signal_bar is not None and len(self) == self.block_signal_bar:
            return
        if float(self.data.signal[0]) <= 0:
            return

        self.pending = {
            'strategy_id': self.p.strategy_id,
            'signal_date': self._date(),
            'buy_low': float(self.data.buy_low[0]),
            'buy_high': float(self.data.buy_high[0]),
            'target': float(self.data.target[0]),
            'stop': float(self.data.lines.stop[0]),
            'max_hold': int(round(float(self.data.max_hold[0]))),
            'gap_guard': float(self.data.gap_guard[0]),
        }

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted, order.Partial):
            return

        if self.entry_order is not None and order.ref == self.entry_order.ref:
            if order.status == order.Completed:
                if self.active is None:
                    return
                self.active['entry_date'] = bt.num2date(order.executed.dt).date().isoformat()
                self.active['entry_fill'] = float(order.executed.price)
                self.active['entry_commission'] = float(order.executed.comm)
                self.entry_bar = len(self)
                self.entry_order = None
            elif order.status in (order.Canceled, order.Expired, order.Margin, order.Rejected):
                self.active = None
                self.entry_bar = None
                self._clear_orders()
            return

        is_stop = self.stop_order is not None and order.ref == self.stop_order.ref
        is_limit = self.limit_order is not None and order.ref == self.limit_order.ref
        is_time = self.time_exit_order is not None and order.ref == self.time_exit_order.ref
        if not (is_stop or is_limit or is_time):
            return

        if order.status != order.Completed:
            return
        if self.active is None or 'entry_fill' not in self.active:
            return

        reason = '손절' if is_stop else '목표달성' if is_limit else '기간종료'
        entry_fill = float(self.active['entry_fill'])
        entry_comm = float(self.active.get('entry_commission') or 0.0)
        exit_fill = float(order.executed.price)
        exit_comm = float(order.executed.comm)
        entry_cost = entry_fill + entry_comm
        exit_proceeds = exit_fill - exit_comm
        ret = exit_proceeds / entry_cost - 1.0 if entry_cost > 0 else 0.0
        self.audit_trades.append(
            {
                'strategy_id': self.p.strategy_id,
                'signal_date': self.active.get('signal_date'),
                'entry_date': self.active.get('entry_date'),
                'exit_date': bt.num2date(order.executed.dt).date().isoformat(),
                'entry_fill': entry_fill,
                'exit_fill': exit_fill,
                'target': float(self.active['target']),
                'stop': float(self.active['stop']),
                'reason': reason,
                'ret': ret,
                'entry_commission': entry_comm,
                'exit_commission': exit_comm,
            }
        )
        self.active = None
        self.entry_bar = None
        self.block_signal_bar = len(self)
        self._clear_orders()


def run_backtrader_on_frame(
    d: pd.DataFrame,
    strategy_id: str,
    market_state: pd.Series | None = None,
    commission_pct: float = BACKTEST_COMMISSION_PCT,
    slippage_bps: float = BACKTEST_SLIPPAGE_BPS,
    half_spread_bps: float = BACKTEST_HALF_SPREAD_BPS,
) -> dict:
    frame = prepare_audit_frame(d, strategy_id, market_state)
    cerebro = bt.Cerebro(cheat_on_open=True, stdstats=False)
    data = SwingAuditData(dataname=frame)
    cerebro.adddata(data)
    cerebro.addstrategy(BacktraderAuditStrategy, strategy_id=strategy_id)
    cerebro.broker.setcash(1_000_000.0)
    cerebro.broker.setcommission(commission=float(commission_pct) / 100.0, stocklike=True)
    impact = (float(slippage_bps) + float(half_spread_bps)) / 10_000.0
    cerebro.broker.set_slippage_perc(
        impact,
        slip_open=True,
        slip_limit=True,
        slip_match=True,
        slip_out=True,
    )
    strategies = cerebro.run()
    strat = strategies[0]
    return {
        'engine': 'Backtrader native broker audit',
        'strategy_id': strategy_id,
        'trades': strat.audit_trades,
        'gap_rejections': strat.gap_rejections,
        'ending_value': float(cerebro.broker.getvalue()),
        'assumptions': {
            'commission_pct_per_side': float(commission_pct),
            'slippage_bps': float(slippage_bps),
            'half_spread_bps': float(half_spread_bps),
            'entry': 'Backtrader cheat_on_open + native Market order',
            'exit': 'Backtrader native bracket Stop/Limit OCO; max-hold uses native Close order',
        },
    }


def _bucket(reason: str | None) -> str:
    text = str(reason or '')
    if '손절' in text:
        return 'stop'
    if '목표' in text:
        return 'target'
    return 'time'


def compare_engines(swing_trades: list[dict], backtrader_trades: list[dict]) -> dict:
    swing_by_entry = {str(t.get('entry_date')): t for t in swing_trades if t.get('entry_date')}
    bt_by_entry = {str(t.get('entry_date')): t for t in backtrader_trades if t.get('entry_date')}
    common = sorted(set(swing_by_entry) & set(bt_by_entry))
    outcome_matches = sum(_bucket(swing_by_entry[d].get('reason')) == _bucket(bt_by_entry[d].get('reason')) for d in common)
    swing_avg = float(np.mean([float(t.get('ret') or 0.0) for t in swing_trades])) if swing_trades else 0.0
    bt_avg = float(np.mean([float(t.get('ret') or 0.0) for t in backtrader_trades])) if backtrader_trades else 0.0
    match_rate = len(common) / max(1, len(set(swing_by_entry) | set(bt_by_entry)))
    outcome_agreement = outcome_matches / max(1, len(common))
    avg_return_delta_pp = (bt_avg - swing_avg) * 100.0

    if match_rate >= .95 and outcome_agreement >= .95 and abs(avg_return_delta_pp) <= .50:
        verdict = 'PASS'
    elif match_rate >= .80 and outcome_agreement >= .85:
        verdict = 'PASS_WITH_DIFFERENCES'
    else:
        verdict = 'REVIEW'

    return {
        'verdict': verdict,
        'swing_trade_count': len(swing_trades),
        'backtrader_trade_count': len(backtrader_trades),
        'matched_entry_dates': len(common),
        'entry_match_rate_pct': round(match_rate * 100, 1),
        'outcome_agreement_pct': round(outcome_agreement * 100, 1),
        'swing_avg_trade_pct': round(swing_avg * 100, 3),
        'backtrader_avg_trade_pct': round(bt_avg * 100, 3),
        'avg_return_delta_pp': round(avg_return_delta_pp, 3),
        'notes': [
            'Signal eligibility and BUY/TARGET/STOP plans are canonical shared inputs; execution is native Backtrader.',
            'Backtrader may improve a sell-limit fill on favorable target gaps, while Swing Lab V2 deliberately caps such fills at target.',
            'Max-hold exits use Backtrader Order.Close semantics, so time-exit prices can differ from Swing Lab V2 spread/slippage-adjusted close fills.',
        ],
    }


def run_backtrader_audit_on_frame(d: pd.DataFrame, strategy_id: str) -> dict:
    market_state = _historical_market_state(d.index)
    swing_trades = simulate(d, strategy_id, market_state=market_state)
    bt_result = run_backtrader_on_frame(d, strategy_id, market_state=market_state)
    comparison = compare_engines(swing_trades, bt_result['trades'])
    return {
        'strategy_id': strategy_id,
        'comparison': comparison,
        'swing_sample': swing_trades[:20],
        'backtrader_sample': bt_result['trades'][:20],
        'backtrader_gap_rejections': bt_result['gap_rejections'][:50],
        'backtrader_assumptions': bt_result['assumptions'],
    }


def run_backtrader_audit(symbol: str, strategy_id: str, period: str = '10y') -> dict:
    d = load_price_history(str(symbol).upper().strip(), period)
    result = run_backtrader_audit_on_frame(d, strategy_id)
    result['symbol'] = str(symbol).upper().strip()
    return result


def write_audit_report(symbols: list[str], strategy_ids: list[str], path='static/backtrader_audit.json') -> dict:
    rows = []
    for symbol in symbols:
        for strategy_id in strategy_ids:
            try:
                rows.append(run_backtrader_audit(symbol, strategy_id))
            except Exception as exc:
                rows.append({'symbol': symbol, 'strategy_id': strategy_id, 'error': str(exc)})
    payload = {'engine': 'Backtrader independent audit', 'rows': rows}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload
