"""Open-market insider purchases from the SEC's quarterly Form 3/4/5 data sets (free, official).

Keeps only what the research needs: purchases (transaction code P) reported on Form 4 by
officers or directors of companies in our price panel, with the day the filing became public.

Output: static/insider_buys.json
Downloads are cached under data/insider/ (not committed) and can be deleted afterwards.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import time
import zipfile

import requests

from earnings_calendar import headers

OUT = Path('static/insider_buys.json')
CACHE = Path('data/insider')
URL = 'https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{quarter}_form345.zip'
FIRST_QUARTER = (2016, 3)
MONTHS = {m: i + 1 for i, m in enumerate(('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'))}


def iso(text: str) -> str | None:
    """'31-JAN-2024' -> '2024-01-31'."""
    try:
        day, month, year = text.strip().split('-')
        return f'{int(year):04d}-{MONTHS[month.upper()]:02d}-{int(day):02d}'
    except Exception:
        return None


def quarters(now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    last = (now.year, (now.month - 1) // 3 + 1)
    out, (year, q) = [], FIRST_QUARTER
    while (year, q) <= last:
        out.append(f'{year}q{q}')
        year, q = (year, q + 1) if q < 4 else (year + 1, 1)
    return out


def table(archive: zipfile.ZipFile, name: str):
    with archive.open(name) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding='utf-8', errors='replace'), delimiter='\t')


def purchases(archive: zipfile.ZipFile, symbols: set[str]) -> list[dict]:
    """Officer or director open-market purchases on original Form 4 filings for our symbols."""
    filings = {}
    for row in table(archive, 'SUBMISSION.tsv'):
        symbol = (row.get('ISSUERTRADINGSYMBOL') or '').strip().upper().replace('.', '-')
        if row.get('DOCUMENT_TYPE') == '4' and symbol in symbols:
            filings[row['ACCESSION_NUMBER']] = (symbol, iso(row.get('FILING_DATE') or ''))
    owners: dict[str, list[tuple[str, str]]] = {}
    for row in table(archive, 'REPORTINGOWNER.tsv'):
        if row['ACCESSION_NUMBER'] in filings:
            owners.setdefault(row['ACCESSION_NUMBER'], []).append((row.get('RPTOWNERCIK') or '', row.get('RPTOWNER_RELATIONSHIP') or ''))
    out = []
    for row in table(archive, 'NONDERIV_TRANS.tsv'):
        key = row['ACCESSION_NUMBER']
        if key not in filings or row.get('TRANS_CODE') != 'P' or row.get('TRANS_ACQUIRED_DISP_CD') != 'A':
            continue
        try:
            shares, price = float(row.get('TRANS_SHARES') or 0), float(row.get('TRANS_PRICEPERSHARE') or 0)
        except ValueError:
            continue
        who = owners.get(key) or []
        roles = ','.join(sorted({r for _, r in who}))
        symbol, filed = filings[key]
        if shares <= 0 or price <= 0 or not filed or not ('Officer' in roles or 'Director' in roles):
            continue
        out.append({'symbol': symbol, 'filed': filed, 'traded': iso(row.get('TRANS_DATE') or ''), 'owner': who[0][0] if who else '',
                    'roles': roles, 'value_usd': round(shares * price)})
    return out


def fetch(quarter: str, session: requests.Session, request_headers: dict) -> zipfile.ZipFile | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f'{quarter}_form345.zip'
    if not path.exists():
        response = session.get(URL.format(quarter=quarter), headers=request_headers, timeout=180)
        if response.status_code != 200:
            return None
        path.write_bytes(response.content)
        time.sleep(0.5)
    try:
        return zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        path.unlink(missing_ok=True)
        return None


def build(symbols: set[str]) -> dict:
    session, request_headers = requests.Session(), headers()
    rows, missing = [], []
    for quarter in quarters():
        archive = fetch(quarter, session, request_headers)
        if archive is None:
            missing.append(quarter)
            continue
        rows += purchases(archive, symbols)
    # One line per insider, company and filing day.
    merged: dict[tuple, dict] = {}
    for r in rows:
        key = (r['symbol'], r['filed'], r['owner'])
        if key in merged:
            merged[key]['value_usd'] += r['value_usd']
        else:
            merged[key] = dict(r)
    final = sorted(merged.values(), key=lambda r: (r['filed'], r['symbol'], r['owner']))
    return {'version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'source': 'SEC insider transactions data sets (Forms 3, 4, 5), transaction code P on original Form 4',
            'quarters_missing': missing, 'symbols_with_buys': len({r['symbol'] for r in final}), 'rows': len(final), 'buys': final}


def main():
    import strategy_evolution as se
    report = build({str(s) for s in se.load_panel()['symbols']})
    OUT.write_text(json.dumps(report, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('rows', 'symbols_with_buys', 'quarters_missing')}))


if __name__ == '__main__':
    main()
