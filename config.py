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
