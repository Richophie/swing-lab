from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

CACHE_PATH = Path(__file__).parent / 'static' / 'earnings_cache.json'
CACHE_VERSION = 1
CACHE_TTL_HOURS = 12
ERROR_RETRY_HOURS = 2
NY = ZoneInfo('America/New_York')


def _date_text(value):
    try:
        ts = pd.Timestamp(value)
        if ts.tzinfo is not None:
            ts = ts.tz_convert('UTC').tz_localize(None)
        return ts.date().isoformat()
    except Exception:
        return None


def _future_from_earnings_dates(ticker, today: str):
    try:
        d = ticker.get_earnings_dates(limit=12)
        if d is None or d.empty:
            return None, 'empty'
        dates = []
        for idx in d.index:
            text = _date_text(idx)
            if text and text >= today:
                dates.append(text)
        return (min(dates) if dates else None), 'ok'
    except Exception as exc:
        return None, f'error:{exc}'


def _future_from_calendar(ticker, today: str):
    try:
        cal = ticker.calendar
        if cal is None:
            return None, 'empty'
        value = None
        if isinstance(cal, dict):
            value = cal.get('Earnings Date') or cal.get('EarningsDate')
        elif hasattr(cal, 'loc'):
            for key in ('Earnings Date', 'EarningsDate'):
                try:
                    item = cal.loc[key]
                    value = item.iloc[0] if hasattr(item, 'iloc') else item
                    break
                except Exception:
                    pass
        vals = value if isinstance(value, (list, tuple)) else [value]
        dates = []
        for val in vals:
            text = _date_text(val)
            if text and text >= today:
                dates.append(text)
        return (min(dates) if dates else None), ('ok' if dates else 'empty')
    except Exception as exc:
        return None, f'error:{exc}'


def _choose_sources(earnings_date, calendar_date):
    if earnings_date and calendar_date:
        diff = abs((pd.Timestamp(earnings_date) - pd.Timestamp(calendar_date)).days)
        if diff <= 1:
            return min(earnings_date, calendar_date), 'confirmed', diff
        return min(earnings_date, calendar_date), 'conflicting', diff
    if earnings_date:
        return earnings_date, 'single_source', None
    if calendar_date:
        return calendar_date, 'single_source', None
    return None, 'unavailable', None


def _read_cache(path: Path = CACHE_PATH):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('cache root must be object')
        data.setdefault('version', CACHE_VERSION)
        data.setdefault('symbols', {})
        return data
    except Exception:
        return {'version': CACHE_VERSION, 'updated_at': None, 'symbols': {}}


def _write_cache(data, path: Path = CACHE_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data['version'] = CACHE_VERSION
    data['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def _age_hours(value, now_utc):
    try:
        checked = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        return max(0.0, (now_utc - checked.astimezone(timezone.utc)).total_seconds() / 3600.0)
    except Exception:
        return float('inf')


def _query_symbol(symbol: str, today: str, now_utc):
    ticker = yf.Ticker(symbol)
    earnings_date, earnings_status = _future_from_earnings_dates(ticker, today)
    calendar_date, calendar_status = _future_from_calendar(ticker, today)
    chosen, confidence, diff = _choose_sources(earnings_date, calendar_date)
    return {
        'symbol': symbol,
        'earnings_date': chosen,
        'confidence': confidence,
        'source_dates': {
            'get_earnings_dates': earnings_date,
            'calendar': calendar_date,
        },
        'source_status': {
            'get_earnings_dates': earnings_status,
            'calendar': calendar_status,
        },
        'source_day_diff': diff,
        'checked_at': now_utc.isoformat(timespec='seconds'),
        'last_attempt_at': now_utc.isoformat(timespec='seconds'),
        'stale': False,
    }


def _max_hold_days(plan):
    plan = plan or {}
    for key in ('days_max',):
        try:
            val = int(plan.get(key))
            if val > 0:
                return val
        except Exception:
            pass
    target_days = plan.get('target_days') or {}
    for key in ('days_high', 'days_max'):
        try:
            val = int(target_days.get(key))
            if val > 0:
                return val
        except Exception:
            pass
    days = plan.get('days')
    if isinstance(days, (list, tuple)) and len(days) >= 2:
        try:
            return max(1, int(days[1]))
        except Exception:
            pass
    return 5


def _risk_from_entry(entry, plan, now_utc):
    today = now_utc.astimezone(NY).date()
    date_text = entry.get('earnings_date')
    confidence = entry.get('confidence') or 'unavailable'
    stale = bool(entry.get('stale'))
    max_hold_days = _max_hold_days(plan)
    hold_calendar_days = max(3, int(math.ceil(max_hold_days * 7 / 5)) + 1)

    days_until = None
    if date_text:
        try:
            days_until = (pd.Timestamp(date_text).date() - today).days
        except Exception:
            days_until = None

    if confidence == 'conflicting':
        code, label = 'UNKNOWN', '실적일 확인 필요'
    elif days_until is None or days_until < 0:
        code, label = 'UNKNOWN', '실적일 확인 필요'
    elif days_until <= 3:
        code, label = 'IMMINENT', f'실적 {days_until}일 전'
    elif days_until <= hold_calendar_days:
        code, label = 'WITHIN_HOLD', f'보유기간 중 실적 가능 · {days_until}일'
    elif days_until <= 14:
        code, label = 'UPCOMING', f'실적 {days_until}일 전'
    else:
        code, label = 'CLEAR', f'실적까지 {days_until}일'

    return {
        'earnings_date': date_text,
        'days_until': days_until,
        'confidence': confidence,
        'stale': stale,
        'risk_code': code,
        'risk_label': label,
        'hold_calendar_days': hold_calendar_days,
        'source_dates': entry.get('source_dates') or {},
        'source_day_diff': entry.get('source_day_diff'),
        'checked_at': entry.get('checked_at'),
    }


def enrich_elite_rows(rows, now_utc=None, cache_path: Path = CACHE_PATH):
    """Attach informational earnings risk only to elite rows.

    This function never changes elite_pass, scores, BUY/TARGET/STOP or strategy
    selection. It is deliberately fail-soft: a failed refresh falls back to the
    last dated cache entry and marks it stale. Failed refreshes back off for two
    hours so a provider outage cannot slow every 30-minute scan.
    """
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today = now.astimezone(NY).date().isoformat()
    cache = _read_cache(cache_path)
    symbols_cache = cache.setdefault('symbols', {})
    queried = reused = stale_used = retry_backoff = 0
    changed = False

    for row in rows:
        if not row.get('elite_pass'):
            continue
        symbol = str(row.get('symbol') or '').upper().strip()
        if not symbol:
            continue
        existing = symbols_cache.get(symbol)
        entry = None
        if existing and _age_hours(existing.get('checked_at'), now) < CACHE_TTL_HOURS:
            entry = dict(existing)
            entry['stale'] = False
            reused += 1
        elif existing and existing.get('earnings_date') and _age_hours(existing.get('last_attempt_at'), now) < ERROR_RETRY_HOURS:
            entry = dict(existing)
            entry['stale'] = True
            stale_used += 1
            retry_backoff += 1
        else:
            queried += 1
            try:
                fresh = _query_symbol(symbol, today, now)
            except Exception as exc:
                fresh = {
                    'symbol': symbol,
                    'earnings_date': None,
                    'confidence': 'unavailable',
                    'source_dates': {},
                    'source_status': {'query': f'error:{exc}'},
                    'source_day_diff': None,
                    'checked_at': now.isoformat(timespec='seconds'),
                    'last_attempt_at': now.isoformat(timespec='seconds'),
                    'stale': False,
                }
            if fresh.get('earnings_date'):
                entry = fresh
                symbols_cache[symbol] = dict(fresh)
                changed = True
            elif existing and existing.get('earnings_date'):
                entry = dict(existing)
                entry['stale'] = True
                entry['last_attempt_at'] = now.isoformat(timespec='seconds')
                entry['refresh_error'] = fresh.get('source_status')
                symbols_cache[symbol] = dict(entry)
                stale_used += 1
                changed = True
            else:
                entry = fresh
                symbols_cache[symbol] = dict(fresh)
                changed = True

        row['event_risk'] = _risk_from_entry(entry, row.get('trade_plan'), now)

    if changed:
        _write_cache(cache, cache_path)
    return rows, {
        'elite_rows_with_event_check': sum(bool(r.get('elite_pass')) for r in rows),
        'earnings_cache_queried': queried,
        'earnings_cache_reused': reused,
        'earnings_cache_stale_used': stale_used,
        'earnings_cache_retry_backoff': retry_backoff,
        'earnings_cache_ttl_hours': CACHE_TTL_HOURS,
        'earnings_error_retry_hours': ERROR_RETRY_HOURS,
        'event_policy': 'informational only; no score, signal, BUY/TARGET/STOP or hard-gate effect',
    }
