from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import csv
import json
from pathlib import Path

TARGET_START = date(2017, 1, 1)
TARGET_END = date(2026, 8, 13)
DEFAULT_MIN_ACTIVE = 40
VERIFIED = 'VERIFIED'


@dataclass(frozen=True)
class MembershipWindow:
    security_id: str
    symbol: str
    start_date: date
    end_date: date | None
    source_id: str
    exchange: str = ''
    security_name: str = ''

    def active_on(self, day: date) -> bool:
        """Membership dates are inclusive on both ends.

        A missing end_date means membership remains active through the source's
        declared coverage end. Candidate eligibility must check BOTH signal and
        next-open entry dates so a name removed overnight cannot enter afterward.
        """
        return self.start_date <= day and (self.end_date is None or day <= self.end_date)


def _day(value: str | date | None, *, required: bool = False) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or '').strip()
    if not text:
        if required:
            raise ValueError('missing required ISO date')
        return None
    return date.fromisoformat(text[:10])


def _norm_symbol(value: str) -> str:
    symbol = str(value or '').strip().upper().replace('.', '-')
    if not symbol:
        raise ValueError('missing symbol')
    return symbol


def load_manifest(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_membership_csv(path: str | Path) -> list[MembershipWindow]:
    rows: list[MembershipWindow] = []
    with Path(path).open('r', encoding='utf-8-sig', newline='') as handle:
        for i, raw in enumerate(csv.DictReader(handle), start=2):
            if not any(str(v or '').strip() for v in raw.values()):
                continue
            try:
                security_id = str(raw.get('security_id') or '').strip()
                source_id = str(raw.get('source_id') or '').strip()
                if not security_id:
                    raise ValueError('missing security_id; ticker alone is not a stable PIT identifier')
                if not source_id:
                    raise ValueError('missing source_id')
                start = _day(raw.get('start_date'), required=True)
                end = _day(raw.get('end_date'))
                if end is not None and end < start:
                    raise ValueError('end_date precedes start_date')
                rows.append(MembershipWindow(
                    security_id=security_id,
                    symbol=_norm_symbol(raw.get('symbol') or ''),
                    start_date=start,
                    end_date=end,
                    source_id=source_id,
                    exchange=str(raw.get('exchange') or '').strip().upper(),
                    security_name=str(raw.get('security_name') or '').strip(),
                ))
            except Exception as exc:
                raise ValueError(f'{Path(path)} line {i}: {exc}') from exc
    validate_windows(rows)
    return rows


def _end(window: MembershipWindow) -> date:
    return window.end_date or date.max


def _overlap(a: MembershipWindow, b: MembershipWindow) -> bool:
    return max(a.start_date, b.start_date) <= min(_end(a), _end(b))


def validate_windows(windows: list[MembershipWindow]) -> None:
    """Reject ambiguous historical identities instead of guessing.

    - one stable security_id cannot have overlapping symbol windows
    - one ticker cannot represent two different securities at the same time
    - exact duplicate rows are invalid
    """
    seen = set()
    by_security: dict[str, list[MembershipWindow]] = {}
    by_symbol: dict[str, list[MembershipWindow]] = {}
    for w in windows:
        key = (w.security_id, w.symbol, w.start_date, w.end_date, w.source_id)
        if key in seen:
            raise ValueError(f'duplicate membership window: {key}')
        seen.add(key)
        by_security.setdefault(w.security_id, []).append(w)
        by_symbol.setdefault(w.symbol, []).append(w)

    for security_id, items in by_security.items():
        ordered = sorted(items, key=lambda x: (x.start_date, _end(x), x.symbol))
        for prev, cur in zip(ordered, ordered[1:]):
            if _overlap(prev, cur):
                raise ValueError(
                    f'overlapping windows for security_id {security_id}: '
                    f'{prev.symbol} {prev.start_date}..{prev.end_date} vs '
                    f'{cur.symbol} {cur.start_date}..{cur.end_date}'
                )

    for symbol, items in by_symbol.items():
        ordered = sorted(items, key=lambda x: (x.start_date, _end(x), x.security_id))
        for i, first in enumerate(ordered):
            for second in ordered[i + 1:]:
                if second.start_date > _end(first):
                    break
                if first.security_id != second.security_id and _overlap(first, second):
                    raise ValueError(
                        f'ticker {symbol} maps to multiple security_ids during overlapping dates: '
                        f'{first.security_id} and {second.security_id}'
                    )


def active_windows(day: date, windows: list[MembershipWindow]) -> list[MembershipWindow]:
    return sorted((w for w in windows if w.active_on(day)), key=lambda x: (x.symbol, x.security_id))


def symbols_on(day: date, windows: list[MembershipWindow]) -> list[str]:
    return sorted({w.symbol for w in active_windows(day, windows)})


def window_for(security_id: str, day: date, windows: list[MembershipWindow]) -> MembershipWindow | None:
    matches = [w for w in windows if w.security_id == security_id and w.active_on(day)]
    if len(matches) > 1:
        raise ValueError(f'ambiguous membership for {security_id} on {day}')
    return matches[0] if matches else None


def eligible_for_signal_and_entry(
    security_id: str,
    signal_day: date,
    entry_day: date,
    windows: list[MembershipWindow],
) -> bool:
    signal_window = window_for(security_id, signal_day, windows)
    entry_window = window_for(security_id, entry_day, windows)
    return bool(signal_window and entry_window)


def _source_ready(source: dict, *, kind: str, target_start: date, target_end: date) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if str(source.get('status') or '').upper() != VERIFIED:
        reasons.append(f'{kind} source status is not VERIFIED')
    coverage = source.get('coverage') or {}
    start = _day(coverage.get('start'))
    end = _day(coverage.get('end'))
    if start is None or start > target_start:
        reasons.append(f'{kind} source does not cover target start {target_start}')
    if end is None or end < target_end:
        reasons.append(f'{kind} source does not cover target end {target_end}')

    required = {
        'membership': ('includes_inactive', 'stable_security_ids', 'ticker_history'),
        'prices': ('includes_inactive', 'daily_ohlcv', 'corporate_action_adjustment'),
    }[kind]
    for key in required:
        if source.get(key) is not True:
            reasons.append(f'{kind} source missing required capability: {key}')
    return not reasons, reasons


def month_starts(start: date, end: date) -> list[date]:
    out: list[date] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(date(y, m, 1))
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return out


def audit_dataset(
    manifest: dict,
    windows: list[MembershipWindow],
    *,
    target_start: date = TARGET_START,
    target_end: date = TARGET_END,
    min_active: int = DEFAULT_MIN_ACTIVE,
) -> dict:
    """Return a strict readiness report.

    PIT is ready only when membership AND inactive-security OHLCV sources are
    verified for the full target interval and membership coverage never falls
    below min_active at monthly checkpoints. There is intentionally no fallback
    to today's screener/current constituents.
    """
    validate_windows(windows)
    membership = manifest.get('membership_source') or {}
    prices = manifest.get('price_source') or {}
    m_ok, m_reasons = _source_ready(membership, kind='membership', target_start=target_start, target_end=target_end)
    p_ok, p_reasons = _source_ready(prices, kind='prices', target_start=target_start, target_end=target_end)

    reasons = [*m_reasons, *p_reasons]
    if not windows:
        reasons.append('membership dataset is empty')

    snapshots = []
    for day in month_starts(target_start, target_end):
        count = len(active_windows(day, windows))
        snapshots.append({'date': day.isoformat(), 'active_count': count})
        if count < min_active:
            reasons.append(f'active membership below {min_active} on {day}: {count}')

    prohibited = manifest.get('prohibited_fallbacks') or []
    fallback_guard = bool(manifest.get('strict_no_current_universe_fallback'))
    if not fallback_guard:
        reasons.append('strict_no_current_universe_fallback is not enabled')

    security_ids = {w.security_id for w in windows}
    symbols = {w.symbol for w in windows}
    inactive_windows = sum(w.end_date is not None and w.end_date < target_end for w in windows)
    ready = bool(m_ok and p_ok and windows and fallback_guard and not reasons)
    return {
        'version': 1,
        'ready': ready,
        'status': 'READY_FOR_PIT_REPLAY' if ready else 'BLOCKED_INCOMPLETE_PIT_DATA',
        'target_start': target_start.isoformat(),
        'target_end': target_end.isoformat(),
        'min_active_required': min_active,
        'window_count': len(windows),
        'security_id_count': len(security_ids),
        'ticker_count': len(symbols),
        'historically_ended_window_count': inactive_windows,
        'membership_source_ready': m_ok,
        'price_source_ready': p_ok,
        'strict_no_current_universe_fallback': fallback_guard,
        'prohibited_fallbacks': prohibited,
        'monthly_coverage': snapshots,
        'blocking_reasons': list(dict.fromkeys(reasons)),
        'methodology': {
            'membership_end_inclusive': True,
            'signal_and_entry_must_both_be_members': True,
            'ticker_is_not_security_identity': True,
            'stable_security_id_required': True,
            'current_universe_fallback_allowed': False,
        },
    }
