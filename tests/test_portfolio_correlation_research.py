from __future__ import annotations

import pandas as pd

from portfolio_correlation_research import trailing_corr, max_positive_corr, simulate_correlation_portfolio
from portfolio_backtest import simulate_portfolio


def check(cond, message):
    if not cond:
        raise AssertionError(message)


def main():
    idx = pd.date_range('2026-01-01', periods=80, freq='B')
    base = pd.Series([.01 if i % 2 == 0 else -.008 for i in range(80)], index=idx)
    returns = {
        'AAA': base,
        'BBB': base * .95,
        'CCC': pd.Series([-.006 if i % 3 == 0 else .004 for i in range(80)], index=idx),
    }
    c = trailing_corr(returns, 'AAA', 'BBB', idx[-1].strftime('%Y-%m-%d'))
    check(c is not None and c > .99, 'same-pattern symbols should have high trailing correlation')
    corr, peer = max_positive_corr({'symbol':'AAA','signal_date':idx[-1].strftime('%Y-%m-%d')}, [{'symbol':'BBB'}], returns)
    check(corr is not None and corr > .99 and peer == 'BBB', 'max peer correlation must be identified')

    trades = [
        {'symbol':'AAA','strategy_id':'x','signal_date':'2026-03-20','entry_date':'2026-03-23','exit_date':'2026-03-27','ret':.03,'risk_pct':.03,'risk_reward':2.0},
        {'symbol':'BBB','strategy_id':'x','signal_date':'2026-03-20','entry_date':'2026-03-23','exit_date':'2026-03-27','ret':-.04,'risk_pct':.03,'risk_reward':1.9},
        {'symbol':'CCC','strategy_id':'x','signal_date':'2026-03-20','entry_date':'2026-03-23','exit_date':'2026-03-27','ret':.02,'risk_pct':.03,'risk_reward':1.8},
    ]
    baseline = simulate_correlation_portfolio(trades, returns, 'baseline_rr')
    existing = simulate_portfolio(trades)
    check(baseline['return_pct'] == existing['return_pct'], 'research baseline must reproduce existing portfolio return')
    check(baseline['accepted_trades'] == existing['accepted_trades'], 'research baseline must reproduce existing accepted count')

    hard = simulate_correlation_portfolio(trades, returns, 'hard_corr_0_75')
    check(hard['rejected_correlation'] >= 1, 'hard correlation policy should reject the highly correlated second trade')
    check(hard['accepted_trades'] < baseline['accepted_trades'], 'hard correlation policy must reduce accepted trades in synthetic clash')

    print('portfolio correlation research PASS')


if __name__ == '__main__':
    main()
