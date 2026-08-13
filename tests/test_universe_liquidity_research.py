from __future__ import annotations

from universe_liquidity_research import _quote_metrics, _top_dollar, summarize_universe


def check(cond, message):
    if not cond:
        raise AssertionError(message)


def main():
    q = _quote_metrics({'regularMarketPrice': 20, 'averageDailyVolume3Month': 2_000_000, 'marketCap': 5_000_000_000, 'bid': 19.99, 'ask': 20.01})
    check(q['dollar_volume_3m_proxy'] == 40_000_000, 'dollar liquidity must be price x avg volume')
    check(q['quoted_spread_bps'] is not None and q['quoted_spread_bps'] > 0, 'valid bid/ask must produce spread bps')

    quotes = {
        'AAA': {'symbol':'AAA','dollar_volume_3m_proxy':100_000_000,'market_cap':2_000_000_000,'quoted_spread_bps':5},
        'BBB': {'symbol':'BBB','dollar_volume_3m_proxy':50_000_000,'market_cap':5_000_000_000,'quoted_spread_bps':10},
        'CCC': {'symbol':'CCC','dollar_volume_3m_proxy':10_000_000,'market_cap':10_000_000_000,'quoted_spread_bps':20},
    }
    check(_top_dollar(quotes, 2) == ['AAA','BBB'], 'top dollar ranking must ignore market-cap order')
    check(_top_dollar(quotes, 3, 20_000_000) == ['AAA','BBB'], 'minimum dollar threshold must remove illiquid rows')

    rows = [
        {'symbol':'AAA','elite_pass':True,'strategy_signals':[{'strategy_id':'rsi2_trend_reversion','experimental':False,'elite_pass':True}]},
        {'symbol':'BBB','elite_pass':False,'strategy_signals':[{'strategy_id':'confirmed_pullback','experimental':False,'elite_pass':False}]},
    ]
    s = summarize_universe('x', ['AAA','BBB','CCC'], rows, quotes)
    check(s['raw_public_s_symbol_count'] == 2, 'raw public S symbols should be counted')
    check(s['elite_symbol_count'] == 1, 'elite symbols should be counted')
    check(s['elite_symbols'] == ['AAA'], 'elite symbol list should be deterministic')

    print('universe liquidity research PASS')


if __name__ == '__main__':
    main()
