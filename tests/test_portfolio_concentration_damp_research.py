from __future__ import annotations

import pandas as pd

from portfolio_concentration_damp_research import (
    behavior_sector,
    policy_multiplier,
    trailing_corr,
)


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    idx = pd.date_range('2025-10-01', periods=90, freq='B')
    tech = pd.Series([0.012 if i % 2 == 0 else -0.009 for i in range(90)], index=idx)
    finance = pd.Series([0.004 if i % 3 else -0.006 for i in range(90)], index=idx)
    returns = {
        'AAA': tech * 1.02,
        'BBB': tech * 0.94,
        'XLK': tech,
        'XLF': finance,
    }
    asof = idx[-1].strftime('%Y-%m-%d')

    corr = trailing_corr(returns, 'AAA', 'BBB', asof)
    check(corr is not None and corr > 0.99, 'highly similar stocks must have high trailing correlation')

    sector, sector_corr = behavior_sector('AAA', asof, returns, {})
    check(sector == 'XLK', 'behavior sector must use the highest trailing sector-ETF correlation')
    check(sector_corr is not None and sector_corr > 0.99, 'behavior-sector match should retain its correlation')

    clean = {'same_sector_count': 1, 'max_peer_corr': 0.70}
    mult, reasons = policy_multiplier({'sector_damp': True, 'corr_damp': True}, clean)
    check(mult == 1.0 and not reasons, 'no concentration trigger must preserve full risk')

    sector_hot = {'same_sector_count': 2, 'max_peer_corr': 0.40}
    mult, reasons = policy_multiplier({'sector_damp': True, 'corr_damp': False}, sector_hot)
    check(mult == 0.5 and reasons == ['sector'], 'third behavior-sector exposure must be half-risk in sector policy')

    corr_hot = {'same_sector_count': 0, 'max_peer_corr': 0.80}
    mult, reasons = policy_multiplier({'sector_damp': False, 'corr_damp': True}, corr_hot)
    check(mult == 0.5 and reasons == ['corr'], '>=0.75 peer correlation must be half-risk in correlation policy')

    both = {'same_sector_count': 3, 'max_peer_corr': 0.90}
    mult, reasons = policy_multiplier({'sector_damp': True, 'corr_damp': True}, both)
    check(mult == 0.5 and set(reasons) == {'sector', 'corr'}, 'combined policy must not stack below half-risk')

    # Guard against accidental hard-reject semantics: every pre-registered damp
    # returns either 1.0 or 0.5, never zero.
    check(mult > 0.0, 'concentration research must damp risk, not reject the valid candidate')

    print('portfolio concentration damp research PASS')


if __name__ == '__main__':
    main()
