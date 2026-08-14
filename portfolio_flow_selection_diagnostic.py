from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
from statistics import mean, median

import numpy as np
import pandas as pd
import yfinance as yf

from global_flow_map import SECTORS
import portfolio_concentration_damp_research as concentration
import portfolio_walkforward_research as wf
import strategy_optimizer_runner as mtm
import strategy_optimizer_v2 as opt
import strategy_selection_research as selection

POOL = Path('static/replay_backtest_pool_v2.json')
OUT = Path('static/portfolio_flow_selection_diagnostic.json')
FAMILY_ID = 'confirmed_sma_donchian'
QUALITY_INTENSITY = 'loose'  # frozen top 50% quality within strategy, TRAIN only per fold
FLOW_STRONG = 10.0
FLOW_WEAK = -10.0
MIN_BUCKET_TRADES = 5


def _family() -> dict:
    return next(x for x in selection.FAMILIES if x['id'] == FAMILY_ID)


def _num(value, default=0.0):
    try:
        x = float(value)
        return x if np.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _ticker_frame(raw: pd.DataFrame, ticker: str, count: int) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = set(map(str, raw.columns.get_level_values(0)))
        level1 = set(map(str, raw.columns.get_level_values(1)))
        if ticker in level0:
            frame = raw[ticker].copy()
        elif ticker in level1:
            frame = raw.xs(ticker, axis=1, level=1).copy()
        else:
            return pd.DataFrame()
    else:
        frame = raw.copy() if count == 1 else pd.DataFrame()
    if frame.empty:
        return frame
    idx = pd.to_datetime(frame.index)
    if getattr(idx, 'tz', None) is not None:
        idx = idx.tz_localize(None)
    frame.index = idx
    return frame.sort_index().dropna(how='all')


def _peer_percentile(frame: pd.DataFrame) -> pd.DataFrame:
    """Match global_flow_map._percentile: (below + 0.5 * equal) / N."""
    ranks = frame.rank(axis=1, method='average', na_option='keep')
    counts = frame.notna().sum(axis=1).replace(0, np.nan)
    return ranks.sub(0.5).div(counts, axis=0)


def build_historical_flow_scores() -> tuple[pd.DataFrame, dict]:
    tickers = sorted(set(SECTORS) | {'SPY'})
    raw = yf.download(
        tickers,
        period='10y',
        interval='1d',
        auto_adjust=True,
        group_by='ticker',
        threads=True,
        progress=False,
    )
    closes = {}
    volumes = {}
    missing = []
    for ticker in tickers:
        frame = _ticker_frame(raw, ticker, len(tickers))
        if frame.empty or 'Close' not in frame:
            missing.append(ticker)
            continue
        closes[ticker] = pd.to_numeric(frame['Close'], errors='coerce')
        if 'Volume' in frame:
            volumes[ticker] = pd.to_numeric(frame['Volume'], errors='coerce')
    if 'SPY' not in closes:
        raise RuntimeError('SPY history unavailable for Flow diagnostic')
    loaded_sectors = [x for x in SECTORS if x in closes and x in volumes]
    if len(loaded_sectors) < 8:
        raise RuntimeError(f'insufficient sector history: {len(loaded_sectors)}')

    close = pd.DataFrame({x: closes[x] for x in loaded_sectors}).sort_index()
    volume = pd.DataFrame({x: volumes[x] for x in loaded_sectors}).reindex(close.index)
    spy = closes['SPY'].reindex(close.index).ffill()

    ret5 = close / close.shift(5) - 1.0
    ret20 = close / close.shift(20) - 1.0
    spy5 = spy / spy.shift(5) - 1.0
    spy20 = spy / spy.shift(20) - 1.0
    rel5 = ret5.sub(spy5, axis=0) * 100.0
    rel20 = ret20.sub(spy20, axis=0) * 100.0
    accel = rel5 - rel20 / 4.0
    vol_ratio = volume.rolling(5, min_periods=5).mean() / volume.rolling(20, min_periods=20).mean().replace(0, np.nan)
    log_volume = np.log(vol_ratio.clip(lower=0.25, upper=4.0))

    mix = (
        0.35 * _peer_percentile(rel5)
        + 0.35 * _peer_percentile(rel20)
        + 0.15 * _peer_percentile(accel)
        + 0.15 * _peer_percentile(log_volume)
    )
    scores = (mix - 0.5) * 200.0
    scores = scores.replace([np.inf, -np.inf], np.nan)
    return scores, {
        'sector_etfs_loaded': loaded_sectors,
        'missing_sector_etfs': sorted(set(missing) & set(SECTORS)),
        'flow_start': str(scores.dropna(how='all').index.min().date()),
        'flow_end': str(scores.dropna(how='all').index.max().date()),
    }


def flow_bucket(score: float) -> str:
    if float(score) >= FLOW_STRONG:
        return 'strong'
    if float(score) <= FLOW_WEAK:
        return 'weak'
    return 'neutral'


def flow_heat(score: float) -> str:
    value = float(score)
    if value >= 35.0:
        return 'hot'
    if value >= 10.0:
        return 'warm'
    if value <= -35.0:
        return 'cold'
    if value <= -10.0:
        return 'cool'
    return 'neutral'


def score_asof(scores: pd.DataFrame, sector: str, asof: str):
    if sector not in scores:
        return None, None
    day = pd.Timestamp(str(asof)[:10])
    series = scores.loc[:day, sector].dropna()
    if series.empty:
        return None, None
    actual = series.index[-1]
    # Candidate signals and sector ETFs share the US trading calendar. Refuse stale data.
    if actual.normalize() != day.normalize():
        return None, None
    return float(series.iloc[-1]), actual.date().isoformat()


def _stats(rows: list[dict]) -> dict:
    if not rows:
        return {
            'trades': 0, 'mean_return_pct': None, 'median_return_pct': None,
            'win_rate_pct': None, 'stop_rate_pct': None, 'mean_flow_score': None,
        }
    returns = [float(x['return_pct']) for x in rows]
    return {
        'trades': len(rows),
        'mean_return_pct': round(mean(returns), 3),
        'median_return_pct': round(median(returns), 3),
        'win_rate_pct': round(sum(x > 0 for x in returns) / len(returns) * 100.0, 2),
        'stop_rate_pct': round(sum(str(x.get('exit_reason') or '').startswith('손절') for x in rows) / len(rows) * 100.0, 2),
        'mean_flow_score': round(mean(float(x['flow_score']) for x in rows), 2),
    }


def _bucket_stats(rows: list[dict], key: str = 'flow_bucket') -> dict:
    names = ['strong', 'neutral', 'weak'] if key == 'flow_bucket' else ['hot', 'warm', 'neutral', 'cool', 'cold']
    return {name: _stats([x for x in rows if x.get(key) == name]) for name in names}


def _rank_corr(rows: list[dict]):
    if len(rows) < 3:
        return None
    x = pd.Series([float(r['flow_score']) for r in rows]).rank(method='average')
    y = pd.Series([float(r['return_pct']) for r in rows]).rank(method='average')
    value = x.corr(y)
    return None if value is None or not np.isfinite(value) else round(float(value), 4)


def summarize(rows: list[dict]) -> dict:
    buckets = _bucket_stats(rows)
    strong = buckets['strong']; weak = buckets['weak']
    comparable = []
    for fold in sorted({str(x['fold']) for x in rows}):
        yr = [x for x in rows if str(x['fold']) == fold]
        s = [x for x in yr if x['flow_bucket'] == 'strong']
        w = [x for x in yr if x['flow_bucket'] == 'weak']
        if len(s) >= MIN_BUCKET_TRADES and len(w) >= MIN_BUCKET_TRADES:
            comparable.append({
                'fold': fold,
                'strong_trades': len(s),
                'weak_trades': len(w),
                'strong_mean_return_pct': round(mean(x['return_pct'] for x in s), 3),
                'weak_mean_return_pct': round(mean(x['return_pct'] for x in w), 3),
            })
    beats = sum(x['strong_mean_return_pct'] > x['weak_mean_return_pct'] for x in comparable)
    mean_delta = None
    median_delta = None
    win_delta = None
    if strong['trades'] and weak['trades']:
        mean_delta = round(strong['mean_return_pct'] - weak['mean_return_pct'], 3)
        median_delta = round(strong['median_return_pct'] - weak['median_return_pct'], 3)
        win_delta = round(strong['win_rate_pct'] - weak['win_rate_pct'], 2)

    if not comparable or strong['trades'] < 20 or weak['trades'] < 20:
        pattern = 'insufficient'
    elif mean_delta is not None and median_delta is not None and mean_delta > 0 and median_delta > 0 and beats / len(comparable) >= 0.67:
        pattern = 'repeats_but_development_only'
    elif mean_delta is not None and mean_delta > 0 and beats / len(comparable) >= 0.50:
        pattern = 'mixed_positive'
    else:
        pattern = 'not_supported'

    by_strategy = {}
    for sid in _family()['strategies']:
        group = [x for x in rows if x['strategy_id'] == sid]
        by_strategy[sid] = {'overall': _stats(group), 'buckets': _bucket_stats(group)}

    return {
        'overall': _stats(rows),
        'buckets': buckets,
        'heat_buckets': _bucket_stats(rows, 'flow_heat'),
        'spearman_flow_vs_trade_return': _rank_corr(rows),
        'strong_minus_weak_mean_return_pp': mean_delta,
        'strong_minus_weak_median_return_pp': median_delta,
        'strong_minus_weak_win_rate_pp': win_delta,
        'comparable_folds': len(comparable),
        'strong_beats_weak_folds': beats,
        'fold_comparisons': comparable,
        'pattern': pattern,
        'by_strategy': by_strategy,
    }


def main() -> None:
    pool = json.loads(POOL.read_text(encoding='utf-8'))
    if not pool.get('ready') or int(pool.get('version') or 0) < 4:
        raise SystemExit('Replay pool V4 is required')

    family = _family()
    candidates = [dict(x) for x in pool.get('trades') or [] if x.get('strategy_id') in set(family['strategies'])]
    for c in candidates:
        c['_quality'] = selection.quality_score(c)
    available_start = opt.parse_day(pool['available_start'])
    available_end = opt.parse_day(pool['available_end'])
    folds = wf.folds_for(available_start, available_end)
    if len(folds) < 3:
        raise SystemExit('Not enough history for Flow diagnostic')

    symbols = sorted({str(c.get('symbol') or '') for c in candidates if c.get('symbol')})
    returns, missing_symbols = concentration._download_returns(symbols + list(SECTORS))
    flow_scores, flow_meta = build_historical_flow_scores()
    sector_cache = {}
    exec_cache = {}
    records = []
    missing_sector_assignment = 0
    missing_flow_score = 0
    quality_test_candidates = 0

    def executed(c):
        key = (c.get('symbol'), c.get('strategy_id'), c.get('signal_date'))
        if key not in exec_cache:
            exec_cache[key] = mtm.execute_candidate_mtm(c, pool, None, None)
        return exec_cache[key]

    fold_rows = []
    for fold in folds:
        thresholds = wf.thresholds_for(candidates, family['strategies'], fold['train_start'], fold['train_end'])
        before = len(records)
        for c in candidates:
            sid = c.get('strategy_id')
            entry_day = opt.parse_day(c['entry_date'])
            if not (fold['test_start'] <= entry_day <= fold['test_end']):
                continue
            threshold = thresholds[sid][QUALITY_INTENSITY]
            if threshold is not None and c['_quality'] < threshold:
                continue
            quality_test_candidates += 1
            row = executed(c)
            if not row or opt.parse_day(row['end_date']) > fold['test_end']:
                continue
            signal_day = str(c.get('signal_date') or '')[:10]
            sector, sector_corr = concentration.behavior_sector(str(c.get('symbol') or ''), signal_day, returns, sector_cache)
            if not sector:
                missing_sector_assignment += 1
                continue
            flow, flow_day = score_asof(flow_scores, sector, signal_day)
            if flow is None:
                missing_flow_score += 1
                continue
            records.append({
                'fold': fold['id'],
                'signal_date': signal_day,
                'entry_date': row['start_date'],
                'exit_date': row['end_date'],
                'symbol': c.get('symbol'),
                'strategy_id': sid,
                'behavior_sector': sector,
                'behavior_sector_corr': None if sector_corr is None else round(float(sector_corr), 4),
                'flow_score_date': flow_day,
                'flow_score': round(float(flow), 2),
                'flow_bucket': flow_bucket(flow),
                'flow_heat': flow_heat(flow),
                'return_pct': round(_num(row.get('change')) * 100.0, 4),
                'exit_reason': row.get('reason'),
            })
        fold_records = records[before:]
        fold_rows.append({
            'fold': fold['id'],
            'train_start': str(fold['train_start']),
            'train_end': str(fold['train_end']),
            'test_start': str(fold['test_start']),
            'test_end': str(fold['test_end']),
            'thresholds_top50': {
                sid: None if thresholds[sid][QUALITY_INTENSITY] is None else round(float(thresholds[sid][QUALITY_INTENSITY]), 6)
                for sid in family['strategies']
            },
            'summary': summarize(fold_records),
        })

    summary = summarize(records)
    payload = {
        'version': 1,
        'ready': True,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'pool_generated_at': pool.get('generated_at'),
        'promotion_status': 'development_only_report_no_main_picker_mutation',
        'family': {
            'id': family['id'],
            'name': family['name'],
            'strategies': family['strategies'],
            'capacity_reference': family['capacity'],
            'quality_intensity': QUALITY_INTENSITY,
        },
        'method': {
            'type': 'rolling OOS trade-level Flow selection diagnostic',
            'production_main_picker_mutated': False,
            'live_orders_mutated': False,
            'portfolio_filter_applied': False,
            'flow_formula_frozen': '35% 5d relative + 35% 20d relative + 15% acceleration + 15% 5d/20d volume ratio peer percentile',
            'flow_thresholds_frozen': {'strong_gte': FLOW_STRONG, 'weak_lte': FLOW_WEAK},
            'behavior_sector': f'highest trailing {concentration.LOOKBACK}-session correlation to 11 sector ETFs; minimum overlap {concentration.MIN_OVERLAP}',
            'quality_filter': 'top 50% within each strategy; threshold recomputed on each fold TRAIN only and frozen for next-year TEST',
            'timing': 'behavior sector and Flow score use signal-day close or earlier only; later trade outcome is report-only',
            'portfolio_note': 'trade-level diagnostic only; capacity/cash competition is intentionally not changed or optimized here',
            'development_warning': '2021-2026 history has already informed project hypotheses and is development evidence, not pristine final OOS proof',
        },
        'data': {
            **flow_meta,
            'candidate_symbols': len(symbols),
            'missing_return_symbols': missing_symbols,
            'quality_test_candidates': quality_test_candidates,
            'classified_trades': len(records),
            'missing_behavior_sector': missing_sector_assignment,
            'missing_signal_day_flow': missing_flow_score,
        },
        'summary': summary,
        'folds': fold_rows,
        'records': records,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    b = summary['buckets']
    print('Flow selection diagnostic', summary['pattern'])
    print('classified', len(records), 'rank corr', summary['spearman_flow_vs_trade_return'])
    print('strong', b['strong'], 'neutral', b['neutral'], 'weak', b['weak'])
    print('strong-weak mean pp', summary['strong_minus_weak_mean_return_pp'], 'folds', summary['strong_beats_weak_folds'], '/', summary['comparable_folds'])


if __name__ == '__main__':
    main()
