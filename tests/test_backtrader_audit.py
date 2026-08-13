from pathlib import Path
import sys

import backtrader as bt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtrader_audit import BacktraderAuditStrategy, SwingAuditData, compare_engines


def _run_prepared(rows):
    frame = pd.DataFrame(rows)
    frame.index = pd.bdate_range('2026-01-05', periods=len(frame))
    cerebro = bt.Cerebro(cheat_on_open=True, stdstats=False)
    cerebro.adddata(SwingAuditData(dataname=frame))
    cerebro.addstrategy(BacktraderAuditStrategy, strategy_id='audit_fixture')
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.001, stocklike=True)
    cerebro.broker.set_slippage_perc(0.00075, slip_open=True, slip_limit=True, slip_match=True, slip_out=True)
    result = cerebro.run()[0]
    return result


def _base_row(open_, high, low, close, signal=0, buy_low=99, buy_high=101, target=105, stop=95, max_hold=5, gap_guard=1):
    return {
        'open': open_, 'high': high, 'low': low, 'close': close,
        'volume': 1_000_000, 'openinterest': 0,
        'signal': signal, 'buy_low': buy_low, 'buy_high': buy_high,
        'target': target, 'stop': stop, 'max_hold': max_hold, 'gap_guard': gap_guard,
    }


def test_native_bracket_target_execution():
    strat = _run_prepared([
        _base_row(100, 101, 99, 100, signal=1),
        _base_row(100, 106, 99, 105),
        _base_row(105, 106, 104, 105),
        _base_row(105, 106, 104, 105),
    ])
    assert len(strat.audit_trades) == 1, strat.audit_trades
    trade = strat.audit_trades[0]
    assert trade['reason'] == '목표달성', trade
    assert trade['entry_date'] == '2026-01-06', trade
    # Native Backtrader applies configured broker slippage to this limit fill,
    # so audit the broker behavior instead of forcing Swing Lab's target cap.
    assert abs(trade['exit_fill'] / 105.0 - 1.0) < 0.001, trade
    assert trade['exit_fill'] > trade['stop'], trade


def test_next_open_gap_rejection():
    strat = _run_prepared([
        _base_row(100, 101, 99, 100, signal=1),
        _base_row(110, 112, 108, 111),
        _base_row(111, 112, 110, 111),
    ])
    assert not strat.audit_trades
    assert len(strat.gap_rejections) == 1
    assert strat.gap_rejections[0]['open'] == 110


def test_comparison_verdict():
    swing = [
        {'entry_date': '2026-01-06', 'reason': '목표달성', 'ret': 0.04},
        {'entry_date': '2026-01-10', 'reason': '손절', 'ret': -0.03},
    ]
    bt_trades = [
        {'entry_date': '2026-01-06', 'reason': '목표달성', 'ret': 0.041},
        {'entry_date': '2026-01-10', 'reason': '손절', 'ret': -0.029},
    ]
    comparison = compare_engines(swing, bt_trades)
    assert comparison['verdict'] == 'PASS', comparison
    assert comparison['entry_match_rate_pct'] == 100.0
    assert comparison['outcome_agreement_pct'] == 100.0


def main():
    test_native_bracket_target_execution()
    test_next_open_gap_rejection()
    test_comparison_verdict()
    print('backtrader audit PASS')


if __name__ == '__main__':
    main()
