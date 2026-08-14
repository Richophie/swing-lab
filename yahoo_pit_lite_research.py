from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import argparse
import json
import math
from pathlib import Path
from statistics import mean, median

import numpy as np
import pandas as pd
import yfinance as yf

import capital_velocity_research as velocity
import portfolio_candidate_capital_v2 as v2
import portfolio_walkforward_research as wf
import strategy_optimizer_runner as mtm
import strategy_optimizer_v2 as opt
import strategy_selection_research as selection
from config import BACKTEST_COMMISSION_PCT, BACKTEST_HALF_SPREAD_BPS, BACKTEST_SLIPPAGE_BPS, S_THRESHOLD
from execution_quality import plan_execution_quality
from market_data import indicators
from replay_pool_v2 import DONCHIAN55_ID, EXPERIMENT_NAMES, SMA_ID, _breakout_candidates, _path, _sma_candidates
from sp500_pit_diagnostic import fetch_snapshots, snapshot_on
from structural_stop_research import STRATEGY_NAMES, historical_features, plan_from_row, selection_pass
from strategy_rules import canonical_signal_frame

OUT = Path('static/yahoo_pit_lite_results.json')
RESEARCH_START = date(2017, 1, 1)
RESEARCH_END = date(2025, 12, 31)  # use only complete calendar TEST years
DOWNLOAD_START = '2016-01-01'       # >=205-session warmup before 2017
DOWNLOAD_END = '2026-03-15'         # enough forward path for late-2025 signals
FAMILY_ID = 'confirmed_sma_donchian'
STRATEGIES = ('confirmed_pullback', SMA_ID, DONCHIAN55_ID)
BATCH = 45
MIN_ROWS = 205
NEAR_LAST_SEEN_DAYS = 10
POLICY = {'label': '0.75% / max10', 'risk_pct': .75, 'capacity': 10, 'cash_floor_pct': 0.0}


class MembershipIndex:
    def __init__(self, snapshots: list[dict]):
        usable = [row for row in snapshots if row['date'] <= RESEARCH_END]
        if not usable:
            raise ValueError('no historical snapshots through research end')
        self.rows = usable
        self.days = [row['date'] for row in usable]
        self.members = [set(row['members']) for row in usable]

    def on(self, day: date) -> set[str]:
        i = bisect_right(self.days, day) - 1
        return set() if i < 0 else self.members[i]

    def contains(self, ticker: str, day: date) -> bool:
        i = bisect_right(self.days, day) - 1
        return i >= 0 and ticker in self.members[i]

    def union(self, start: date, end: date) -> set[str]:
        out: set[str] = set()
        for row in self.rows:
            if row['date'] > end:
                break
            if row['date'] >= start:
                out.update(row['members'])
        # include the snapshot immediately before start, because membership stays
        # in force until the next snapshot.
        out.update(self.on(start))
        return out

    def last_seen(self, ticker: str, end: date) -> date | None:
        for row in reversed(self.rows):
            if row['date'] <= end and ticker in row['members']:
                return row['date']
        return None


def _clean_download_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    out = frame.copy()
    needed = ['Open', 'High', 'Low', 'Close', 'Volume']
    if not all(c in out.columns for c in needed):
        return pd.DataFrame()
    out = out[needed].apply(pd.to_numeric, errors='coerce')
    out.index = pd.to_datetime(out.index)
    if getattr(out.index, 'tz', None) is not None:
        out.index = out.index.tz_localize(None)
    out = out[~out.index.duplicated(keep='last')].sort_index()
    out = out.dropna(subset=['Open', 'High', 'Low', 'Close'])
    out = out[out['Close'] > 0]
    return out


def _extract_symbol(raw: pd.DataFrame, ticker: str, batch_size: int) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            lvl0 = list(raw.columns.get_level_values(0))
            lvllast = list(raw.columns.get_level_values(-1))
            if ticker in lvl0:
                return _clean_download_frame(raw[ticker])
            if ticker in lvllast:
                return _clean_download_frame(raw.xs(ticker, level=-1, axis=1))
        if batch_size == 1:
            return _clean_download_frame(raw)
    except Exception:
        return pd.DataFrame()
    return pd.DataFrame()


def download_prices(tickers: list[str]) -> tuple[dict[str, pd.DataFrame], list[dict]]:
    frames: dict[str, pd.DataFrame] = {}
    errors: list[dict] = []
    for offset in range(0, len(tickers), BATCH):
        batch = tickers[offset:offset + BATCH]
        try:
            raw = yf.download(
                ' '.join(batch), start=DOWNLOAD_START, end=DOWNLOAD_END,
                interval='1d', auto_adjust=False, group_by='ticker',
                threads=True, progress=False, timeout=30,
            )
        except Exception as exc:
            errors.append({'batch_start': offset, 'symbols': batch, 'error': str(exc)})
            raw = pd.DataFrame()
        for ticker in batch:
            frame = _extract_symbol(raw, ticker, len(batch))
            if len(frame) >= MIN_ROWS:
                frames[ticker] = frame
    return frames, errors


def benchmark_market_state() -> pd.Series:
    frames, _ = download_prices(['SPY', 'QQQ'])
    all_days = sorted(set().union(*(set(x.index) for x in frames.values()))) if frames else []
    if not all_days:
        return pd.Series(dtype='object')
    index = pd.DatetimeIndex(all_days)
    total = pd.Series(0.0, index=index)
    usable = 0
    for ticker in ('SPY', 'QQQ'):
        d = frames.get(ticker)
        if d is None or d.empty:
            continue
        ind = indicators(d)
        score = (
            (ind['close'] > ind['sma120']).astype(int)
            + (ind['close'] > ind['sma200']).astype(int)
            + (ind['rsi'] > 45).astype(int)
        )
        total = total.add(score.reindex(index).ffill().fillna(0), fill_value=0)
        usable += 1
    state = pd.Series('조심', index=index, dtype='object')
    if usable:
        state.loc[total >= 3] = '중립'
        state.loc[total >= 5] = '좋음'
    return state


def _confirmed_candidates(d: pd.DataFrame, symbol: str, market_state: pd.Series) -> list[dict]:
    state = market_state.reindex(d.index).ffill().fillna('조심')
    frame = canonical_signal_frame(d, state)
    features = historical_features(d, state, frame)
    scores = features['scores']['confirmed_pullback']
    flows = features['flows']
    overlay = features['overlay']
    ind = indicators(d)
    rows = []
    for i in range(205, len(d) - 2):
        if not bool(frame['confirmed_pullback'].iloc[i]) or float(scores.iloc[i]) < S_THRESHOLD:
            continue
        plan = plan_from_row(frame.iloc[i], 'confirmed_pullback', 'force_1_50')
        flow_row = flows.iloc[i]
        flow = {k: (None if pd.isna(v) else float(v)) for k, v in flow_row.items()}
        selected = selection_pass(
            float(scores.iloc[i]), flow, plan, str(state.iloc[i]),
            bool(overlay.iloc[i]), float(frame['close'].iloc[i]), 'confirmed_pullback',
        )
        if not selected.get('pass'):
            continue
        try:
            q = plan_execution_quality(plan)
        except Exception:
            continue
        entry_i = i + 1
        path = _path(d, ind, entry_i, 45)
        if not path:
            continue
        rows.append({
            'symbol': symbol,
            'strategy_id': 'confirmed_pullback',
            'strategy_name': STRATEGY_NAMES['confirmed_pullback'],
            'signal_date': d.index[i].strftime('%Y-%m-%d'),
            'entry_date': d.index[entry_i].strftime('%Y-%m-%d'),
            'signal_close': round(float(frame['close'].iloc[i]), 6),
            'buy_low': round(float(plan['buy_low']), 6),
            'buy_high': round(float(plan['buy_high']), 6),
            'atr': round(float(plan['atr']), 6),
            'target': round(float(plan['target']), 6),
            'stop': round(float(plan['stop']), 6),
            'max_hold': int(plan['days'][1]),
            'elite_score': round(float(selected['elite_score']), 4),
            'net_risk_reward': round(float(q['net_risk_reward']), 6),
            'market_state': str(state.iloc[i]),
            'quality_features': {
                'elite_score': round(float(selected['elite_score']), 4),
                'net_risk_reward': round(float(q['net_risk_reward']), 6),
            },
            'exit_mode': 'price_plan',
            'entry_mode': 'next_open',
            'path': path,
        })
    return rows


def candidate_rows(d: pd.DataFrame, symbol: str, market_state: pd.Series) -> list[dict]:
    ind = indicators(d)
    rows = _confirmed_candidates(d, symbol, market_state)
    rows.extend(_sma_candidates(d, ind, symbol))
    rows.extend(c for c in _breakout_candidates(d, ind, symbol) if c.get('strategy_id') == DONCHIAN55_ID)
    return rows


def membership_filter(candidates: list[dict], membership: MembershipIndex) -> list[dict]:
    out = []
    for c in candidates:
        try:
            signal_day = opt.parse_day(c['signal_date'])
            entry_day = opt.parse_day(c['entry_date'])
        except Exception:
            continue
        if signal_day < RESEARCH_START or signal_day > RESEARCH_END:
            continue
        if entry_day > RESEARCH_END:
            continue
        symbol = str(c.get('symbol') or '')
        if membership.contains(symbol, signal_day) and membership.contains(symbol, entry_day):
            out.append(c)
    return out


def coverage_summary(
    membership: MembershipIndex,
    universe: set[str],
    latest_members: set[str],
    frames: dict[str, pd.DataFrame],
) -> dict:
    historical_noncurrent = sorted(universe - latest_members)
    usable_noncurrent = []
    near_noncurrent = []
    any_noncurrent = []
    for ticker in historical_noncurrent:
        d = frames.get(ticker)
        if d is None or d.empty:
            continue
        any_noncurrent.append(ticker)
        last_seen = membership.last_seen(ticker, RESEARCH_END)
        if last_seen is None:
            continue
        before = d.loc[d.index.date <= last_seen]
        last_bar = before.index.max().date() if not before.empty else None
        near = bool(last_bar and last_bar >= last_seen - timedelta(days=NEAR_LAST_SEEN_DAYS))
        if near:
            near_noncurrent.append(ticker)
        if len(before) >= MIN_ROWS and near:
            usable_noncurrent.append(ticker)
    total_old = len(historical_noncurrent)
    return {
        'historical_universe_tickers': len(universe),
        'latest_member_count': len(latest_members),
        'downloaded_usable_tickers': len(frames),
        'historical_noncurrent_tickers': total_old,
        'historical_noncurrent_with_any_usable_frame': len(any_noncurrent),
        'historical_noncurrent_near_last_seen': len(near_noncurrent),
        'historical_noncurrent_warmup_and_near_last_seen': len(usable_noncurrent),
        'historical_noncurrent_coverage_pct': round(len(usable_noncurrent) / total_old * 100.0, 2) if total_old else 0.0,
        'missing_noncurrent_tickers': sorted(set(historical_noncurrent) - set(usable_noncurrent)),
    }


def _pool_stub() -> dict:
    return {
        'version': 4,
        'costs': {
            'commission_pct_per_side': BACKTEST_COMMISSION_PCT,
            'slippage_bps': BACKTEST_SLIPPAGE_BPS,
            'half_spread_bps': BACKTEST_HALF_SPREAD_BPS,
        },
    }


def prepare_candidates(candidates: list[dict]) -> None:
    for c in candidates:
        c['_quality'] = selection.quality_score(c)


def _fold_metrics(candidates: list[dict], folds: list[dict]) -> list[dict]:
    family = next(f for f in selection.FAMILIES if f['id'] == FAMILY_ID)
    pool = _pool_stub()
    cache: dict[tuple, dict | None] = {}

    def executed(c):
        key = (c.get('symbol'), c.get('strategy_id'), c.get('signal_date'))
        if key not in cache:
            cache[key] = mtm.execute_candidate_mtm(c, pool, None, None)
        return cache[key]

    results = []
    for fold in folds:
        thresholds, rows = v2.fixed_pairs(family, candidates, fold, executed)
        test = velocity.velocity_portfolio(rows, fold['test_start'], fold['test_end'], POLICY)
        results.append({
            'fold': fold['id'],
            'train_start': str(fold['train_start']),
            'train_end': str(fold['train_end']),
            'test_start': str(fold['test_start']),
            'test_end': str(fold['test_end']),
            'thresholds': {
                sid: None if thresholds[sid][v2.QUALITY_INTENSITY] is None else round(float(thresholds[sid][v2.QUALITY_INTENSITY]), 6)
                for sid in family['strategies']
            },
            'test': velocity.compact(test),
        })
    return results


def _summary(folds: list[dict]) -> dict:
    vals = [x['test'] for x in folds]
    returns = [x['return_pct'] for x in vals]
    compound = 1.0
    for value in returns:
        compound *= 1.0 + value / 100.0
    return {
        'fold_count': len(vals),
        'positive_folds': sum(x > 0 for x in returns),
        'stitched_test_return_pct': round((compound - 1.0) * 100.0, 2),
        'median_test_return_pct': round(median(returns), 2) if returns else 0.0,
        'worst_test_return_pct': round(min(returns), 2) if returns else 0.0,
        'worst_mdd_pct': round(min(x['mdd_pct'] for x in vals), 2) if vals else 0.0,
        'total_trades': sum(x['trades'] for x in vals),
        'mean_trades_per_year': round(mean(x['trades_per_year'] for x in vals), 1) if vals else 0.0,
        'total_cash_rejects': sum(x.get('reject_cash', 0) for x in vals),
        'mean_avg_cash_pct': round(mean(x.get('avg_cash_pct', 0.0) for x in vals), 1) if vals else 0.0,
    }


def compare_universes(survivor_folds: list[dict], pit_folds: list[dict]) -> dict:
    s = _summary(survivor_folds)
    p = _summary(pit_folds)
    per_fold = []
    for a, b in zip(survivor_folds, pit_folds):
        per_fold.append({
            'fold': a['fold'],
            'survivors_only_return_pct': a['test']['return_pct'],
            'pit_lite_return_pct': b['test']['return_pct'],
            'delta_pct': round(b['test']['return_pct'] - a['test']['return_pct'], 2),
            'survivors_only_mdd_pct': a['test']['mdd_pct'],
            'pit_lite_mdd_pct': b['test']['mdd_pct'],
        })
    return {
        'survivors_only': s,
        'pit_lite': p,
        'delta_stitched_return_pct': round(p['stitched_test_return_pct'] - s['stitched_test_return_pct'], 2),
        'delta_worst_mdd_pct': round(p['worst_mdd_pct'] - s['worst_mdd_pct'], 2),
        'pit_lite_better_folds': sum(x['delta_pct'] > .01 for x in per_fold),
        'pit_lite_worse_folds': sum(x['delta_pct'] < -.01 for x in per_fold),
        'per_fold': per_fold,
    }


def run(max_symbols: int | None = None) -> dict:
    now = datetime.now(timezone.utc)
    snapshots = fetch_snapshots()
    membership = MembershipIndex(snapshots)
    universe = membership.union(RESEARCH_START, RESEARCH_END)
    latest_members = snapshot_on(snapshots[-1]['date'], snapshots)

    tickers = sorted(universe)
    if max_symbols:
        # deterministic smoke mode: always retain historical non-current names first,
        # then fill with current members. Full research never sets this flag.
        old = sorted(universe - latest_members)
        cur = sorted(universe & latest_members)
        tickers = (old + cur)[:max_symbols]
        universe = set(tickers)
        latest_members = latest_members & universe

    frames, download_errors = download_prices(tickers)
    market_state = benchmark_market_state()
    all_candidates: list[dict] = []
    symbol_errors = []
    for n, ticker in enumerate(tickers, 1):
        d = frames.get(ticker)
        if d is None or len(d) < MIN_ROWS:
            continue
        try:
            rows = membership_filter(candidate_rows(d, ticker, market_state), membership)
            all_candidates.extend(rows)
        except Exception as exc:
            symbol_errors.append({'symbol': ticker, 'error': str(exc)})
        if n % 50 == 0:
            print('processed', n, 'of', len(tickers), 'candidates', len(all_candidates))

    all_candidates.sort(key=lambda x: (x['entry_date'], x['symbol'], x['strategy_id']))
    survivor_candidates = [c for c in all_candidates if c.get('symbol') in latest_members]
    prepare_candidates(all_candidates)
    prepare_candidates(survivor_candidates)

    folds = wf.folds_for(RESEARCH_START, RESEARCH_END)
    survivor_folds = _fold_metrics(survivor_candidates, folds)
    pit_folds = _fold_metrics(all_candidates, folds)
    coverage = coverage_summary(membership, universe, latest_members, frames)
    comparison = compare_universes(survivor_folds, pit_folds)

    historical_noncurrent_candidate_count = sum(1 for c in all_candidates if c.get('symbol') not in latest_members)
    payload = {
        'version': 1,
        'ready': True,
        'generated_at': now.isoformat(timespec='seconds'),
        'status': 'PIT_LITE_FREE_YAHOO_DIAGNOSTIC',
        'promotion_status': 'DIAGNOSTIC_ONLY_NOT_SURVIVORSHIP_FREE',
        'research_window': {'start': str(RESEARCH_START), 'end': str(RESEARCH_END)},
        'family': list(STRATEGIES),
        'portfolio': {'risk_budget_pct': .75, 'max_positions': 10, 'exit': 'natural_strategy_exit'},
        'method': {
            'membership': 'community-maintained historical S&P 500 snapshots; signal date and next-open entry date must both be members',
            'prices': 'free Yahoo/yfinance daily OHLCV only',
            'control': 'same historical S&P framework but restrict signals to tickers that remain in the latest S&P snapshot',
            'pit_lite': 'add every historical member whose Yahoo history is available enough to generate the strategy',
            'selection': 'within-strategy top50 quality threshold and hybrid_50 priority are recalculated on each fold TRAIN only',
            'validation': '4y TRAIN -> next complete calendar-year TEST, 2021-2025',
        },
        'coverage': coverage,
        'candidate_counts': {
            'survivors_only': len(survivor_candidates),
            'pit_lite': len(all_candidates),
            'historical_noncurrent_candidates_added': historical_noncurrent_candidate_count,
            'survivor_symbols_with_candidates': len({c['symbol'] for c in survivor_candidates}),
            'pit_lite_symbols_with_candidates': len({c['symbol'] for c in all_candidates}),
        },
        'comparison': comparison,
        'folds': {
            'survivors_only': survivor_folds,
            'pit_lite': pit_folds,
        },
        'download_error_batches': download_errors,
        'symbol_errors': symbol_errors,
        'limitations': [
            'This is PIT-Lite, not complete point-in-time proof: Yahoo misses many former/delisted histories.',
            'Missing historical non-current names are never replaced with current constituents and are never assumed to have zero return.',
            'Historical S&P 500 ticker labels are not permanent security IDs; ticker reuse and corporate actions can remain ambiguous.',
            'S&P 500 is an external large-cap survivorship stress universe, not the production liquid-stock universe.',
            'The 2021-2025 history has already influenced research direction, so this is development stress evidence, not a fresh promotion holdout.',
            'No result in this file changes the main picker, V1/V2/V3/V4 Forward states, or live-order rules.',
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
        'candidate_counts': payload['candidate_counts'],
        'survivors_only': comparison['survivors_only'],
        'pit_lite': comparison['pit_lite'],
        'delta_stitched_return_pct': comparison['delta_stitched_return_pct'],
    }, ensure_ascii=False, indent=2))
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--max-symbols', type=int, default=None)
    args = parser.parse_args()
    run(max_symbols=args.max_symbols)


if __name__ == '__main__':
    main()
