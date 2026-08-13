APP_VERSION = "16.5"
CORE_VERSION = "4.4"
S_THRESHOLD = 85.0
ELITE_MAX = 9999
PUBLIC_STRATEGIES = (
    "confirmed_pullback",
    "rsi2_trend_reversion",
    "momentum_pullback",
)
EXPERIMENTAL_STRATEGIES = ("volatility_breakout",)

# Main scan intentionally avoids the full US micro/small-cap universe.
SCAN_CANDIDATE_LIMIT = 500
MAIN_MIN_MARKET_CAP = 2_000_000_000
MAIN_MIN_AVG_DAILY_VOLUME = 500_000
MAIN_MIN_PRICE = 5

# Backtest V2 execution assumptions. These are deliberately conservative and
# centralized so scanner/backtest reports cannot silently use different costs.
BACKTEST_COMMISSION_PCT = 0.10
BACKTEST_SLIPPAGE_BPS = 5.0
BACKTEST_HALF_SPREAD_BPS = 2.5

# Portfolio simulator defaults. Capital is modeled as KRW notional exposure;
# returns are dimensionless, so no historical FX assumption is required here.
# Actual USD share rounding belongs to the future paper/live broker layer.
BACKTEST_INITIAL_CAPITAL_KRW = 3_000_000
BACKTEST_MAX_POSITIONS = 3
BACKTEST_RISK_PER_TRADE_PCT = 1.0
BACKTEST_MAX_POSITION_PCT = 40.0
