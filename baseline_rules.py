from __future__ import annotations

from copy import deepcopy

from config import (
    APP_VERSION,
    CORE_VERSION,
    PUBLIC_STRATEGIES,
    S_THRESHOLD,
    SCAN_CANDIDATE_LIMIT,
    BACKTEST_INITIAL_CAPITAL_KRW,
    BACKTEST_MAX_POSITIONS,
    BACKTEST_RISK_PER_TRADE_PCT,
    BACKTEST_MAX_POSITION_PCT,
    BACKTEST_COMMISSION_PCT,
    BACKTEST_SLIPPAGE_BPS,
    BACKTEST_HALF_SPREAD_BPS,
)
from strategy_rules import MIN_STOP_ATR, ENTRY_GAP_ATR, ENTRY_GAP_PCT

BASELINE_VERSION = 'baseline-v1.0-2026-08-13'
BASELINE_FROZEN_AT = '2026-08-13'
MIN_FORWARD_REVIEW_TRADES = 30
FULL_FORWARD_REVIEW_TRADES = 50

_BASELINE = {
    'baseline_version': BASELINE_VERSION,
    'frozen_at': BASELINE_FROZEN_AT,
    'app_version_at_freeze': APP_VERSION,
    'core_version_at_freeze': CORE_VERSION,
    'public_strategies': list(PUBLIC_STRATEGIES),
    's_threshold': S_THRESHOLD,
    'elite_policy': {
        'elite_min_score': 72.0,
        'min_flow_score': 42.0,
        'min_gross_risk_reward': 1.20,
        'market_state_excluded': ['조심'],
        'entry_viable_required': True,
        'min_stop_atr': MIN_STOP_ATR,
    },
    'execution': {
        'entry_gap_atr': ENTRY_GAP_ATR,
        'entry_gap_pct': ENTRY_GAP_PCT,
        'same_bar_policy': 'use 1m first-touch when available; unresolved same-1m/daily ambiguity falls back to stop',
        'commission_pct_per_side': BACKTEST_COMMISSION_PCT,
        'slippage_bps': BACKTEST_SLIPPAGE_BPS,
        'half_spread_bps': BACKTEST_HALF_SPREAD_BPS,
    },
    'portfolio': {
        'starting_cash_krw': BACKTEST_INITIAL_CAPITAL_KRW,
        'max_positions': BACKTEST_MAX_POSITIONS,
        'risk_per_trade_pct': BACKTEST_RISK_PER_TRADE_PCT,
        'max_position_pct': BACKTEST_MAX_POSITION_PCT,
        'slot_priority': 'ex_ante_gross_risk_reward',
    },
    'universe': {
        'candidate_limit': SCAN_CANDIDATE_LIMIT,
    },
    'forward_review': {
        'no_strategy_tuning_before_closed_trades': MIN_FORWARD_REVIEW_TRADES,
        'formal_review_target_closed_trades': FULL_FORWARD_REVIEW_TRADES,
    },
}


def baseline_snapshot() -> dict:
    return deepcopy(_BASELINE)
