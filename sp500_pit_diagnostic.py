from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from io import StringIO
import json
from pathlib import Path
import re

import pandas as pd
import requests

ROOT = Path(__file__).parent
OUT = ROOT / 'static' / 'sp500_pit_diagnostic.json'
SOURCE_REPO = 'https://github.com/chinobing/historical_sp500_constituents'
SOURCE_CSV = 'https://raw.githubusercontent.com/chinobing/historical_sp500_constituents/main/sp_500_historical_components.csv'
TARGET_START = date(2017, 1, 1)
TARGET_END = date(2026, 8, 13)
MAX_SOURCE_AGE_DAYS = 45


def _ticker(value) -> str:
    text = re.sub(r'\[[^\]]+\]', '', str(value or '')).strip().upper().replace('.', '-')
    return re.sub(r'[^A-Z0-9\-]', '', text)


def parse_snapshot_csv(text: str) -> list[dict]:
    frame = pd.read_csv(StringIO(text))
    lower = {str(c).strip().lower(): c for c in frame.columns}
    date_col = lower.get('date')
    tickers_col = lower.get('tickers')
    if date_col is None or tickers_col is None:
        raise ValueError(f'historical component CSV requires date,tickers columns; got {list(frame.columns)}')

    by_day: dict[date, set[str]] = {}
    for _, row in frame.iterrows():
        parsed = pd.to_datetime(row.get(date_col), errors='coerce')
        if pd.isna(parsed):
            continue
        day = parsed.date()
        members = {_ticker(x) for x in str(row.get(tickers_col) or '').split(',')}
        members.discard('')
        if members:
            by_day[day] = members
    if not by_day:
        raise ValueError('historical component CSV contained no usable snapshots')
    return [
        {'date': day, 'members': by_day[day]}
        for day in sorted(by_day)
    ]


def snapshot_on(target: date, snapshots: list[dict]) -> set[str]:
    eligible = [row for row in snapshots if row['date'] <= target]
    if not eligible:
        return set()
    return set(eligible[-1]['members'])


def month_ends(start: date, end: date) -> list[date]:
    if end < start:
        return []
    periods = pd.period_range(start=start, end=end, freq='M')
    return [min(p.end_time.date(), end) for p in periods]


def _last_seen(snapshots: list[dict], *, end: date) -> dict[str, date]:
    out: dict[str, date] = {}
    for row in snapshots:
        if row['date'] > end:
            break
        for ticker in row['members']:
            out[ticker] = row['date']
    return out


def build_from_snapshots(snapshots: list[dict], *, as_of: date) -> dict:
    usable = [row for row in snapshots if row['date'] <= as_of]
    if not usable:
        raise ValueError('no historical membership snapshot at or before as_of')

    source_start = usable[0]['date']
    source_end = usable[-1]['date']
    coverage_end = min(TARGET_END, as_of, source_end)
    requested_end = min(TARGET_END, as_of)
    latest_members = set(usable[-1]['members'])
    freshness_days = max(0, (as_of - source_end).days)

    monthly = []
    for day in month_ends(TARGET_START, coverage_end):
        members = snapshot_on(day, usable)
        monthly.append({'date': day.isoformat(), 'member_count': len(members)})

    last_seen = _last_seen(usable, end=coverage_end)
    historical_noncurrent = {
        ticker: day for ticker, day in last_seen.items()
        if day >= TARGET_START and ticker not in latest_members
    }
    counts = [x['member_count'] for x in monthly]
    count_plausible = bool(counts and min(counts) >= 450 and max(counts) <= 550)
    start_covered = source_start <= TARGET_START
    fresh_enough = freshness_days <= MAX_SOURCE_AGE_DAYS
    ready = bool(count_plausible and start_covered and fresh_enough)

    return {
        'version': 2,
        'ready': ready,
        'status': 'DIAGNOSTIC_MEMBERSHIP_READY' if ready else 'DIAGNOSTIC_MEMBERSHIP_COVERAGE_WARNING',
        'promotion_status': 'DIAGNOSTIC_ONLY_COMMUNITY_MEMBERSHIP',
        'source_type': 'community_maintained_historical_sp500_snapshots',
        'source_repository': SOURCE_REPO,
        'source_csv': SOURCE_CSV,
        'as_of': as_of.isoformat(),
        'requested_target_start': TARGET_START.isoformat(),
        'requested_target_end': requested_end.isoformat(),
        'target_start': TARGET_START.isoformat(),
        'target_end': coverage_end.isoformat(),
        'source_coverage_start': source_start.isoformat(),
        'source_coverage_end': source_end.isoformat(),
        'source_age_days': freshness_days,
        'source_freshness_limit_days': MAX_SOURCE_AGE_DAYS,
        'snapshot_count': len(usable),
        'current_member_count': len(latest_members),
        'unique_historical_ticker_count': len(last_seen),
        'historical_removed_tickers': sorted(historical_noncurrent),
        'ticker_last_seen': {ticker: historical_noncurrent[ticker].isoformat() for ticker in sorted(historical_noncurrent)},
        'monthly_member_counts': monthly,
        'latest_members': sorted(latest_members),
        'coverage_checks': {
            'target_start_covered': start_covered,
            'source_fresh_enough': fresh_enough,
            'monthly_member_count_plausible': count_plausible,
        },
        'limitations': [
            'This is a community-maintained historical S&P 500 dataset, not the final licensed PIT source.',
            'Ticker strings are historical labels, not permanent security identifiers; ticker reuse/corporate actions can still be ambiguous.',
            'The source is an external large-cap sensitivity universe, not the same objective universe as today\'s liquid-stock screener.',
            'The last-seen date is a snapshot-derived membership endpoint proxy, not a guaranteed final trading date.',
            'No production picker, current replay pool, or Forward challenger uses this diagnostic.',
        ],
    }


def fetch_snapshots() -> list[dict]:
    response = requests.get(
        SOURCE_CSV,
        timeout=30,
        headers={'User-Agent': 'swing-lab-research/1.0 (historical-index diagnostic)'},
    )
    response.raise_for_status()
    return parse_snapshot_csv(response.text)


def run() -> dict:
    now = datetime.now(timezone.utc)
    payload = build_from_snapshots(fetch_snapshots(), as_of=now.date())
    payload['generated_at'] = now.isoformat(timespec='seconds')
    payload['production_main_picker_mutated'] = False
    payload['forward_challengers_mutated'] = False
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({
        'status': payload['status'],
        'source_coverage_end': payload['source_coverage_end'],
        'source_age_days': payload['source_age_days'],
        'current_member_count': payload['current_member_count'],
        'snapshot_count': payload['snapshot_count'],
        'unique_historical_ticker_count': payload['unique_historical_ticker_count'],
        'historical_removed_ticker_count': len(payload['historical_removed_tickers']),
        'monthly_count_min': min((x['member_count'] for x in payload['monthly_member_counts']), default=None),
        'monthly_count_max': max((x['member_count'] for x in payload['monthly_member_counts']), default=None),
    }, ensure_ascii=False, indent=2))
    return payload


if __name__ == '__main__':
    run()
