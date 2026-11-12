"""Past earnings announcement days from SEC filings (free, official).

A company reports quarterly results in a Form 8-K with Item 2.02. The filing's acceptance
time tells whether the market could react the same day (filed before the close) or only the
next trading day (filed after the close). That first session is the "reaction day".

Output: static/earnings_dates.json  {symbol: [reaction day, ...]}
"""
from __future__ import annotations

from datetime import datetime, time as clock, timedelta, timezone
import json
import os
from pathlib import Path
import time

import requests

OUT = Path('static/earnings_dates.json')
# The SEC requires automated requests to name a contact. It is read from the environment and never stored in the repository.
CONTACT_ENV = 'SEC_CONTACT_EMAIL'
FIRST_DATE = '2016-06-01'
PAUSE_SECONDS = 0.15      # SEC asks for at most ten requests a second
MARKET_CLOSE = clock(16, 0)


def new_york(utc_text: str) -> datetime:
    """SEC acceptance times are UTC. US daylight time runs from the second Sunday of March to the first Sunday of November."""
    moment = datetime.fromisoformat(utc_text.replace('Z', '+00:00')).astimezone(timezone.utc)
    year = moment.year
    march = datetime(year, 3, 8, 7, tzinfo=timezone.utc)
    start = march + timedelta(days=(6 - march.weekday()) % 7)          # 2am EST = 07:00 UTC
    november = datetime(year, 11, 1, 6, tzinfo=timezone.utc)
    end = november + timedelta(days=(6 - november.weekday()) % 7)      # 2am EDT = 06:00 UTC
    return (moment - timedelta(hours=4 if start <= moment < end else 5)).replace(tzinfo=None)


def announcement_day(utc_text: str) -> tuple[str, bool]:
    """Calendar day in New York and whether the filing came after the close."""
    local = new_york(utc_text)
    return local.date().isoformat(), local.time() >= MARKET_CLOSE


def reaction_day(day: str, after_close: bool, sessions: list[str]) -> str | None:
    """First trading session that could price the news."""
    from bisect import bisect_left, bisect_right
    k = bisect_right(sessions, day) if after_close else bisect_left(sessions, day)
    return sessions[k] if k < len(sessions) else None


def earnings_filings(block: dict) -> list[tuple[str, bool]]:
    rows = []
    for form, items, accepted in zip(block.get('form', []), block.get('items', []), block.get('acceptanceDateTime', [])):
        if form == '8-K' and '2.02' in str(items) and accepted:
            rows.append(announcement_day(accepted))
    return rows


def fetch_symbol(session: requests.Session, cik: int, HEADERS: dict) -> list[tuple[str, bool]]:
    data = session.get(f'https://data.sec.gov/submissions/CIK{cik:010d}.json', headers=HEADERS, timeout=30).json()
    rows = earnings_filings(data['filings']['recent'])
    for extra in data['filings'].get('files', []):
        if extra.get('filingTo', '9999') < FIRST_DATE:
            continue
        time.sleep(PAUSE_SECONDS)
        rows += earnings_filings(session.get(f"https://data.sec.gov/submissions/{extra['name']}", headers=HEADERS, timeout=30).json())
    return [r for r in rows if r[0] >= FIRST_DATE]


def headers() -> dict:
    contact = str(os.getenv(CONTACT_ENV) or '').strip()
    if '@' not in contact:
        raise RuntimeError(f'Set {CONTACT_ENV} to a contact e-mail address; the SEC rejects requests without one')
    return {'User-Agent': f'swing-lab research {contact}'}


def build(symbols: list[str], sessions: list[str]) -> dict:
    session = requests.Session()
    HEADERS = headers()
    ciks = {v['ticker']: int(v['cik_str']) for v in session.get('https://www.sec.gov/files/company_tickers.json', headers=HEADERS, timeout=30).json().values()}
    dates, missing = {}, []
    for symbol in symbols:
        cik = ciks.get(symbol) or ciks.get(symbol.replace('-', '.')) or ciks.get(symbol.replace('-', ''))
        if cik is None:
            missing.append(symbol)
            continue
        try:
            filings = fetch_symbol(session, cik, HEADERS)
        except Exception:
            missing.append(symbol)
            continue
        days = sorted({d for d in (reaction_day(day, late, sessions) for day, late in filings) if d})
        if days:
            dates[symbol] = days
        time.sleep(PAUSE_SECONDS)
    return {'version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'source': 'SEC EDGAR, Form 8-K Item 2.02 acceptance times', 'meaning': 'first trading session that could react to each earnings release',
            'symbols_requested': len(symbols), 'symbols_with_dates': len(dates), 'symbols_missing': missing, 'dates': dates}


def main():
    import strategy_evolution as se
    panel = se.load_panel()
    report = build([str(s) for s in panel['symbols']], [str(d) for d in panel['dates']])
    OUT.write_text(json.dumps(report, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    counts = [len(v) for v in report['dates'].values()]
    print(json.dumps({'requested': report['symbols_requested'], 'with_dates': report['symbols_with_dates'], 'missing': len(report['symbols_missing']),
                      'median_per_symbol': sorted(counts)[len(counts) // 2] if counts else 0, 'total': sum(counts)}))


if __name__ == '__main__':
    main()
