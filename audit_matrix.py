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


def normalize_zero_trade_comparison(comparison: dict) -> dict:
    """Zero vs zero means there is nothing to compare, not an engine disagreement."""
    out = dict(comparison)
    if int(out.get('swing_trade_count') or 0) == 0 and int(out.get('backtrader_trade_count') or 0) == 0:
        out['verdict'] = 'NO_TRADES'
        out['entry_match_rate_pct'] = 100.0
        out['outcome_agreement_pct'] = 100.0
    return out


def outcome_bucket(reason):
    text = str(reason or '')
    if '손절' in text:
        return 'stop'
    if '목표' in text:
        return 'target'
    return 'time'


def trade_diagnostics(swing_trades: list[dict], backtrader_trades: list[dict]) -> dict:
    swing = {str(t.get('entry_date')): t for t in swing_trades if t.get('entry_date')}
    bt = {str(t.get('entry_date')): t for t in backtrader_trades if t.get('entry_date')}
    swing_only = sorted(set(swing) - set(bt))
    backtrader_only = sorted(set(bt) - set(swing))
    outcome_mismatch = []
    for date in sorted(set(swing) & set(bt)):
        if outcome_bucket(swing[date].get('reason')) != outcome_bucket(bt[date].get('reason')):
            outcome_mismatch.append({
                'entry_date': date,
                'swing_reason': swing[date].get('reason'),
                'backtrader_reason': bt[date].get('reason'),
                'swing_exit_date': swing[date].get('exit_date'),
                'backtrader_exit_date': bt[date].get('exit_date'),
                'swing_ret_pct': round(float(swing[date].get('ret') or 0.0) * 100.0, 3),
                'backtrader_ret_pct': round(float(bt[date].get('ret') or 0.0) * 100.0, 3),
            })
    return {
        'swing_only_entry_dates': swing_only,
        'backtrader_only_entry_dates': backtrader_only,
        'outcome_mismatches': outcome_mismatch,
    }


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
                comparison = normalize_zero_trade_comparison(compare_engines(swing_trades, bt_result['trades']))
                diagnostics = trade_diagnostics(swing_trades, bt_result['trades'])
                row = {
                    'symbol': symbol,
                    'strategy_id': strategy_id,
                    'strategy_name': STRATEGY_NAMES[strategy_id],
                    **comparison,
                    **diagnostics,
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
                if row['swing_only_entry_dates'] or row['backtrader_only_entry_dates'] or row['outcome_mismatches']:
                    print('  DIFF', json.dumps({
                        'swing_only': row['swing_only_entry_dates'],
                        'backtrader_only': row['backtrader_only_entry_dates'],
                        'outcomes': row['outcome_mismatches'],
                    }, ensure_ascii=False))

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
                'mean_abs_avg_return_delta_pp': round(mean_or_none([abs(r['avg_return_delta_pp']) for r in valid if r['verdict'] != 'NO_TRADES']) or 0.0, 3),
                'swing_only_entries': sum(len(r.get('swing_only_entry_dates') or []) for r in valid),
                'backtrader_only_entries': sum(len(r.get('backtrader_only_entry_dates') or []) for r in valid),
                'outcome_mismatch_count': sum(len(r.get('outcome_mismatches') or []) for r in valid),
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
