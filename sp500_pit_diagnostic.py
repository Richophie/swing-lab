from __future__ import annotations

from datetime import date, datetime, timezone
from io import StringIO
import json
from pathlib import Path
import re

import pandas as pd
import requests

ROOT = Path(__file__).parent
OUT = ROOT / 'static' / 'sp500_pit_diagnostic.json'
PAGE_URL = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
API_URL = 'https://en.wikipedia.org/w/api.php'
PAGE_NAME = 'List of S&P 500 companies'
TARGET_START = date(2017, 1, 1)
TARGET_END = date(2026, 8, 13)


def _flat_column(value) -> str:
    if isinstance(value, tuple):
        parts = [str(x).strip() for x in value if str(x).strip() and not str(x).lower().startswith('unnamed')]
        return ' '.join(dict.fromkeys(parts)).lower()
    return str(value).strip().lower()


def _ticker(value) -> str:
    text = re.sub(r'\[[^\]]+\]', '', str(value or '')).strip().upper().replace('.', '-')
    text = re.sub(r'[^A-Z0-9\-]', '', text)
    return text


def _find_col(df: pd.DataFrame, *needles: str):
    cols = {col: _flat_column(col) for col in df.columns}
    for col, flat in cols.items():
        if all(n.lower() in flat for n in needles):
            return col
    return None


def normalize_current_table(df: pd.DataFrame) -> list[dict]:
    symbol_col = _find_col(df, 'symbol')
    security_col = _find_col(df, 'security')
    if symbol_col is None:
        raise ValueError('current constituent table missing Symbol column')
    out = []
    for _, row in df.iterrows():
        symbol = _ticker(row.get(symbol_col))
        if not symbol:
            continue
        out.append({
            'symbol': symbol,
            'security': str(row.get(security_col) or '').strip() if security_col is not None else '',
        })
    return out


def normalize_changes_table(df: pd.DataFrame) -> list[dict]:
    date_col = _find_col(df, 'effective', 'date')
    if date_col is None:
        date_col = _find_col(df, 'date')
    added_col = _find_col(df, 'added', 'ticker')
    removed_col = _find_col(df, 'removed', 'ticker')
    added_name_col = _find_col(df, 'added', 'security')
    removed_name_col = _find_col(df, 'removed', 'security')
    if date_col is None or added_col is None or removed_col is None:
        raise ValueError('changes table missing date/added ticker/removed ticker columns')
    out = []
    for _, row in df.iterrows():
        parsed = pd.to_datetime(row.get(date_col), errors='coerce')
        if pd.isna(parsed):
            continue
        added = _ticker(row.get(added_col))
        removed = _ticker(row.get(removed_col))
        if not added and not removed:
            continue
        out.append({
            'effective_date': parsed.date().isoformat(),
            'added': added or None,
            'added_security': str(row.get(added_name_col) or '').strip() if added_name_col is not None else '',
            'removed': removed or None,
            'removed_security': str(row.get(removed_name_col) or '').strip() if removed_name_col is not None else '',
        })
    out.sort(key=lambda x: (x['effective_date'], x.get('added') or '', x.get('removed') or ''))
    return out


def _table_columns_debug(tables: list[pd.DataFrame]) -> list[list[str]]:
    return [[_flat_column(c) for c in df.columns] for df in tables]


def identify_tables(tables: list[pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    current = None
    changes = None
    for df in tables:
        flats = [_flat_column(c) for c in df.columns]
        if current is None and any('symbol' in x for x in flats) and any('security' in x for x in flats):
            if not any('added' in x or 'removed' in x for x in flats):
                current = df
        if changes is None and any('added' in x and ('ticker' in x or 'symbol' in x) for x in flats) and any('removed' in x and ('ticker' in x or 'symbol' in x) for x in flats):
            changes = df
    if current is None or changes is None:
        raise ValueError(f'could not identify current/changes tables; columns={_table_columns_debug(tables)}')
    return current, changes


def members_on(target: date, current_symbols: set[str], changes: list[dict], *, as_of: date) -> set[str]:
    if target > as_of:
        raise ValueError('target cannot be after as_of')
    members = set(current_symbols)
    relevant = [x for x in changes if target < date.fromisoformat(x['effective_date']) <= as_of]
    for change in sorted(relevant, key=lambda x: x['effective_date'], reverse=True):
        added = change.get('added')
        removed = change.get('removed')
        if added:
            members.discard(added)
        if removed:
            members.add(removed)
    return members


def month_ends(start: date, end: date) -> list[date]:
    periods = pd.period_range(start=start, end=end, freq='M')
    return [min(p.end_time.date(), end) for p in periods]


def build_from_tables(tables: list[pd.DataFrame], *, as_of: date) -> dict:
    current_df, changes_df = identify_tables(tables)
    current_rows = normalize_current_table(current_df)
    changes = normalize_changes_table(changes_df)
    current_symbols = {x['symbol'] for x in current_rows}
    usable_changes = [x for x in changes if date.fromisoformat(x['effective_date']) <= as_of]
    target_end = min(TARGET_END, as_of)
    snapshots = []
    for day in month_ends(TARGET_START, target_end):
        members = members_on(day, current_symbols, usable_changes, as_of=as_of)
        snapshots.append({'date': day.isoformat(), 'member_count': len(members)})
    unique_historical = set(current_symbols)
    for change in usable_changes:
        if change.get('added'):
            unique_historical.add(change['added'])
        if change.get('removed'):
            unique_historical.add(change['removed'])
    counts = [x['member_count'] for x in snapshots]
    plausible = bool(current_symbols and snapshots and min(counts) >= 450 and max(counts) <= 550)
    return {
        'version': 1,
        'ready': plausible,
        'status': 'DIAGNOSTIC_MEMBERSHIP_READY' if plausible else 'DIAGNOSTIC_MEMBERSHIP_PARSE_WARNING',
        'promotion_status': 'DIAGNOSTIC_ONLY_COMMUNITY_MEMBERSHIP',
        'source_type': 'community_reconstructed_index_membership',
        'source_url': PAGE_URL,
        'as_of': as_of.isoformat(),
        'target_start': TARGET_START.isoformat(),
        'target_end': target_end.isoformat(),
        'current_member_count': len(current_symbols),
        'change_event_count': len(usable_changes),
        'unique_historical_ticker_count': len(unique_historical),
        'historical_removed_tickers': sorted({x['removed'] for x in usable_changes if x.get('removed') and date.fromisoformat(x['effective_date']) >= TARGET_START}),
        'monthly_member_counts': snapshots,
        'current_members': sorted(current_symbols),
        'changes': usable_changes,
        'limitations': [
            'This is a community-maintained S&P 500 constituent/change table, not the final licensed PIT source.',
            'Ticker strings are reconstructed backwards and are not permanent security identifiers.',
            'Historical corporate actions, ticker reuse and omitted change records can create reconstruction errors.',
            'S&P 500 membership is a large-cap benchmark sensitivity universe, not the same objective universe as today\'s liquid-stock screener.',
            'No production picker or Forward challenger uses this diagnostic.',
        ],
    }


def fetch_tables() -> list[pd.DataFrame]:
    response = requests.get(
        API_URL,
        params={'action': 'parse', 'page': PAGE_NAME, 'prop': 'text', 'format': 'json', 'formatversion': 2},
        timeout=30,
        headers={'User-Agent': 'swing-lab-research/1.0 (historical-index diagnostic)'},
    )
    response.raise_for_status()
    payload = response.json()
    html = ((payload.get('parse') or {}).get('text'))
    if isinstance(html, dict):
        html = html.get('*')
    if not html:
        raise ValueError(f'Wikipedia parse API returned no page HTML: {payload.get("error") or "unknown response"}')
    return pd.read_html(StringIO(str(html)))


def run() -> dict:
    now = datetime.now(timezone.utc)
    payload = build_from_tables(fetch_tables(), as_of=now.date())
    payload['generated_at'] = now.isoformat(timespec='seconds')
    payload['production_main_picker_mutated'] = False
    payload['forward_challengers_mutated'] = False
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({
        'status': payload['status'],
        'current_member_count': payload['current_member_count'],
        'change_event_count': payload['change_event_count'],
        'unique_historical_ticker_count': payload['unique_historical_ticker_count'],
        'monthly_count_min': min((x['member_count'] for x in payload['monthly_member_counts']), default=None),
        'monthly_count_max': max((x['member_count'] for x in payload['monthly_member_counts']), default=None),
    }, ensure_ascii=False, indent=2))
    return payload


if __name__ == '__main__':
    run()
