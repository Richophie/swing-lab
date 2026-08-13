from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from backtest_engine import _historical_market_state, simulate
from backtrader_audit import compare_engines, run_backtrader_on_frame
from market_data import load_price_history


SYMBOLS = [
    'AAPL', 'MSFT', 'AMZN', 'META', 'NVDA', 'GOOGL', 'JPM', 'XOM', 'JNJ', 'PG',
    'HD', 'CAT', 'AMD', 'QCOM', 'CRM', 'DIS', 'NKE', 'F', 'PLD', 'PYPL',
]
STRATEGIES = [
    'confirmed_pullback',
    'rsi2_trend_reversion',
    'momentum_pullback',
]
STRATEGY_NAMES = {
    'confirmed_pullback': '확인형 눌림반등',
    'rsi2_trend_reversion': 'RSI2 추세내 과매도',
    'momentum_pullback': '모멘텀 눌림 지속',
}
OUT = Path('artifacts/backtrader_real_audit.json')


def mean_or_none(values):
    values = [float(v) for v in values if v is not None]
    return None if not values else float(np.mean(values))


def run_matrix():
    rows = []
    by_strategy = defaultdict(list)

    for symbol in SYMBOLS:
        try:
            d = load_price_history(symbol, '10y').dropna()
            market_state = _historical_market_state(d.index)
        except Exception as exc:
            for strategy_id in STRATEGIES:
                row = {
                    'symbol': symbol,
                    'strategy_id': strategy_id,
                    'strategy_name': STRATEGY_NAMES[strategy_id],
                    'error': f'data load failed: {exc}',
                }
                rows.append(row)
                by_strategy[strategy_id].append(row)
            continue

        for strategy_id in STRATEGIES:
            try:
                swing_trades = simulate(
                    d,
                    strategy_id,
                    market_state=market_state,
                    symbol=symbol,
                )
                bt_result = run_backtrader_on_frame(
                    d,
                    strategy_id,
                    market_state=market_state,
                )
                comparison = compare_engines(swing_trades, bt_result['trades'])
                row = {
                    'symbol': symbol,
                    'strategy_id': strategy_id,
                    'strategy_name': STRATEGY_NAMES[strategy_id],
                    **comparison,
                    'backtrader_gap_rejections': len(bt_result.get('gap_rejections') or []),
                }
            except Exception as exc:
                row = {
                    'symbol': symbol,
                    'strategy_id': strategy_id,
                    'strategy_name': STRATEGY_NAMES[strategy_id],
                    'error': str(exc),
                }
            rows.append(row)
            by_strategy[strategy_id].append(row)
            if 'error' in row:
                print(f"{symbol:5s} {STRATEGY_NAMES[strategy_id]:18s} ERROR {row['error']}")
            else:
                print(
                    f"{symbol:5s} {STRATEGY_NAMES[strategy_id]:18s} "
                    f"{row['verdict']:21s} "
                    f"trades {row['swing_trade_count']:3d}/{row['backtrader_trade_count']:3d} "
                    f"entry {row['entry_match_rate_pct']:5.1f}% "
                    f"outcome {row['outcome_agreement_pct']:5.1f}% "
                    f"delta {row['avg_return_delta_pp']:+.3f}pp"
                )

    strategy_summaries = []
    for strategy_id in STRATEGIES:
        valid = [r for r in by_strategy[strategy_id] if 'error' not in r]
        verdict_counts = defaultdict(int)
        for r in valid:
            verdict_counts[r['verdict']] += 1
        total_swing = sum(int(r['swing_trade_count']) for r in valid)
        total_bt = sum(int(r['backtrader_trade_count']) for r in valid)
        matched = sum(int(r['matched_entry_dates']) for r in valid)
        union = sum(
            max(
                int(r['swing_trade_count']) + int(r['backtrader_trade_count']) - int(r['matched_entry_dates']),
                0,
            )
            for r in valid
        )
        weighted_outcome_n = sum(int(r['matched_entry_dates']) for r in valid)
        weighted_outcome_matches = sum(
            int(r['matched_entry_dates']) * float(r['outcome_agreement_pct']) / 100.0
            for r in valid
        )
        strategy_summaries.append(
            {
                'strategy_id': strategy_id,
                'strategy_name': STRATEGY_NAMES[strategy_id],
                'symbols_ok': len(valid),
                'symbols_error': len(by_strategy[strategy_id]) - len(valid),
                'verdict_counts': dict(verdict_counts),
                'swing_trade_count': total_swing,
                'backtrader_trade_count': total_bt,
                'entry_match_rate_pct': round(matched / union * 100.0, 1) if union else 100.0,
                'outcome_agreement_pct': round(weighted_outcome_matches / weighted_outcome_n * 100.0, 1) if weighted_outcome_n else 100.0,
                'mean_abs_avg_return_delta_pp': round(mean_or_none([abs(r['avg_return_delta_pp']) for r in valid]) or 0.0, 3),
            }
        )

    valid_rows = [r for r in rows if 'error' not in r]
    verdict_counts = defaultdict(int)
    for r in valid_rows:
        verdict_counts[r['verdict']] += 1

    payload = {
        'engine': 'Swing Lab V2 vs Backtrader real-data audit',
        'period': '10y',
        'symbols': SYMBOLS,
        'strategies': STRATEGIES,
        'matrix_size': len(SYMBOLS) * len(STRATEGIES),
        'rows_ok': len(valid_rows),
        'rows_error': len(rows) - len(valid_rows),
        'verdict_counts': dict(verdict_counts),
        'strategy_summaries': strategy_summaries,
        'rows': rows,
        'scope_note': 'This checks execution-engine reproducibility on a fixed current-name sample; it is not a historical-universe profitability proof.',
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    print('\n=== REAL DATA AUDIT SUMMARY ===')
    print(json.dumps({
        'rows_ok': payload['rows_ok'],
        'rows_error': payload['rows_error'],
        'verdict_counts': payload['verdict_counts'],
        'strategy_summaries': payload['strategy_summaries'],
    }, ensure_ascii=False, indent=2))
    return payload


if __name__ == '__main__':
    run_matrix()
