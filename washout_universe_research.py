"""Do the washout-rebound rules also work on mid and small caps?

The rules that passed the evolution gates were found on S&P 500 members. This replays
their frozen thresholds, unchanged, on today's S&P MidCap 400 and SmallCap 600 members.

Big caveat: there is no free history of who was in those indexes, so this universe is
"companies that are in the index today". A beaten-down small company that later went
bankrupt is missing, and that flatters exactly this kind of rule. Read the result as an
upper bound. Research only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path

import numpy as np
import requests

import strategy_evolution as se
from washout_risk_research import BASE_RULES, SEGMENTS, stats

OUT = Path('static/washout_universe_research.json')
SOURCES = {
    'midcap_400': 'https://en.wikipedia.org/wiki/List_of_S%26P_400_companies',
    'smallcap_600': 'https://en.wikipedia.org/wiki/List_of_S%26P_600_companies',
}
# The evolution filter (about $20M a day) and a looser one that small caps can meet.
LIQUIDITY_FLOORS = {'usd_20m_per_day': 7.3, 'usd_5m_per_day': 6.7}


class _Tables(HTMLParser):
    """Rows of every HTML table as lists of cell text. Standard library only."""

    def __init__(self):
        super().__init__()
        self.tables, self._row, self._cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.tables.append([])
        elif tag == 'tr' and self.tables:
            self._row = []
        elif tag in ('td', 'th') and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self._cell is not None and self._row is not None:
            self._row.append(''.join(self._cell).strip()); self._cell = None
        elif tag == 'tr' and self._row is not None and self.tables:
            self.tables[-1].append(self._row); self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def parse_members(html: str) -> list[str]:
    """Tickers from the first large table that has a symbol column."""
    parser = _Tables()
    parser.feed(html)
    for rows in parser.tables:
        if len(rows) < 300:
            continue
        header = [c.lower() for c in rows[0]]
        column = next((i for i, c in enumerate(header) if c in ('symbol', 'ticker symbol', 'ticker')), None)
        if column is None:
            continue
        symbols = {r[column].replace('.', '-') for r in rows[1:] if len(r) > column and r[column]}
        return sorted(x for x in symbols if x.replace('-', '').isalnum() and len(x) <= 6)
    raise RuntimeError('no constituent table found')


def fetch_members(url: str) -> list[str]:
    return parse_members(requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0 swing-lab research'}).text)


def build_panel(frames: dict) -> dict:
    from indicator_library import add_panel_features, market_features
    from market_data import indicators, load_price_history
    try:
        vix = load_price_history('^VIX', 'max')
    except Exception:
        vix = None
    panel = se.panel_from_frames(frames, market_features(load_price_history('SPY', 'max'), vix), se.evolution_features, indicators)
    add_panel_features(panel['features'], np.isfinite(panel['close']))
    panel['feature_names'] = list(panel['features'])
    return panel


def evaluate(ctx: se.Context, ledger: dict, columns: np.ndarray, floor: float) -> dict:
    ctx.tradable = (ctx.panel['close'] >= se.MIN_PRICE) & (ctx.features['dollar_volume_log'] >= floor)
    out = {}
    for candidate in ledger.get('family_candidates') or []:
        if candidate['name'] not in BASE_RULES:
            continue
        genome, signals = se.frozen_signals(ctx, candidate)
        returns = ctx.returns(genome)
        taken = signals & np.isfinite(returns)
        taken[:, ~columns] = False
        rows_by = {name: ctx.rows(*span) for name, span in SEGMENTS.items()}
        out[candidate['name']] = {
            **{name: {**stats(returns[rows][taken[rows]]), 't_stat': se.segment_stats(returns, taken, rows, columns, 1.0).get('t_stat')} for name, rows in rows_by.items()},
            'all_years': stats(returns[taken]),
        }
    return out


def build(panel: dict, groups: dict[str, set], ledger: dict) -> dict:
    ctx = se.Context(panel)
    names = [str(s) for s in ctx.symbols]
    result = {}
    for group, members in groups.items():
        columns = np.array([s in members for s in names])
        result[group] = {'symbols_with_prices': int(columns.sum()), 'symbols_requested': len(members),
                         **{label: evaluate(ctx, ledger, columns, floor) for label, floor in LIQUIDITY_FLOORS.items()}}
    return {
        'version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'status': 'RESEARCH_ONLY', 'production_rules_mutated': False, 'frozen_rules_mutated': False,
        'survivorship_free': False, 'universe': '오늘 기준 S&P MidCap 400 / SmallCap 600 구성종목',
        'rules': list(BASE_RULES), 'groups': result,
        'limitations': [
            '과거 구성종목 이력이 없어 오늘 지수에 있는 회사만 봤습니다. 상장폐지된 중소형주가 빠져 성적이 실제보다 좋게 나옵니다.',
            '규칙의 기준값은 S&P 500에서 정한 그대로이며 이 종목들에 맞춰 고치지 않았습니다.',
            '소형주는 호가 간격이 넓어 실제 거래 비용이 가정(편도 약 0.18%)보다 클 수 있습니다.',
        ],
    }


def main():
    from entry_feature_pool import download
    groups = {name: set(fetch_members(url)) for name, url in SOURCES.items()}
    frames = download(sorted(set().union(*groups.values())))
    report = build(build_panel(frames), groups, json.loads(se.OUT.read_text(encoding='utf-8')))
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    for group, body in report['groups'].items():
        print(group, body['symbols_with_prices'], '/', body['symbols_requested'])
        for floor in LIQUIDITY_FLOORS:
            for rule, segments in body[floor].items():
                print(' ', floor, rule, {k: (v.get('trades'), v.get('avg_return_pct'), v.get('win_rate_pct'), v.get('big_loss_share_pct'), v.get('t_stat')) for k, v in segments.items()})


if __name__ == '__main__':
    main()
