from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).parent
FX_FILE = ROOT / 'static' / 'fx_cache.json'


def _valid(v) -> bool:
    try:
        return 500 < float(v) < 3000
    except Exception:
        return False


def _last_close(frame) -> float:
    if frame is None or frame.empty:
        raise ValueError('USD/KRW 데이터가 비어 있습니다')
    close = frame['Close']
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    value = float(close.dropna().iloc[-1])
    if not _valid(value):
        raise ValueError(f'USD/KRW 값 범위 오류: {value}')
    return round(value, 2)


def refresh() -> dict:
    previous = {}
    try:
        previous = json.loads(FX_FILE.read_text(encoding='utf-8'))
    except Exception:
        previous = {}

    try:
        frame = yf.download(
            'KRW=X',
            period='5d',
            interval='1d',
            auto_adjust=False,
            progress=False,
            timeout=8,
        )
        value = _last_close(frame)
        payload = {
            'usdkrw': value,
            'source': 'yfinance_scan_cache',
            'updated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        }
        FX_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        return payload
    except Exception as exc:
        if _valid(previous.get('usdkrw')):
            print('FX refresh failed; keeping previous cache:', exc)
            return previous
        raise


if __name__ == '__main__':
    print(refresh())
