import numpy as np
import pandas as pd

from strategy_engine import evaluate_strategies
from strategy_rules import MIN_STOP_ATR, STRATEGY_IDS, canonical_signal_frame, strict_signal_flags, trade_levels_from_row


def synthetic_prices(n=320):
    rng = np.random.default_rng(7)
    idx = pd.bdate_range('2025-01-01', periods=n)
    returns = rng.normal(0.0008, 0.012, n)
    close = 100 * np.exp(np.cumsum(returns))
    open_ = close * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + rng.uniform(0.001, 0.015, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0.001, 0.015, n))
    volume = rng.integers(1_000_000, 5_000_000, n)
    return pd.DataFrame(
        {'Open': open_, 'High': high, 'Low': low, 'Close': close, 'Volume': volume},
        index=idx,
    )


def main():
    d = synthetic_prices()
    for state in ('좋음', '중립', '조심'):
        flags = strict_signal_flags(d, state)
        live = {row['id']: bool(row['active']) for row in evaluate_strategies(d, state)['strategies']}
        assert flags == live, (state, flags, live)

    frame = canonical_signal_frame(d, '좋음')
    row = frame.iloc[-1]
    for strategy_id in STRATEGY_IDS:
        levels = trade_levels_from_row(row, strategy_id)
        assert levels['stop'] < levels['entry'] < levels['target'], (strategy_id, levels)
        assert (levels['entry'] - levels['stop']) / levels['atr'] >= MIN_STOP_ATR - 1e-9, (strategy_id, levels)

    print('strategy rule parity PASS')


if __name__ == '__main__':
    main()
