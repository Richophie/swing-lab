from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import journal
from intraday_execution import bars_for_date, first_exit_touch, fresh_intraday_history
from market_data import fresh_price_history

ROOT = Path(__file__).parent
HISTORY_FILE = ROOT / 'static' / 'trade_history.json'


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def _save(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _entry(item: dict):
    vals = [float(v) for v in (item.get('entry_low'), item.get('entry_high')) if v is not None]
    return sum(vals) / len(vals) if vals else None


def _set_target(item: dict, day: str, target: float, quality: str, timestamp: str | None):
    entry = _entry(item)
    ret = ((target / entry) - 1.0) * 100.0 if entry else None
    item.update(
        {
            'status': '성공',
            'status_code': 'SUCCESS',
            'outcome_at': day,
            'outcome_price': round(target, 4),
            'outcome_return_pct': round(ret, 2) if ret is not None else None,
            'outcome_note': '같은 일봉에서 목표/손절을 모두 터치했지만 1분봉에서 TARGET이 먼저 확인됐습니다.',
            'intraday_resolution_quality': quality,
            'intraday_resolution_timestamp': timestamp,
        }
    )


def repair(history: dict) -> int:
    candidates = []
    for block in history.get('days') or []:
        for item in block.get('items') or []:
            if item.get('status_code') != 'STOP' or not item.get('outcome_at'):
                continue
            if item.get('intraday_resolution_quality'):
                continue
            candidates.append(item)
    repaired = 0
    by_symbol = {}
    for item in candidates:
        by_symbol.setdefault(item.get('symbol'), []).append(item)
    for symbol, rows in by_symbol.items():
        try:
            daily = fresh_price_history(symbol, '1mo')
        except Exception:
            continue
        try:
            minute = fresh_intraday_history(symbol, '7d')
        except Exception:
            minute = None
        for item in rows:
            day = str(item.get('outcome_at'))[:10]
            try:
                same = daily[[idx.strftime('%Y-%m-%d') == day for idx in daily.index]]
                if same.empty:
                    continue
                bar = same.iloc[-1]
                target, stop = float(item['target']), float(item['stop'])
                if not (float(bar['High']) >= target and float(bar['Low']) <= stop):
                    item['intraday_resolution_quality'] = 'daily_single_side_stop'
                    continue
                bars = bars_for_date(minute, day) if minute is not None else None
                resolved = first_exit_touch(bars, target=target, stop=stop) if bars is not None else None
                if resolved and resolved['side'] == 'TARGET':
                    _set_target(item, day, target, resolved['quality'], resolved['timestamp'])
                    repaired += 1
                elif resolved:
                    item['intraday_resolution_quality'] = resolved['quality']
                    item['intraday_resolution_timestamp'] = resolved['timestamp']
                    item['outcome_note'] = (
                        '같은 일봉에서 목표/손절을 모두 터치했고 1분봉에서 STOP이 먼저 확인됐습니다.'
                        if resolved['quality'] == '1m_first_touch'
                        else '같은 1분봉 안에서 목표/손절을 모두 터치해 정확한 틱 순서를 알 수 없어 STOP 우선으로 보수 처리했습니다.'
                    )
                else:
                    item['intraday_resolution_quality'] = 'daily_ambiguous_stop_fallback'
                    item['outcome_note'] = '같은 일봉 양방향 터치이나 1분봉을 확보하지 못해 STOP 우선으로 보수 처리했습니다.'
            except Exception:
                continue
    history['intraday_outcome_policy'] = (
        'same-day target+stop ambiguity uses chronological 1-minute first touch when available; '
        'only unresolved same-minute/data-missing cases fall back to stop'
    )
    return repaired


def refresh_summaries(history: dict) -> None:
    official, research = journal.summarize(history)
    history['summary'] = official
    history['research_summary'] = research
    history['intraday_repair_updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')


def main():
    history = _load(HISTORY_FILE, {'days': []})
    changed = repair(history)
    refresh_summaries(history)
    _save(HISTORY_FILE, history)
    print('intraday outcome target-first repairs', changed, 'summary refreshed')


if __name__ == '__main__':
    main()
