from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path

import pandas as pd
import yfinance as yf

OUT = Path('static/global_flow_map.json')

SECTORS = {
    'XLK': ('기술', 'Technology'),
    'XLC': ('커뮤니케이션', 'Communication Services'),
    'XLY': ('경기소비재', 'Consumer Discretionary'),
    'XLP': ('필수소비재', 'Consumer Staples'),
    'XLF': ('금융', 'Financials'),
    'XLV': ('헬스케어', 'Health Care'),
    'XLI': ('산업재', 'Industrials'),
    'XLB': ('소재', 'Materials'),
    'XLE': ('에너지', 'Energy'),
    'XLU': ('유틸리티', 'Utilities'),
    'XLRE': ('부동산', 'Real Estate'),
}

REGIONS = {
    'SPY': ('미국', 'United States'),
    'VGK': ('유럽', 'Europe'),
    'EWJ': ('일본', 'Japan'),
    'MCHI': ('중국', 'China'),
    'INDA': ('인도', 'India'),
    'EWY': ('한국', 'South Korea'),
    'EWT': ('대만', 'Taiwan'),
    'EEM': ('신흥국', 'Emerging Markets'),
    'VEA': ('선진국 ex-US', 'Developed ex-US'),
    'EWZ': ('브라질', 'Brazil'),
}

BENCHMARKS = {'sector': 'SPY', 'region': 'ACWI'}
ALL_TICKERS = sorted(set(SECTORS) | set(REGIONS) | {'ACWI'})


def _num(value, default=0.0):
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _ret(series: pd.Series, days: int) -> float:
    s = series.dropna()
    if len(s) <= days:
        return 0.0
    a, b = _num(s.iloc[-days - 1]), _num(s.iloc[-1])
    return b / a - 1.0 if a > 0 else 0.0


def _ticker_frame(raw: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        level0 = set(map(str, raw.columns.get_level_values(0)))
        level1 = set(map(str, raw.columns.get_level_values(1)))
        if ticker in level0:
            frame = raw[ticker].copy()
        elif ticker in level1:
            frame = raw.xs(ticker, axis=1, level=1).copy()
        else:
            return pd.DataFrame()
    else:
        frame = raw.copy()
    return frame.dropna(how='all')


def _metrics(frame: pd.DataFrame) -> dict | None:
    if frame.empty or 'Close' not in frame or len(frame['Close'].dropna()) < 25:
        return None
    close = frame['Close'].dropna()
    volume = frame['Volume'].dropna() if 'Volume' in frame else pd.Series(dtype=float)
    vol5 = _num(volume.tail(5).mean()) if len(volume) >= 5 else 0.0
    vol20 = _num(volume.tail(20).mean()) if len(volume) >= 20 else 0.0
    vol_ratio = vol5 / vol20 if vol20 > 0 else 1.0
    as_of = close.index[-1]
    if hasattr(as_of, 'date'):
        as_of = as_of.date().isoformat()
    else:
        as_of = str(as_of)[:10]
    return {
        'as_of': as_of,
        'close': round(_num(close.iloc[-1]), 4),
        'return_1d_pct': round(_ret(close, 1) * 100.0, 3),
        'return_5d_pct': round(_ret(close, 5) * 100.0, 3),
        'return_20d_pct': round(_ret(close, 20) * 100.0, 3),
        'volume_ratio_5v20': round(vol_ratio, 3),
    }


def _percentile(values: list[float], value: float) -> float:
    if not values:
        return 0.5
    ordered = sorted(values)
    below = sum(x < value for x in ordered)
    equal = sum(x == value for x in ordered)
    return (below + equal * 0.5) / len(ordered)


def _score_group(rows: list[dict], benchmark: dict) -> list[dict]:
    bench5 = _num(benchmark.get('return_5d_pct'))
    bench20 = _num(benchmark.get('return_20d_pct'))
    for row in rows:
        row['relative_5d_pct'] = round(_num(row['return_5d_pct']) - bench5, 3)
        row['relative_20d_pct'] = round(_num(row['return_20d_pct']) - bench20, 3)
        row['acceleration_pct'] = round(row['relative_5d_pct'] - row['relative_20d_pct'] / 4.0, 3)

    rel5 = [r['relative_5d_pct'] for r in rows]
    rel20 = [r['relative_20d_pct'] for r in rows]
    accel = [r['acceleration_pct'] for r in rows]
    volumes = [math.log(max(0.25, min(4.0, _num(r['volume_ratio_5v20'], 1.0)))) for r in rows]

    for row in rows:
        vol_value = math.log(max(0.25, min(4.0, _num(row['volume_ratio_5v20'], 1.0))))
        rank_mix = (
            0.35 * _percentile(rel5, row['relative_5d_pct'])
            + 0.35 * _percentile(rel20, row['relative_20d_pct'])
            + 0.15 * _percentile(accel, row['acceleration_pct'])
            + 0.15 * _percentile(volumes, vol_value)
        )
        score = (rank_mix - 0.5) * 200.0
        row['flow_score'] = round(score, 1)
        if row['relative_20d_pct'] >= 0 and row['acceleration_pct'] >= 0:
            quadrant = 'leading'
        elif row['relative_20d_pct'] >= 0:
            quadrant = 'cooling'
        elif row['acceleration_pct'] >= 0:
            quadrant = 'improving'
        else:
            quadrant = 'lagging'
        row['quadrant'] = quadrant
        row['heat'] = 'hot' if score >= 35 else 'warm' if score >= 10 else 'cold' if score <= -35 else 'cool' if score <= -10 else 'neutral'

    return sorted(rows, key=lambda x: x['flow_score'], reverse=True)


def _build_rows(raw: pd.DataFrame, mapping: dict[str, tuple[str, str]], benchmark_metrics: dict, group: str) -> list[dict]:
    rows = []
    for ticker, names in mapping.items():
        metric = _metrics(_ticker_frame(raw, ticker))
        if not metric:
            continue
        rows.append({'ticker': ticker, 'name_ko': names[0], 'name_en': names[1], 'group': group, **metric})
    return _score_group(rows, benchmark_metrics) if rows else []


def _pulse(sectors: list[dict], regions: list[dict]) -> dict:
    all_rows = sectors + regions
    positive = sum(1 for r in all_rows if _num(r.get('flow_score')) > 10)
    negative = sum(1 for r in all_rows if _num(r.get('flow_score')) < -10)
    if positive >= negative * 1.6 and positive >= 5:
        state = 'risk_on'
    elif negative >= positive * 1.6 and negative >= 5:
        state = 'risk_off'
    else:
        state = 'mixed'
    return {
        'state': state,
        'positive_assets': positive,
        'negative_assets': negative,
        'top_sectors': [r['ticker'] for r in sectors[:3]],
        'weak_sectors': [r['ticker'] for r in sectors[-3:]],
        'top_regions': [r['ticker'] for r in regions[:3]],
    }


def generate() -> dict:
    raw = yf.download(
        ALL_TICKERS,
        period='1y',
        interval='1d',
        auto_adjust=True,
        group_by='ticker',
        threads=True,
        progress=False,
    )
    spy = _metrics(_ticker_frame(raw, 'SPY'))
    acwi = _metrics(_ticker_frame(raw, 'ACWI'))
    if not spy or not acwi:
        raise RuntimeError('benchmark data unavailable')

    sectors = _build_rows(raw, SECTORS, spy, 'sector')
    regions = _build_rows(raw, REGIONS, acwi, 'region')
    if len(sectors) < 8 or len(regions) < 6:
        raise RuntimeError(f'insufficient flow universe: sectors={len(sectors)} regions={len(regions)}')

    return {
        'ready': True,
        'version': 1,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'method': {
            'label': '가격·거래량 기반 Flow Proxy',
            'not_fund_flow': True,
            'trade_signal': False,
            'sector_benchmark': 'SPY',
            'region_benchmark': 'ACWI',
            'score': 'peer percentile mix: 35% 5d relative strength + 35% 20d relative strength + 15% acceleration + 15% 5d/20d volume ratio',
            'rotation_x': '20d relative strength',
            'rotation_y': '5d relative strength minus one quarter of 20d relative strength',
            'timing_note': '각 ETF의 최근 이용 가능한 종가 기준이며 지역별 거래소 마감시각은 서로 다를 수 있음',
        },
        'benchmarks': {'SPY': spy, 'ACWI': acwi},
        'pulse': _pulse(sectors, regions),
        'sectors': sectors,
        'regions': regions,
    }


def main() -> None:
    try:
        data = generate()
        OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        print('global flow map', data['pulse']['state'], len(data['sectors']), len(data['regions']))
    except Exception as exc:
        print('global flow map warning:', exc)
        if OUT.exists():
            print('keeping previous global flow cache')
            return
        OUT.write_text(json.dumps({
            'ready': False,
            'version': 1,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'error': str(exc),
            'method': {'not_fund_flow': True, 'trade_signal': False},
        }, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
