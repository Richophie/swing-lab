from __future__ import annotations

EVENT_CODES = {'IMMINENT','WITHIN_HOLD','UPCOMING','CLEAR','UNKNOWN'}


def snapshot_event_risk(event_risk) -> dict:
    """Freeze the informational event context that existed when a signal/order was created.

    This is observational metadata only. It must never be fed back into signal,
    score, BUY/TARGET/STOP or order sizing decisions.
    """
    er = event_risk or {}
    code = str(er.get('risk_code') or 'UNKNOWN').upper()
    if code not in EVENT_CODES:
        code = 'UNKNOWN'
    return {
        'risk_code': code,
        'risk_label': er.get('risk_label'),
        'earnings_date': er.get('earnings_date'),
        'days_until': er.get('days_until'),
        'confidence': er.get('confidence') or 'unavailable',
        'stale': bool(er.get('stale')),
        'hold_calendar_days': er.get('hold_calendar_days'),
        'source_day_diff': er.get('source_day_diff'),
        'checked_at': er.get('checked_at'),
    }


def event_bucket(item: dict) -> str:
    snap = item.get('event_risk_snapshot') or {}
    code = str(snap.get('risk_code') or '').upper()
    return code if code in EVENT_CODES else 'LEGACY_UNTRACKED'
