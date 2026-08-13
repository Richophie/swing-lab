from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest_engine import exit_fill_for_bar, market_buy_fill, market_sell_fill, net_trade_return
from portfolio_backtest import simulate_portfolio


def test_execution_costs():
    buy = market_buy_fill(100.0, 5.0, 2.5)
    sell = market_sell_fill(100.0, 5.0, 2.5)
    assert buy > 100.0
    assert sell < 100.0
    assert net_trade_return(buy, sell, 0.001) < 0.0


def test_gap_and_intrabar_exit_rules():
    gap_stop = exit_fill_for_bar(90, 110, 85, target=105, stop=95, slippage_bps=5, half_spread_bps=2.5)
    assert gap_stop is not None
    assert gap_stop[1] == '갭손절'
    assert gap_stop[0] < 90

    gap_target = exit_fill_for_bar(110, 112, 100, target=105, stop=95, slippage_bps=5, half_spread_bps=2.5)
    assert gap_target is not None
    assert gap_target[1] == '갭목표'
    assert gap_target[0] == 105

    both = exit_fill_for_bar(100, 110, 90, target=105, stop=95, slippage_bps=5, half_spread_bps=2.5)
    assert both is not None
    assert both[1] == '손절'
    assert both[0] < 95


def test_portfolio_capacity_and_risk_sizing():
    trades = [
        {
            'symbol': 'AAA', 'strategy_id': 'rsi2_trend_reversion',
            'entry_date': '2026-01-05', 'exit_date': '2026-01-07',
            'risk_pct': 0.05, 'risk_reward': 2.0, 'ret': 0.10, 'reason': '목표달성',
        },
        {
            'symbol': 'BBB', 'strategy_id': 'rsi2_trend_reversion',
            'entry_date': '2026-01-05', 'exit_date': '2026-01-08',
            'risk_pct': 0.05, 'risk_reward': 1.8, 'ret': -0.05, 'reason': '손절',
        },
        {
            'symbol': 'CCC', 'strategy_id': 'rsi2_trend_reversion',
            'entry_date': '2026-01-05', 'exit_date': '2026-01-09',
            'risk_pct': 0.05, 'risk_reward': 1.2, 'ret': 0.20, 'reason': '목표달성',
        },
    ]
    result = simulate_portfolio(
        trades,
        initial_capital_krw=3_000_000,
        max_positions=2,
        risk_per_trade_pct=1.0,
        max_position_pct=40.0,
    )
    assert result['accepted_trades'] == 2
    assert result['rejected_capacity'] == 1
    assert result['max_concurrent_positions'] == 2
    assert [t['symbol'] for t in result['trades']] == ['AAA', 'BBB']
    # 1% account risk / 5% stop distance = 20% notional = 600,000 KRW.
    assert result['trades'][0]['notional_krw'] == 600000
    assert result['ending_capital_krw'] == 3_030_000


def test_same_day_exit_cash_is_not_reused_for_open():
    trades = [
        {
            'symbol': 'AAA', 'strategy_id': 'confirmed_pullback',
            'entry_date': '2026-01-05', 'exit_date': '2026-01-06',
            'risk_pct': 0.02, 'risk_reward': 2.0, 'ret': 0.02, 'reason': '목표달성',
        },
        {
            'symbol': 'BBB', 'strategy_id': 'confirmed_pullback',
            'entry_date': '2026-01-06', 'exit_date': '2026-01-07',
            'risk_pct': 0.02, 'risk_reward': 2.0, 'ret': 0.02, 'reason': '목표달성',
        },
    ]
    result = simulate_portfolio(
        trades,
        initial_capital_krw=3_000_000,
        max_positions=1,
        risk_per_trade_pct=1.0,
        max_position_pct=100.0,
    )
    assert result['accepted_trades'] == 1
    assert result['rejected_capacity'] == 1


def main():
    test_execution_costs()
    test_gap_and_intrabar_exit_rules()
    test_portfolio_capacity_and_risk_sizing()
    test_same_day_exit_cash_is_not_reused_for_open()
    print('backtest v2 PASS')


if __name__ == '__main__':
    main()
