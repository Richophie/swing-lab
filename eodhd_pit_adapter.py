from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import argparse
import json
import os
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).parent
OUT = ROOT / 'static' / 'eodhd_pit_probe.json'
BASE_URL = 'https://eodhd.com/api'
TOKEN_ENV = 'EODHD_API_TOKEN'
INDEX_CODE = 'GSPC.INDX'
TARGET_START = date(2017, 1, 1)
TARGET_END = date(2026, 8, 13)
WARMUP_DAYS = 420
MIN_DAILY_ROWS = 205
END_TOLERANCE_DAYS = 15


@dataclass(frozen=True)
class HistoricalComponent:
    code: str
    name: str
    start_date: date
    end_date: date | None
    is_active_now: bool
    is_delisted: bool
    exchange: str = 'US'

    @property
    def vendor_symbol(self) -> str:
        code = self.code.strip().upper()
        if '.' in code:
            return code
        exchange = (self.exchange or 'US').strip().upper()
        return f'{code}.{exchange}'


def _day(value: Any, required: bool = False) -> date | None:
    text = str(value or '').strip()
    if not text:
        if required:
            raise ValueError('missing date')
        return None
    return date.fromisoformat(text[:10])


def _truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or '').strip().lower() in {'1', 'true', 'yes', 'y'}


def _records(value: Any) -> list[dict]:
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        # EODHD filtered responses are commonly numeric-keyed dictionaries.
        if any(k in value for k in ('Code', 'StartDate', 'EndDate')):
            return [value]
        return [x for x in value.values() if isinstance(x, dict)]
    return []


def parse_historical_components(payload: Any) -> list[HistoricalComponent]:
    if isinstance(payload, dict) and payload.get('error'):
        raise ValueError(f"EODHD error: {payload.get('error')}")
    raw = payload.get('HistoricalTickerComponents') if isinstance(payload, dict) and 'HistoricalTickerComponents' in payload else payload
    out: list[HistoricalComponent] = []
    for item in _records(raw):
        code = str(item.get('Code') or item.get('code') or '').strip().upper()
        if not code:
            continue
        start = _day(item.get('StartDate') or item.get('start_date'), required=True)
        end = _day(item.get('EndDate') or item.get('end_date'))
        if end is not None and end < start:
            raise ValueError(f'{code}: EndDate before StartDate')
        out.append(HistoricalComponent(
            code=code,
            name=str(item.get('Name') or item.get('name') or '').strip(),
            start_date=start,
            end_date=end,
            is_active_now=_truth(item.get('IsActiveNow') if 'IsActiveNow' in item else item.get('is_active_now')),
            is_delisted=_truth(item.get('IsDelisted') if 'IsDelisted' in item else item.get('is_delisted')),
            exchange=str(item.get('Exchange') or item.get('exchange') or 'US').strip().upper() or 'US',
        ))
    out.sort(key=lambda x: (x.start_date, x.code, x.end_date or date.max))
    if not out:
        raise ValueError('EODHD HistoricalTickerComponents response contained no usable records')
    return out


def parse_eod_rows(payload: Any) -> list[dict]:
    if isinstance(payload, dict) and payload.get('error'):
        raise ValueError(f"EODHD error: {payload.get('error')}")
    rows = _records(payload)
    out = []
    for row in rows:
        d = _day(row.get('date'))
        if d is None:
            continue
        try:
            out.append({
                'date': d,
                'open': float(row.get('open')),
                'high': float(row.get('high')),
                'low': float(row.get('low')),
                'close': float(row.get('close')),
                'adjusted_close': float(row.get('adjusted_close') or row.get('adjustedClose') or row.get('close')),
                'volume': float(row.get('volume') or 0),
            })
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: x['date'])
    return out


class EODHDPITClient:
    def __init__(self, token: str, *, session: requests.Session | None = None, timeout: int = 30):
        token = str(token or '').strip()
        if not token:
            raise ValueError(f'{TOKEN_ENV} is required')
        self.token = token
        self.session = session or requests.Session()
        self.timeout = timeout

    def _get(self, path: str, **params) -> Any:
        query = {'api_token': self.token, 'fmt': 'json', **params}
        response = self.session.get(f'{BASE_URL}/{path.lstrip("/")}', params=query, timeout=self.timeout)
        response.raise_for_status()
        try:
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(f'EODHD returned non-JSON response for {path}') from exc
        if isinstance(payload, dict) and (payload.get('error') or payload.get('message') == 'Forbidden'):
            raise RuntimeError(f'EODHD API error for {path}: {payload.get("error") or payload.get("message")}')
        return payload

    def historical_sp500_components(self) -> list[HistoricalComponent]:
        payload = self._get(f'fundamentals/{INDEX_CODE}', filter='HistoricalTickerComponents')
        return parse_historical_components(payload)

    def eod(self, vendor_symbol: str, start: date, end: date) -> list[dict]:
        payload = self._get(
            f'eod/{vendor_symbol}',
            **{'from': start.isoformat(), 'to': end.isoformat(), 'period': 'd'},
        )
        return parse_eod_rows(payload)


def component_probe_window(component: HistoricalComponent) -> tuple[date, date]:
    end = component.end_date or TARGET_END
    start = max(date(1900, 1, 1), end - timedelta(days=WARMUP_DAYS))
    return start, end


def eod_coverage(rows: list[dict], expected_end: date) -> dict:
    before = [row for row in rows if row['date'] <= expected_end]
    if not before:
        return {'rows': 0, 'last_date': None, 'has_warmup': False, 'near_end': False, 'usable': False}
    last = max(row['date'] for row in before)
    warm = len(before) >= MIN_DAILY_ROWS
    near = last >= expected_end - timedelta(days=END_TOLERANCE_DAYS)
    return {
        'rows': len(before),
        'last_date': last.isoformat(),
        'has_warmup': warm,
        'near_end': near,
        'usable': bool(warm and near),
    }


def choose_probe_components(components: list[HistoricalComponent], limit: int) -> list[HistoricalComponent]:
    former = [
        c for c in components
        if c.end_date is not None and c.end_date >= TARGET_START and c.start_date <= TARGET_END
    ]
    # Delisted first, then most recent removals. This deliberately stresses the exact gap
    # that Yahoo could not cover; it is a source-capability probe, not performance research.
    former.sort(key=lambda c: (not c.is_delisted, -(c.end_date.toordinal() if c.end_date else 0), c.code))
    return former[:max(1, int(limit))]


def run_probe(client: EODHDPITClient, *, limit: int = 25) -> dict:
    components = client.historical_sp500_components()
    probe = choose_probe_components(components, limit)
    results = []
    for component in probe:
        start, end = component_probe_window(component)
        try:
            rows = client.eod(component.vendor_symbol, start, end)
            coverage = eod_coverage(rows, end)
            error = None
        except Exception as exc:
            coverage = {'rows': 0, 'last_date': None, 'has_warmup': False, 'near_end': False, 'usable': False}
            error = str(exc)
        results.append({
            'code': component.code,
            'vendor_symbol': component.vendor_symbol,
            'name': component.name,
            'start_date': component.start_date.isoformat(),
            'end_date': component.end_date.isoformat() if component.end_date else None,
            'is_delisted': component.is_delisted,
            'coverage': coverage,
            'error': error,
        })

    usable = sum(1 for x in results if x['coverage']['usable'])
    delisted = sum(1 for c in components if c.is_delisted)
    former = sum(1 for c in components if c.end_date is not None and c.end_date >= TARGET_START)
    payload = {
        'version': 1,
        'status': 'EODHD_SOURCE_PROBE_ONLY',
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'index': INDEX_CODE,
        'historical_component_count': len(components),
        'former_component_count_since_2017': former,
        'vendor_marked_delisted_component_count': delisted,
        'probe_count': len(results),
        'probe_usable_count': usable,
        'probe_usable_pct': round(usable / len(results) * 100, 2) if results else 0.0,
        'probe_results': results,
        'strict_pit_source_verified': False,
        'source_manifest_mutated': False,
        'production_main_picker_mutated': False,
        'forward_challengers_mutated': False,
        'raw_vendor_data_committed': False,
        'notes': [
            'This probe intentionally does not mark the strict PIT manifest VERIFIED.',
            'Vendor membership boundary semantics, symbol-change continuity and licensing must be reviewed before full replay ingestion.',
            'Only aggregate/sample diagnostics may be written to the public repository; licensed raw vendor datasets must not be committed.',
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('probe',), nargs='?', default='probe')
    parser.add_argument('--limit', type=int, default=25)
    args = parser.parse_args()
    token = os.getenv(TOKEN_ENV, '').strip()
    if not token:
        raise SystemExit(f'{TOKEN_ENV} is not configured; no network/vendor request was made')
    payload = run_probe(EODHDPITClient(token), limit=args.limit)
    print(json.dumps({
        'status': payload['status'],
        'historical_component_count': payload['historical_component_count'],
        'former_component_count_since_2017': payload['former_component_count_since_2017'],
        'probe_count': payload['probe_count'],
        'probe_usable_pct': payload['probe_usable_pct'],
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
