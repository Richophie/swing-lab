from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

import numpy as np
import yfinance as yf

from market_data import load_us_universe, market_snapshot, prefilter_symbols
from scanner import scan_candidates, enrich_plans
from stock_names import canonical_symbol

OUT = Path('artifacts/universe_liquidity_research.json')
BASELINE_LIMIT = 500
BROAD_POOL_TARGET = 1200
BROAD_MIN_PRICE = 5
BROAD_MIN_AVG_VOLUME = 200_000
BROAD_MIN_MARKET_CAP = 500_000_000


def _num(row, *keys):
    for key in keys:
        try:
            value = row.get(key)
            if value is not None:
                n = float(value)
                if np.isfinite(n):
                    return n
        except Exception:
            pass
    return None


def _quote_metrics(row):
    price = _num(row, 'intradayprice', 'regularMarketPrice', 'regularmarketprice')
    avg_vol = _num(row, 'avgdailyvol3m', 'averageDailyVolume3Month', 'averageDailyVolume3month')
    cap = _num(row, 'intradaymarketcap', 'marketCap', 'marketcap')
    bid = _num(row, 'bid')
    ask = _num(row, 'ask')
    dollar = price * avg_vol if price and avg_vol else None
    spread_bps = None
    if bid and ask and ask >= bid and (ask + bid) > 0:
        mid = (ask + bid) / 2.0
        spread_bps = (ask - bid) / mid * 10_000 if mid > 0 else None
    return {
        'price': price,
        'avg_volume_3m': avg_vol,
        'market_cap': cap,
        'dollar_volume_3m_proxy': dollar,
        'bid': bid,
        'ask': ask,
        'quoted_spread_bps': spread_bps,
    }


def broad_quote_pool(universe):
    uset = {x['symbol'] for x in universe}
    query = yf.EquityQuery('and', [
        yf.EquityQuery('eq', ['region', 'us']),
        yf.EquityQuery('is-in', ['exchange', 'NMS', 'NGM', 'NCM', 'NYQ', 'ASE']),
        yf.EquityQuery('gte', ['intradayprice', BROAD_MIN_PRICE]),
        yf.EquityQuery('gte', ['avgdailyvol3m', BROAD_MIN_AVG_VOLUME]),
        yf.EquityQuery('gte', ['intradaymarketcap', BROAD_MIN_MARKET_CAP]),
    ])
    quotes = {}
    offset = 0
    while offset < 5000 and len(quotes) < BROAD_POOL_TARGET:
        resp = yf.screen(query, offset=offset, size=250, sortField='intradaymarketcap', sortAsc=False)
        batch = resp.get('quotes', []) if isinstance(resp, dict) else []
        if not batch:
            break
        for row in batch:
            symbol = canonical_symbol(row.get('symbol', ''))
            if symbol not in uset:
                continue
            metrics = _quote_metrics(row)
            metrics['symbol'] = symbol
            metrics['quote_keys'] = sorted(row.keys())[:80]
            quotes[symbol] = metrics
        offset += len(batch)
        if len(batch) < 250:
            break
    if len(quotes) < 200:
        raise RuntimeError(f'broad quote pool too small: {len(quotes)}')
    return quotes


def _top_dollar(quotes, limit, min_dollar=0):
    rows = [x for x in quotes.values() if (x.get('dollar_volume_3m_proxy') or 0) >= min_dollar]
    rows.sort(key=lambda x: (x.get('dollar_volume_3m_proxy') or 0, x.get('market_cap') or 0), reverse=True)
    return [x['symbol'] for x in rows[:limit]]


def _stats(values):
    vals = np.array([float(x) for x in values if x is not None and np.isfinite(float(x))], dtype=float)
    if not len(vals):
        return {'count': 0, 'p10': None, 'median': None, 'p90': None, 'min': None}
    return {
        'count': int(len(vals)),
        'p10': round(float(np.percentile(vals, 10)), 4),
        'median': round(float(np.median(vals)), 4),
        'p90': round(float(np.percentile(vals, 90)), 4),
        'min': round(float(vals.min()), 4),
    }


def summarize_universe(name, symbols, rows, quotes):
    sset = set(symbols)
    selected = [r for r in rows if r.get('symbol') in sset]
    raw_public = []
    elite_public = []
    for row in selected:
        for sig in row.get('strategy_signals') or []:
            if sig.get('experimental'):
                continue
            raw_public.append((row['symbol'], sig['strategy_id']))
            if sig.get('elite_pass'):
                elite_public.append((row['symbol'], sig['strategy_id']))

    dollar = [(quotes.get(s) or {}).get('dollar_volume_3m_proxy') for s in symbols]
    spread = [(quotes.get(s) or {}).get('quoted_spread_bps') for s in symbols]
    cap = [(quotes.get(s) or {}).get('market_cap') for s in symbols]
    signal_dollar = [(quotes.get(r['symbol']) or {}).get('dollar_volume_3m_proxy') for r in selected]
    elite_rows = [r for r in selected if r.get('elite_pass')]
    elite_dollar = [(quotes.get(r['symbol']) or {}).get('dollar_volume_3m_proxy') for r in elite_rows]

    return {
        'name': name,
        'symbol_count': len(symbols),
        'raw_public_s_signal_count': len(raw_public),
        'raw_public_s_symbol_count': len(set(s for s, _ in raw_public)),
        'elite_signal_count': len(elite_public),
        'elite_symbol_count': len(set(s for s, _ in elite_public)),
        'raw_s_symbols_per_100': round(len(set(s for s, _ in raw_public)) / max(1, len(symbols)) * 100, 2),
        'elite_symbols_per_100': round(len(set(s for s, _ in elite_public)) / max(1, len(symbols)) * 100, 2),
        'raw_by_strategy': dict(Counter(sid for _, sid in raw_public)),
        'elite_by_strategy': dict(Counter(sid for _, sid in elite_public)),
        'quote_dollar_volume_proxy': _stats(dollar),
        'quote_market_cap': _stats(cap),
        'quoted_spread_bps': _stats(spread),
        'quoted_spread_coverage_pct': round(sum(x is not None for x in spread) / max(1, len(symbols)) * 100, 2),
        'signal_symbol_dollar_volume_proxy': _stats(signal_dollar),
        'elite_symbol_dollar_volume_proxy': _stats(elite_dollar),
        'elite_symbols': sorted(set(s for s, _ in elite_public)),
        'raw_s_symbols': sorted(set(s for s, _ in raw_public)),
    }


def main():
    universe = load_us_universe()
    names = {x['symbol']: x['security_name'] for x in universe}
    baseline = prefilter_symbols(universe, BASELINE_LIMIT)
    quotes = broad_quote_pool(universe)

    variants = {
        'current_marketcap_500': baseline,
        'dollar_top500': _top_dollar(quotes, 500),
        'dollar_top800': _top_dollar(quotes, 800),
        'dollar_min20m_up_to800': _top_dollar(quotes, 800, 20_000_000),
        'dollar_min50m_up_to800': _top_dollar(quotes, 800, 50_000_000),
    }
    union = list(dict.fromkeys(s for symbols in variants.values() for s in symbols))
    market = market_snapshot()
    rows, failed = scan_candidates(union, market, names)
    rows = enrich_plans(rows, market.get('state'))

    summary = {name: summarize_universe(name, symbols, rows, quotes) for name, symbols in variants.items()}
    base_set = set(baseline)
    overlap = {}
    for name, symbols in variants.items():
        sset = set(symbols)
        overlap[name] = {
            'overlap_with_current': len(sset & base_set),
            'added_vs_current': len(sset - base_set),
            'removed_vs_current': len(base_set - sset),
            'added_examples': sorted(sset - base_set)[:50],
            'removed_examples': sorted(base_set - sset)[:50],
        }

    payload = {
        'study': 'Current market-cap universe versus dollar-liquidity ranked universes',
        'status': 'RESEARCH_ONLY',
        'market_state': market.get('state'),
        'us_listed_operating_universe_count': len(universe),
        'broad_quote_pool_count': len(quotes),
        'union_scanned_count': len(union),
        'scan_failed_count': len(failed),
        'broad_pool_thresholds': {
            'min_price': BROAD_MIN_PRICE,
            'min_avg_daily_volume_3m_shares': BROAD_MIN_AVG_VOLUME,
            'min_market_cap': BROAD_MIN_MARKET_CAP,
        },
        'variant_summary': summary,
        'overlap': overlap,
        'quote_field_sample': next(iter(quotes.values())).get('quote_keys', []) if quotes else [],
        'failed_sample': failed[:50],
        'decision_rule': 'Do not expand merely because more signals appear. Prefer a liquidity-ranked universe only if signal/elite discovery improves while dollar-liquidity quality remains high; quoted spread is diagnostic only because coverage may be incomplete.',
        'scope_note': 'This is a current-universe discovery-quality study, not a historical constituent backtest. Survivorship bias remains for historical performance questions.',
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'broad_quote_pool_count': len(quotes),
        'union_scanned_count': len(union),
        'variant_summary': summary,
        'scan_failed_count': len(failed),
    }, ensure_ascii=False, indent=2))
    return payload


if __name__ == '__main__':
    main()
