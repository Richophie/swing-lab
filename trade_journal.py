from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import math
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).parent
SCAN_FILE = ROOT / 'static' / 'latest_scan.json'
JOURNAL_FILE = ROOT / 'static' / 'trade_history.json'
NY = ZoneInfo('America/New_York')


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def market_date_from_iso(value):
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(NY).date().isoformat()
    except Exception:
        return datetime.now(timezone.utc).astimezone(NY).date().isoformat()


def frozen_item(row, recommended_at, market_date):
    p = row.get('trade_plan') or {}
    days = p.get('target_days') or {}
    max_days = int(days.get('days_high') or 5)
    min_days = int(days.get('days_low') or 1)
    return {
        'symbol': row.get('symbol'),
        'grade': row.get('grade'),
        'score': row.get('score'),
        'strategy_name': row.get('strategy_name'),
        'strategy_id': row.get('strategy_id'),
        'strategy_reason': row.get('strategy_reason'),
        'strategy_agreement': row.get('strategy_agreement'),
        'confidence': row.get('confidence'),
        'recommended_at': recommended_at,
        'market_date': market_date,
        'entry_low': p.get('entry_low'),
        'entry_high': p.get('entry_high'),
        'target': p.get('target'),
        'stop': p.get('stop'),
        'target_pct': p.get('target_pct'),
        'stop_pct': p.get('stop_pct'),
        'target_days_low': min_days,
        'target_days_high': max_days,
        'target_reason': p.get('target_reason'),
        'stop_reason': p.get('stop_reason'),
        'risk_reward': p.get('risk_reward'),
        'status': '진행 중',
        'status_code': 'OPEN',
        'outcome_at': None,
        'outcome_price': None,
        'outcome_note': '추천 다음 거래일부터 판정합니다.',
        'bars_observed': 0,
        'best_high': None,
        'worst_low': None,
    }


def append_today(scan, journal):
    scanned_at = scan.get('scanned_at') or datetime.now(timezone.utc).isoformat(timespec='seconds')
    market_date = market_date_from_iso(scanned_at)
    days = journal.setdefault('days', [])
    day = next((d for d in days if d.get('date') == market_date), None)
    if day is None:
        day = {'date': market_date, 'created_at': scanned_at, 'updated_at': scanned_at, 'items': []}
        days.append(day)
    existing = {x.get('symbol') for x in day.get('items', [])}
    for row in scan.get('results') or []:
        if row.get('grade') not in {'S', 'A'} or not row.get('eligible', True):
            continue
        symbol = row.get('symbol')
        if not symbol or symbol in existing:
            continue
        day['items'].append(frozen_item(row, scanned_at, market_date))
        existing.add(symbol)
    day['updated_at'] = scanned_at
    days.sort(key=lambda x: x.get('date', ''), reverse=True)


def fetch_history(symbols):
    if not symbols:
        return None
    try:
        return yf.download(' '.join(symbols), period='3mo', interval='1d', auto_adjust=False,
                           group_by='ticker', threads=True, progress=False, timeout=30)
    except Exception:
        return None


def symbol_frame(bulk, symbol, count):
    try:
        d = bulk.copy() if count == 1 else bulk[symbol].copy()
        d = d.dropna(subset=['High', 'Low', 'Close']).copy()
        idx = pd.to_datetime(d.index)
        if getattr(idx, 'tz', None) is not None:
            idx = idx.tz_localize(None)
        d.index = idx
        return d
    except Exception:
        return pd.DataFrame()


def evaluate_item(item, d):
    if item.get('status_code') in {'SUCCESS', 'FAIL', 'HOLD'}:
        return
    target = item.get('target')
    stop = item.get('stop')
    if target is None or stop is None or d.empty:
        return
    rec_date = pd.Timestamp(item['market_date'])
    # Strictly after signal date so the same day's pre-signal high/low cannot contaminate outcomes.
    future = d[d.index.normalize() > rec_date.normalize()]
    max_days = max(1, int(item.get('target_days_high') or 5))
    window = future.iloc[:max_days]
    item['bars_observed'] = int(len(window))
    if len(window):
        item['best_high'] = round(float(window['High'].max()), 4)
        item['worst_low'] = round(float(window['Low'].min()), 4)

    for idx, row in window.iterrows():
        hit_target = float(row['High']) >= float(target)
        hit_stop = float(row['Low']) <= float(stop)
        if hit_target and hit_stop:
            item.update({
                'status': '실패', 'status_code': 'FAIL', 'outcome_at': idx.date().isoformat(),
                'outcome_price': stop,
                'outcome_note': '같은 일봉에서 목표가와 손절가를 모두 터치해 선후를 알 수 없어 보수적으로 실패 처리했습니다.'
            })
            return
        if hit_stop:
            item.update({
                'status': '실패', 'status_code': 'FAIL', 'outcome_at': idx.date().isoformat(),
                'outcome_price': stop, 'outcome_note': '목표가보다 손절가를 먼저 터치했습니다.'
            })
            return
        if hit_target:
            item.update({
                'status': '성공', 'status_code': 'SUCCESS', 'outcome_at': idx.date().isoformat(),
                'outcome_price': target, 'outcome_note': '목표기간 안에 목표가를 달성했습니다.'
            })
            return

    # Enough completed trading bars have elapsed and neither boundary was reached.
    if len(future) >= max_days:
        last = window.iloc[-1]
        item.update({
            'status': '홀딩', 'status_code': 'HOLD', 'outcome_at': window.index[-1].date().isoformat(),
            'outcome_price': round(float(last['Close']), 4),
            'outcome_note': '목표기간 안에 목표가와 손절가 모두 닿지 않았습니다.'
        })


def evaluate_all(journal):
    open_items = []
    for day in journal.get('days', []):
        for item in day.get('items', []):
            if item.get('status_code') not in {'SUCCESS', 'FAIL', 'HOLD'} and item.get('symbol'):
                open_items.append(item)
    symbols = sorted({x['symbol'] for x in open_items})
    bulk = fetch_history(symbols)
    if bulk is None:
        return
    for item in open_items:
        evaluate_item(item, symbol_frame(bulk, item['symbol'], len(symbols)))


def summary(journal):
    items = [x for d in journal.get('days', []) for x in d.get('items', [])]
    closed = [x for x in items if x.get('status_code') in {'SUCCESS', 'FAIL', 'HOLD'}]
    successes = sum(x.get('status_code') == 'SUCCESS' for x in closed)
    fails = sum(x.get('status_code') == 'FAIL' for x in closed)
    holds = sum(x.get('status_code') == 'HOLD' for x in closed)
    decisive = successes + fails
    return {
        'total_signals': len(items),
        'closed_signals': len(closed),
        'success': successes,
        'fail': fails,
        'hold': holds,
        'success_rate_closed_pct': round(successes / len(closed) * 100, 1) if closed else None,
        'win_rate_ex_hold_pct': round(successes / decisive * 100, 1) if decisive else None,
    }


def main():
    scan = load_json(SCAN_FILE, {})
    journal = load_json(JOURNAL_FILE, {'version': '1.0', 'days': []})
    append_today(scan, journal)
    evaluate_all(journal)
    journal['version'] = '1.0'
    journal['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    journal['summary'] = summary(journal)
    save_json(JOURNAL_FILE, journal)
    print('saved', JOURNAL_FILE, journal['summary'])


if __name__ == '__main__':
    main()
