from __future__ import annotations

from config import BACKTEST_COMMISSION_PCT, BACKTEST_HALF_SPREAD_BPS, BACKTEST_SLIPPAGE_BPS
from backtest_engine import market_buy_fill, market_sell_fill


def plan_execution_quality(
    plan: dict,
    *,
    commission_pct: float = BACKTEST_COMMISSION_PCT,
    slippage_bps: float = BACKTEST_SLIPPAGE_BPS,
    half_spread_bps: float = BACKTEST_HALF_SPREAD_BPS,
) -> dict:
    """Estimate gross and cost-aware risk/reward from signal-day trade levels.

    This is deliberately pre-trade: it uses only the planned BUY midpoint, TARGET,
    STOP, and configured execution costs. It never uses a future fill or outcome.

    Cost convention matches Swing Lab Backtest V2:
    - entry: market-like buy, paying half-spread + slippage, then commission
    - target: limit-style target credited at TARGET, then sell commission
    - stop: stop-market style sell at STOP less half-spread + slippage, then commission
    """
    low = float(plan.get('buy_low', plan.get('entry_low')))
    high = float(plan.get('buy_high', plan.get('entry_high')))
    target = float(plan['target'])
    stop = float(plan['stop'])
    if low > high:
        low, high = high, low
    entry_ref = float(plan.get('entry') or ((low + high) / 2.0))
    if not stop < entry_ref < target:
        raise ValueError('STOP < BUY < TARGET 구조가 아닙니다')

    commission = max(0.0, float(commission_pct)) / 100.0
    entry_fill = market_buy_fill(entry_ref, slippage_bps, half_spread_bps)
    stop_fill = market_sell_fill(stop, slippage_bps, half_spread_bps)

    entry_cost = entry_fill * (1.0 + commission)
    target_proceeds = target * (1.0 - commission)
    stop_proceeds = stop_fill * (1.0 - commission)

    gross_reward = target - entry_ref
    gross_risk = entry_ref - stop
    net_reward = target_proceeds - entry_cost
    net_risk = entry_cost - stop_proceeds

    gross_rr = gross_reward / gross_risk if gross_risk > 0 else 0.0
    net_rr = net_reward / net_risk if net_risk > 0 else 0.0
    return {
        'entry_reference_usd': round(entry_ref, 6),
        'estimated_entry_fill_usd': round(entry_fill, 6),
        'estimated_target_proceeds_per_share': round(target_proceeds, 6),
        'estimated_stop_fill_usd': round(stop_fill, 6),
        'estimated_stop_proceeds_per_share': round(stop_proceeds, 6),
        'gross_risk_reward': round(gross_rr, 4),
        'net_risk_reward': round(net_rr, 4),
        'net_target_return_pct': round((target_proceeds / entry_cost - 1.0) * 100.0, 4),
        'net_stop_return_pct': round((stop_proceeds / entry_cost - 1.0) * 100.0, 4),
        'cost_rr_drag': round(gross_rr - net_rr, 4),
        'commission_pct_per_side': float(commission_pct),
        'slippage_bps': float(slippage_bps),
        'half_spread_bps': float(half_spread_bps),
    }
