from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).parent
MEMBERSHIP = ROOT / 'static' / 'sp500_pit_diagnostic.json'
OUT = ROOT / 'static' / 'sp500_pit_price_coverage.json'
START = '2016-01-01'
WARMUP_ROWS = 205
REMOVAL_TOLERANCE_DAYS = 10
CHUNK = 30


def _close_series(raw: pd.DataFrame, ticker: str, ticker_count: int) -> pd.Series:
    if raw is None or raw.empty:
        return pd.Series(dtype=float)
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            if ticker in raw.columns.get_level_values(0):
                frame = raw[ticker]
                col = 'Adj Close' if 'Adj Close' in frame.columns else 'Close'
                return pd.to_numeric(frame[col], errors='coerce').dropna()
            if ticker in raw.columns.get_level_values(-1):
                frame = raw.xs(ticker, level=-1, axis=1)
                col = 'Adj Close' if 'Adj Close' in frame.columns else 'Close'
                return pd.to_numeric(frame[col], errors='coerce').dropna()
        col = 'Adj Close' if 'Adj Close' in raw.columns else 'Close'
        return pd.to_numeric(raw[col], errors='coerce').dropna()
    except Exception:
        return pd.Series(dtype=float)


def coverage_for_series(series: pd.Series, removal_day: date) -> dict:
    if series is None or series.empty:
        return {
            'rows': 0,
            'first_date': None,
            'last_date': None,
            'has_any_history': False,
            'has_warmup': False,
            'near_removal': False,
            'usable_for_signal_replay': False,
        }
    idx = pd.to_datetime(series.index)
    if getattr(idx, 'tz', None) is not None:
        idx = idx.tz_localize(None)
    values = pd.Series(series.to_numpy(), index=idx).dropna().sort_index()
    cutoff = pd.Timestamp(removal_day)
    before = values.loc[values.index <= cutoff]
    first = before.index.min().date() if not before.empty else None
    last = before.index.max().date() if not before.empty else None
    warmup = len(before) >= WARMUP_ROWS
    near = bool(last and last >= removal_day - timedelta(days=REMOVAL_TOLERANCE_DAYS))
    return {
        'rows': int(len(before)),
        'first_date': first.isoformat() if first else None,
        'last_date': last.isoformat() if last else None,
        'has_any_history': bool(len(before)),
        'has_warmup': bool(warmup),
        'near_removal': bool(near),
        'usable_for_signal_replay': bool(warmup and near),
    }


def _removal_map(membership: dict) -> dict[str, date]:
    out: dict[str, date] = {}
    target_start = date.fromisoformat(membership.get('target_start') or '2017-01-01')
    for change in membership.get('changes') or []:
        ticker = str(change.get('removed') or '').strip().upper()
        if not ticker:
            continue
        day = date.fromisoformat(change['effective_date'])
        if day < target_start:
            continue
        out[ticker] = max(out.get(ticker, day), day)
    return out


def download_removed_coverage(membership: dict) -> dict:
    removals = _removal_map(membership)
    tickers = sorted(removals)
    results: dict[str, dict] = {}
    errors = []
    end = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    for offset in range(0, len(tickers), CHUNK):
        batch = tickers[offset:offset + CHUNK]
        try:
            raw = yf.download(
                ' '.join(batch), start=START, end=end, interval='1d', auto_adjust=False,
                group_by='ticker', threads=True, progress=False, timeout=30,
            )
        except Exception as exc:
            errors.append({'batch': batch, 'error': str(exc)})
            raw = pd.DataFrame()
        for ticker in batch:
            series = _close_series(raw, ticker, len(batch))
            results[ticker] = {
                'removal_date': removals[ticker].isoformat(),
                **coverage_for_series(series, removals[ticker]),
            }

    usable = [t for t, x in results.items() if x['usable_for_signal_replay']]
    any_history = [t for t, x in results.items() if x['has_any_history']]
    near = [t for t, x in results.items() if x['near_removal']]
    total = len(results)
    return {
        'version': 1,
        'ready': True,
        'status': 'FREE_PRICE_COVERAGE_DIAGNOSTIC',
        'promotion_status': 'DIAGNOSTIC_ONLY_NOT_RESEARCH_GRADE_PIT',
        'source': 'yfinance_free_history_probe',
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'membership_generated_at': membership.get('generated_at'),
        'removed_ticker_count': total,
        'with_any_history': len(any_history),
        'with_any_history_pct': round(len(any_history) / total * 100, 2) if total else 0.0,
        'near_removal_count': len(near),
        'near_removal_pct': round(len(near) / total * 100, 2) if total else 0.0,
        'usable_warmup_and_near_removal_count': len(usable),
        'usable_warmup_and_near_removal_pct': round(len(usable) / total * 100, 2) if total else 0.0,
        'missing_or_incomplete_tickers': sorted(t for t, x in results.items() if not x['usable_for_signal_replay']),
        'ticker_results': results,
        'errors': errors,
        'research_grade_pit_ready': False,
        'limitations': [
            'This probes free Yahoo/yfinance availability only; it is not assumed complete for delisted securities.',
            'A ticker having historical bars does not prove permanent-identifier or corporate-action continuity.',
            'Near-removal coverage uses a 10-calendar-day tolerance because the effective index removal date may follow the final trading session.',
            'This diagnostic cannot promote production rules or mark the strict PIT source manifest VERIFIED.',
        ],
        'production_main_picker_mutated': False,
        'forward_challengers_mutated': False,
    }


def run() -> dict:
    membership = json.loads(MEMBERSHIP.read_text(encoding='utf-8'))
    payload = download_removed_coverage(membership)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({
        'removed': payload['removed_ticker_count'],
        'any_history_pct': payload['with_any_history_pct'],
        'usable_pct': payload['usable_warmup_and_near_removal_pct'],
        'missing_examples': payload['missing_or_incomplete_tickers'][:15],
    }, ensure_ascii=False, indent=2))
    return payload


if __name__ == '__main__':
    run()
