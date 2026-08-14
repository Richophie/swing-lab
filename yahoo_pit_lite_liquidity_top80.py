from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import argparse
import json
from pathlib import Path
from statistics import mean, median

import pandas as pd

import portfolio_walkforward_research as wf
import strategy_optimizer_v2 as opt
import yahoo_pit_lite_research as pit

OUT = Path('static/yahoo_pit_lite_top80_results.json')
TOP_N = 80
ADV_LOOKBACK = 20


def historical_liquidity_top_n(
    frames: dict[str, pd.DataFrame],
    membership: pit.MembershipIndex,
    signal_days: set[date],
    *,
    top_n: int = TOP_N,
    lookback: int = ADV_LOOKBACK,
) -> tuple[dict[date, set[str]], dict]:
    """Return point-in-time top-N members by trailing average dollar volume.

    Only OHLCV through each signal day is used. The cross-section is also
    restricted to historical index members on that exact day. Missing Yahoo
    histories simply reduce the observable cross-section; they are reported as
    a limitation rather than silently replaced with current constituents.
    """
    wanted = set(signal_days)
    by_day: dict[date, list[tuple[float, str]]] = defaultdict(list)

    for ticker, frame in frames.items():
        if frame is None or frame.empty:
            continue
        close = pd.to_numeric(frame['Close'], errors='coerce')
        volume = pd.to_numeric(frame['Volume'], errors='coerce')
        adv = (close * volume).rolling(lookback, min_periods=lookback).mean()
        for ts, value in adv.dropna().items():
            day = pd.Timestamp(ts).date()
            if day not in wanted or value <= 0:
                continue
            if membership.contains(ticker, day):
                by_day[day].append((float(value), ticker))

    top_by_day: dict[date, set[str]] = {}
    eligible_counts = []
    for day in sorted(wanted):
        ranked = sorted(by_day.get(day, ()), key=lambda x: (-x[0], x[1]))
        eligible_counts.append(len(ranked))
        top_by_day[day] = {ticker for _, ticker in ranked[:top_n]}

    enough = [x for x in eligible_counts if x >= top_n]
    diagnostics = {
        'signal_days': len(wanted),
        'days_with_any_liquidity_cross_section': sum(x > 0 for x in eligible_counts),
        'days_with_at_least_top_n_observable_members': len(enough),
        'top_n': int(top_n),
        'adv_lookback_sessions': int(lookback),
        'min_observable_members': min(eligible_counts) if eligible_counts else 0,
        'median_observable_members': round(float(median(eligible_counts)), 1) if eligible_counts else 0.0,
        'mean_observable_members': round(float(mean(eligible_counts)), 1) if eligible_counts else 0.0,
        'max_observable_members': max(eligible_counts) if eligible_counts else 0,
    }
    return top_by_day, diagnostics


def liquidity_filter(candidates: list[dict], top_by_day: dict[date, set[str]]) -> list[dict]:
    out = []
    for candidate in candidates:
        try:
            day = opt.parse_day(candidate['signal_date'])
        except Exception:
            continue
        if str(candidate.get('symbol') or '') in top_by_day.get(day, set()):
            out.append(candidate)
    return out


def compare_all_vs_top80(all_folds: list[dict], top80_folds: list[dict]) -> dict:
    full = pit._summary(all_folds)
    liquid = pit._summary(top80_folds)
    per_fold = []
    for a, b in zip(all_folds, top80_folds):
        per_fold.append({
            'fold': a['fold'],
            'pit_lite_all_return_pct': a['test']['return_pct'],
            'pit_lite_top80_return_pct': b['test']['return_pct'],
            'delta_pct': round(b['test']['return_pct'] - a['test']['return_pct'], 2),
            'pit_lite_all_mdd_pct': a['test']['mdd_pct'],
            'pit_lite_top80_mdd_pct': b['test']['mdd_pct'],
        })
    return {
        'pit_lite_all': full,
        'pit_lite_top80': liquid,
        'delta_stitched_return_pct': round(liquid['stitched_test_return_pct'] - full['stitched_test_return_pct'], 2),
        'delta_worst_mdd_pct': round(liquid['worst_mdd_pct'] - full['worst_mdd_pct'], 2),
        'top80_better_folds': sum(x['delta_pct'] > .01 for x in per_fold),
        'top80_worse_folds': sum(x['delta_pct'] < -.01 for x in per_fold),
        'per_fold': per_fold,
    }


def run(max_symbols: int | None = None) -> dict:
    now = datetime.now(timezone.utc)
    snapshots = pit.fetch_snapshots()
    membership = pit.MembershipIndex(snapshots)
    universe = membership.union(pit.RESEARCH_START, pit.RESEARCH_END)
    latest_members = pit.snapshot_on(snapshots[-1]['date'], snapshots)

    tickers = sorted(universe)
    if max_symbols:
        old = sorted(universe - latest_members)
        cur = sorted(universe & latest_members)
        tickers = (old + cur)[:max_symbols]
        universe = set(tickers)
        latest_members = latest_members & universe

    frames, download_errors = pit.download_prices(tickers)
    market_state = pit.benchmark_market_state()
    all_candidates: list[dict] = []
    symbol_errors = []
    for n, ticker in enumerate(tickers, 1):
        frame = frames.get(ticker)
        if frame is None or len(frame) < pit.MIN_ROWS:
            continue
        try:
            rows = pit.membership_filter(pit.candidate_rows(frame, ticker, market_state), membership)
            all_candidates.extend(rows)
        except Exception as exc:
            symbol_errors.append({'symbol': ticker, 'error': str(exc)})
        if n % 50 == 0:
            print('processed', n, 'of', len(tickers), 'candidates', len(all_candidates))

    all_candidates.sort(key=lambda x: (x['entry_date'], x['symbol'], x['strategy_id']))
    signal_days = {opt.parse_day(c['signal_date']) for c in all_candidates}
    top_by_day, liquidity_diag = historical_liquidity_top_n(frames, membership, signal_days)
    top80_candidates = liquidity_filter(all_candidates, top_by_day)

    pit.prepare_candidates(all_candidates)
    pit.prepare_candidates(top80_candidates)

    folds = wf.folds_for(pit.RESEARCH_START, pit.RESEARCH_END)
    all_folds = pit._fold_metrics(all_candidates, folds)
    top80_folds = pit._fold_metrics(top80_candidates, folds)
    comparison = compare_all_vs_top80(all_folds, top80_folds)
    coverage = pit.coverage_summary(membership, universe, latest_members, frames)

    noncurrent = universe - latest_members
    payload = {
        'version': 1,
        'ready': True,
        'generated_at': now.isoformat(timespec='seconds'),
        'status': 'PIT_LITE_FREE_YAHOO_HISTORICAL_LIQUIDITY_TOP80_DIAGNOSTIC',
        'promotion_status': 'DIAGNOSTIC_ONLY_NOT_SURVIVORSHIP_FREE',
        'research_window': {'start': str(pit.RESEARCH_START), 'end': str(pit.RESEARCH_END)},
        'family': list(pit.STRATEGIES),
        'portfolio': {'risk_budget_pct': .75, 'max_positions': 10, 'exit': 'natural_strategy_exit'},
        'liquidity_gate': {
            'metric': 'trailing average dollar volume = Close * Volume',
            'lookback_sessions': ADV_LOOKBACK,
            'rank': f'top {TOP_N} historical S&P members observable in Yahoo on each signal day',
            'timing': 'signal-day close only; no future volume or future membership information',
        },
        'coverage': coverage,
        'liquidity_diagnostics': liquidity_diag,
        'candidate_counts': {
            'pit_lite_all': len(all_candidates),
            'pit_lite_top80': len(top80_candidates),
            'retained_pct': round(len(top80_candidates) / len(all_candidates) * 100.0, 2) if all_candidates else 0.0,
            'pit_lite_all_symbols': len({c['symbol'] for c in all_candidates}),
            'pit_lite_top80_symbols': len({c['symbol'] for c in top80_candidates}),
            'historical_noncurrent_all': sum(c.get('symbol') in noncurrent for c in all_candidates),
            'historical_noncurrent_top80': sum(c.get('symbol') in noncurrent for c in top80_candidates),
        },
        'comparison': comparison,
        'folds': {'pit_lite_all': all_folds, 'pit_lite_top80': top80_folds},
        'download_error_batches': download_errors,
        'symbol_errors': symbol_errors,
        'method': {
            'membership': 'historical S&P snapshot membership is required on both signal day and next-open entry day',
            'prices': 'free Yahoo/yfinance daily OHLCV only',
            'liquidity': 'rank trailing 20-session average dollar volume cross-sectionally on each signal day and keep top80',
            'selection': 'after the liquidity gate, within-strategy top50 quality threshold and hybrid_50 priority are recomputed on each fold TRAIN only',
            'validation': '4y TRAIN -> next complete calendar-year TEST, 2021-2025',
        },
        'limitations': [
            'This is PIT-Lite, not complete point-in-time proof: Yahoo still misses many former/delisted histories.',
            'The daily Top80 rank is therefore among historical members with observable Yahoo data, not a guaranteed complete historical cross-section.',
            'Missing historical securities are never replaced with current constituents and are never assigned zero return.',
            'Historical ticker labels are not permanent security IDs; ticker reuse and corporate actions can remain ambiguous.',
            'Average dollar volume uses Yahoo Close * Volume and is a liquidity proxy, not exchange-grade historical dollar-volume data.',
            'Top80 is one coarse pre-registered sensitivity choice chosen to approximate the current project universe size; no Top-N grid is searched.',
            '2021-2025 is development stress evidence and cannot auto-promote a production or Forward rule.',
            'No result changes the main picker, Frozen Forward V1-V4, PaperBroker, or live-order path.',
        ],
        'production_main_picker_mutated': False,
        'forward_challengers_mutated': False,
        'live_trading_mutated': False,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'status': payload['status'],
        'coverage_pct': coverage['historical_noncurrent_coverage_pct'],
        'liquidity_diagnostics': liquidity_diag,
        'candidate_counts': payload['candidate_counts'],
        'pit_lite_all': comparison['pit_lite_all'],
        'pit_lite_top80': comparison['pit_lite_top80'],
        'delta_stitched_return_pct': comparison['delta_stitched_return_pct'],
    }, ensure_ascii=False, indent=2))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--max-symbols', type=int, default=None)
    args = parser.parse_args()
    run(max_symbols=args.max_symbols)


if __name__ == '__main__':
    main()
