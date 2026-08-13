from __future__ import annotations

import json
from pathlib import Path

import gap_guard_research as gap
from market_data import load_price_history
from net_rr_research import pooled_stats
from portfolio_backtest import simulate_portfolio
from rsi2_broad_regime_research import MIN_HISTORY_ROWS, research_universe

OUT = Path('artifacts/rsi2_upside_gap_research.json')
TARGET_SYMBOLS = 60
POLICIES = {
    'baseline_current': {
        'confirmed_pullback': 'current',
        'rsi2_trend_reversion': 'current',
        'momentum_pullback': 'current',
    },
    'rsi2_up_0_50': {
        'confirmed_pullback': 'current',
        'rsi2_trend_reversion': 'down_current_up_0_50',
        'momentum_pullback': 'current',
    },
    'rsi2_up_0_25': {
        'confirmed_pullback': 'current',
        'rsi2_trend_reversion': 'down_current_up_0_25',
        'momentum_pullback': 'current',
    },
}

# Add one focused intermediate variant to the generic research module. Production
# config is untouched; this exists only inside the research process.
gap.VARIANTS['down_current_up_0_50'] = {'down': 'current', 'up': 0.50}


def bucket(trades: list[dict], name: str) -> list[dict]:
    if name == 'all': return trades
    if name == 'is_first_70pct': return [t for t in trades if t['is_is']]
    if name == 'oos_last_30pct': return [t for t in trades if t['is_oos']]
    if name == 'recent_2y': return [t for t in trades if t['is_recent']]
    raise ValueError(name)


def run_research() -> dict:
    requested, source = research_universe()
    requested = requested[:TARGET_SYMBOLS]
    eligible = []
    errors = []
    policy_trades = {name: [] for name in POLICIES}
    policy_diagnostics = {name: {} for name in POLICIES}
    symbol_results = []

    for symbol in requested:
        try:
            d = load_price_history(symbol, '10y').dropna()
            if len(d) < MIN_HISTORY_ROWS:
                errors.append({'symbol': symbol, 'error': f'history rows {len(d)} < {MIN_HISTORY_ROWS}'})
                continue
            frame, candidates = gap._signal_candidates(d, symbol)
            eligible.append(symbol)
        except Exception as exc:
            errors.append({'symbol': symbol, 'error': str(exc)})
            continue

        row = {'symbol': symbol, 'policies': {}}
        for policy, mapping in POLICIES.items():
            row['policies'][policy] = {}
            for sid, variant in mapping.items():
                try:
                    trades, diag = gap.simulate_variant(
                        d, frame, candidates[sid], variant,
                        symbol=symbol, strategy_id=sid,
                    )
                    policy_trades[policy].extend(trades)
                    row['policies'][policy][sid] = {'trades': len(trades), 'diagnostics': diag}
                except Exception as exc:
                    row['policies'][policy][sid] = {'error': str(exc)}
        symbol_results.append(row)

    summary = {}
    for policy, trades in policy_trades.items():
        summary[policy] = {}
        for b in ('all','is_first_70pct','oos_last_30pct','recent_2y'):
            bt = bucket(trades, b)
            stats = pooled_stats(bt)
            rsi2 = [t for t in bt if t['strategy_id'] == 'rsi2_trend_reversion']
            portfolio = simulate_portfolio(bt)
            stats['rsi2'] = pooled_stats(rsi2)
            stats['rsi2_open_relation'] = gap.relation_stats(rsi2)
            stats['portfolio'] = {k: portfolio.get(k) for k in (
                'return_pct','realized_pnl_krw','max_drawdown_pct','stress_drawdown_pct',
                'accepted_trades','win_rate_pct','avg_position_krw','max_concurrent_positions',
                'rejected_capacity','rejected_cash',
            )}
            summary[policy][b] = stats

    payload = {
        'study': 'Focused RSI2 upside next-open guard sensitivity',
        'status': 'RESEARCH_ONLY',
        'selection_source': source,
        'requested_symbol_count': len(requested),
        'eligible_symbol_count': len(eligible),
        'eligible_symbols': eligible,
        'errors': errors,
        'policies': POLICIES,
        'variant_definition': {
            'baseline_current': 'all strategies down/up current max(0.75ATR,1%)',
            'rsi2_up_0_50': 'RSI2 downside current, upside 0.50ATR; other strategies current',
            'rsi2_up_0_25': 'RSI2 downside current, upside 0.25ATR; other strategies current',
        },
        'variant_summary': summary,
        'symbol_results': symbol_results,
        'decision_rule': 'A focused RSI2 upside guard should improve or preserve both OOS and recent finite-account quality. Do not accept an OOS-only improvement that degrades recent results or removes excessive trades.',
        'production_note': 'No production guard changes in this study.',
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'eligible_symbol_count':len(eligible),'variant_summary':summary,'errors_count':len(errors)},ensure_ascii=False,indent=2))
    return payload


if __name__ == '__main__':
    run_research()
