from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import json
from pathlib import Path
from statistics import mean, median

import numpy as np
import pandas as pd
import yfinance as yf

from global_flow_map import SECTORS
import portfolio_candidate_capital_v2 as v2
import portfolio_walkforward_research as wf
import strategy_optimizer_runner as mtm
import strategy_optimizer_v2 as opt
import strategy_selection_research as selection

POOL = Path('static/replay_backtest_pool_v2.json')
OUT = Path('static/portfolio_concentration_damp_v2.json')
LOOKBACK = 60
MIN_OVERLAP = 40
BASE_RISK_PCT = 0.75
CAPACITY = 10

# Coarse, pre-registered portfolio policies. No fine threshold/weight grid.
POLICIES = {
    'baseline': {
        'label': '기준 · 집중도에 따른 감액 없음',
        'sector_damp': False,
        'corr_damp': False,
    },
    'sector_half': {
        'label': '행동섹터 3번째부터 신규 위험 50%',
        'sector_damp': True,
        'corr_damp': False,
    },
    'corr_half': {
        'label': '보유종목과 60일 상관 ≥0.75면 신규 위험 50%',
        'sector_damp': False,
        'corr_damp': True,
    },
    'combined_half': {
        'label': '행동섹터 또는 상관 집중이면 신규 위험 50%',
        'sector_damp': True,
        'corr_damp': True,
    },
}


def _price_series(frame: pd.DataFrame) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype=float)
    for col in ('Adj Close', 'Close'):
        if col in frame:
            s = pd.to_numeric(frame[col], errors='coerce').dropna()
            if len(s):
                return s
    return pd.Series(dtype=float)


def _download_returns(symbols: list[str]) -> tuple[dict[str, pd.Series], list[str]]:
    symbols = sorted({str(x) for x in symbols if x})
    raw = yf.download(
        symbols,
        period='10y',
        interval='1d',
        auto_adjust=True,
        group_by='ticker',
        threads=True,
        progress=False,
    )
    out = {}
    missing = []
    for symbol in symbols:
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                level0 = set(map(str, raw.columns.get_level_values(0)))
                level1 = set(map(str, raw.columns.get_level_values(1)))
                if symbol in level0:
                    frame = raw[symbol]
                elif symbol in level1:
                    frame = raw.xs(symbol, axis=1, level=1)
                else:
                    frame = pd.DataFrame()
            else:
                frame = raw if len(symbols) == 1 else pd.DataFrame()
            s = _price_series(frame)
            if len(s) < MIN_OVERLAP + 5:
                missing.append(symbol)
                continue
            idx = pd.to_datetime(s.index)
            if getattr(idx, 'tz', None) is not None:
                idx = idx.tz_localize(None)
            s.index = idx
            out[symbol] = s.astype(float).pct_change().replace([np.inf, -np.inf], np.nan)
        except Exception:
            missing.append(symbol)
    return out, missing


def trailing_corr(returns: dict[str, pd.Series], a: str, b: str, asof: str, lookback: int = LOOKBACK):
    if not a or not b:
        return None
    if a == b:
        return 1.0
    sa = returns.get(a); sb = returns.get(b)
    if sa is None or sb is None:
        return None
    end = pd.Timestamp(str(asof)[:10])
    joined = pd.concat([sa.loc[:end].rename('a'), sb.loc[:end].rename('b')], axis=1, join='inner').dropna().tail(lookback)
    if len(joined) < MIN_OVERLAP:
        return None
    value = joined['a'].corr(joined['b'])
    if value is None or not np.isfinite(value):
        return None
    return float(value)


def behavior_sector(symbol: str, asof: str, returns: dict[str, pd.Series], cache: dict) -> tuple[str | None, float | None]:
    key = (str(symbol), str(asof)[:10])
    if key in cache:
        return cache[key]
    scored = []
    for etf in SECTORS:
        value = trailing_corr(returns, str(symbol), etf, asof)
        if value is not None:
            scored.append((value, etf))
    if not scored:
        result = (None, None)
    else:
        value, etf = max(scored, key=lambda x: x[0])
        result = (etf, float(value))
    cache[key] = result
    return result


def entry_context(row: dict, positions: dict, returns: dict[str, pd.Series], sector_cache: dict) -> dict:
    asof = str(row.get('_audit_signal_date') or row.get('signal_date') or row.get('start_date') or '')[:10]
    symbol = str(row.get('symbol') or '')
    sector, sector_corr = behavior_sector(symbol, asof, returns, sector_cache)
    same_sector_peers = []
    corr_peers = []
    for pos in positions.values():
        peer = str(pos['row'].get('symbol') or '')
        peer_sector, _ = behavior_sector(peer, asof, returns, sector_cache)
        if sector and peer_sector == sector:
            same_sector_peers.append(peer)
        value = trailing_corr(returns, symbol, peer, asof)
        if value is not None:
            corr_peers.append((float(value), peer))
    max_corr = max((x[0] for x in corr_peers), default=None)
    corr_peer = max(corr_peers, default=(None, None), key=lambda x: x[0])[1] if corr_peers else None
    return {
        'asof': asof,
        'behavior_sector': sector,
        'behavior_sector_corr': sector_corr,
        'same_sector_count': len(same_sector_peers),
        'same_sector_peers': same_sector_peers,
        'max_peer_corr': max_corr,
        'corr_peer': corr_peer,
    }


def policy_multiplier(policy: dict, context: dict) -> tuple[float, list[str]]:
    reasons = []
    if policy.get('sector_damp') and int(context.get('same_sector_count') or 0) >= 2:
        reasons.append('sector')
    max_corr = context.get('max_peer_corr')
    if policy.get('corr_damp') and max_corr is not None and float(max_corr) >= 0.75:
        reasons.append('corr')
    return (0.5 if reasons else 1.0), reasons


def _equity(cash: float, positions: dict) -> float:
    return cash + sum(p['size'] * opt.num(p.get('mark'), 1.0) for p in positions.values())


def concentration_portfolio(rows: list[dict], start: date, end: date, policy: dict,
                            returns: dict[str, pd.Series], sector_cache: dict) -> dict:
    selected = [
        dict(r) for r in rows
        if start <= opt.parse_day(r['start_date']) <= end and opt.parse_day(r['end_date']) <= end
    ]
    selected.sort(key=lambda r: (r['start_date'], -opt.num(r.get('priority')), str(r.get('key') or '')))

    starts, ends, marks = defaultdict(list), defaultdict(list), defaultdict(list)
    for seq, row in enumerate(selected):
        row['_seq'] = seq
        starts[row['start_date']].append(row)
        ends[row['end_date']].append(row)
        for mark in row.get('marks') or ():
            if len(mark) >= 2 and str(mark[0]):
                marks[str(mark[0])].append((seq, opt.num(mark[1], 1.0)))

    days = sorted(set(starts) | set(ends) | set(marks))
    cash = opt.INITIAL_CAPITAL
    peak = cash
    mdd = 0.0
    positions = {}
    open_symbols = set()
    changes = []
    reject_cash = reject_capacity = reject_duplicate = cash_limited = 0
    allocated = desired_total = 0.0
    cash_samples, exposure_samples, open_samples = [], [], []
    contexts = []
    damped = []

    def exposure():
        return sum(p['size'] * opt.num(p.get('mark'), 1.0) for p in positions.values())

    for day in days:
        incoming = sorted(starts.get(day, []), key=lambda r: (-opt.num(r.get('priority')), str(r.get('key') or ''), r['_seq']))
        for row in incoming:
            symbol = row.get('symbol')
            if symbol and symbol in open_symbols:
                reject_duplicate += 1
                continue
            if len(positions) >= CAPACITY:
                reject_capacity += 1
                continue

            context = entry_context(row, positions, returns, sector_cache)
            multiplier, reasons = policy_multiplier(policy, context)
            context_row = {
                'day': day,
                'symbol': symbol,
                'strategy_id': row.get('strategy_id'),
                'multiplier': multiplier,
                'reasons': reasons,
                'same_sector_count': context['same_sector_count'],
                'behavior_sector': context['behavior_sector'],
                'max_peer_corr': context['max_peer_corr'],
            }
            contexts.append(context_row)

            total = _equity(cash, positions)
            rf = max(opt.num(row.get('risk_fraction')), 0.001)
            desired = min(total * (BASE_RISK_PCT / 100.0) * multiplier / rf, total * opt.MAX_SHARE)
            actual = min(cash, desired)
            desired_total += desired
            if actual < 1.0:
                if desired >= 1.0:
                    reject_cash += 1
                continue
            if actual + 1e-6 < desired:
                cash_limited += 1

            positions[row['_seq']] = {'row': row, 'size': actual, 'mark': 1.0, 'entry_context': context_row}
            if symbol:
                open_symbols.add(symbol)
            cash -= actual
            allocated += actual
            if multiplier < 1.0:
                damped.append({**context_row, 'change': opt.num(row.get('change'))})

        for row in sorted(ends.get(day, []), key=lambda r: r['_seq']):
            pos = positions.get(row['_seq'])
            if not pos:
                continue
            change = opt.num(row.get('change'))
            cash += pos['size'] * (1.0 + change)
            changes.append(change)
            symbol = pos['row'].get('symbol')
            if symbol:
                open_symbols.discard(symbol)
            del positions[row['_seq']]

        for seq, factor in marks.get(day, ()):
            if seq in positions:
                positions[seq]['mark'] = factor

        total = _equity(cash, positions)
        expo = exposure()
        if total > 0:
            cash_samples.append(cash / total)
            exposure_samples.append(expo / total)
        open_samples.append(len(positions))
        peak = max(peak, total)
        if peak > 0:
            mdd = min(mdd, total / peak - 1.0)

    for pos in positions.values():
        change = opt.num(pos['row'].get('change'))
        cash += pos['size'] * (1.0 + change)
        changes.append(change)

    years = max((end - start).days / 365.25, 0.25)
    corr_vals = [float(x['max_peer_corr']) for x in contexts if x.get('max_peer_corr') is not None]
    sector_known = [x for x in contexts if x.get('behavior_sector')]
    damp_changes = [float(x['change']) for x in damped]
    return {
        'ending': cash,
        'return': cash / opt.INITIAL_CAPITAL - 1.0,
        'cagr': (cash / opt.INITIAL_CAPITAL) ** (1.0 / years) - 1.0 if cash > 0 else -1.0,
        'mdd': mdd,
        'trades': len(changes),
        'win_rate': sum(x > 0 for x in changes) / len(changes) if changes else 0.0,
        'avg_trade': mean(changes) if changes else 0.0,
        'trades_per_year': len(changes) / years,
        'max_open': max(open_samples, default=0),
        'underwater_days': 0,
        'reject_cash': reject_cash,
        'reject_capacity': reject_capacity,
        'reject_duplicate': reject_duplicate,
        'cash_limited_entries': cash_limited,
        'allocation_ratio': allocated / desired_total if desired_total else 0.0,
        'avg_cash_pct': mean(cash_samples) * 100.0 if cash_samples else 100.0,
        'avg_exposure_pct': mean(exposure_samples) * 100.0 if exposure_samples else 0.0,
        'avg_open_positions': mean(open_samples) if open_samples else 0.0,
        'entry_contexts': len(contexts),
        'sector_proxy_coverage_pct': len(sector_known) / len(contexts) * 100.0 if contexts else 0.0,
        'entries_same_sector_2plus': sum(int(x.get('same_sector_count') or 0) >= 2 for x in contexts),
        'entries_corr_075plus': sum(float(x.get('max_peer_corr') or -9) >= 0.75 for x in contexts),
        'median_max_peer_corr': median(corr_vals) if corr_vals else None,
        'damped_entries': len(damped),
        'damped_sector_entries': sum('sector' in x.get('reasons', []) for x in damped),
        'damped_corr_entries': sum('corr' in x.get('reasons', []) for x in damped),
        'damped_avg_trade': mean(damp_changes) if damp_changes else 0.0,
    }


def compact(result: dict) -> dict:
    base = wf.metric(result)
    base.update({
        'reject_cash': int(result['reject_cash']),
        'reject_capacity': int(result['reject_capacity']),
        'cash_limited_entries': int(result['cash_limited_entries']),
        'allocation_ratio_pct': round(result['allocation_ratio'] * 100.0, 1),
        'avg_cash_pct': round(result['avg_cash_pct'], 1),
        'avg_exposure_pct': round(result['avg_exposure_pct'], 1),
        'avg_open_positions': round(result['avg_open_positions'], 2),
        'sector_proxy_coverage_pct': round(result['sector_proxy_coverage_pct'], 1),
        'entries_same_sector_2plus': int(result['entries_same_sector_2plus']),
        'entries_corr_075plus': int(result['entries_corr_075plus']),
        'median_max_peer_corr': None if result['median_max_peer_corr'] is None else round(result['median_max_peer_corr'], 3),
        'damped_entries': int(result['damped_entries']),
        'damped_sector_entries': int(result['damped_sector_entries']),
        'damped_corr_entries': int(result['damped_corr_entries']),
        'damped_avg_trade_pct': round(result['damped_avg_trade'] * 100.0, 3),
    })
    return base


def summarize(folds: list[dict], key: str) -> dict:
    vals = [f['variants'][key] for f in folds]
    returns = [x['return_pct'] for x in vals]
    ref = [f['variants']['baseline']['return_pct'] for f in folds]
    compound = 1.0
    for value in returns:
        compound *= 1.0 + value / 100.0
    out = {
        'stitched_test_return_pct': round((compound - 1.0) * 100.0, 2),
        'positive_folds': sum(x > 0 for x in returns),
        'median_test_return_pct': round(median(returns), 2),
        'worst_test_return_pct': round(min(returns), 2),
        'worst_mdd_pct': round(min(x['mdd_pct'] for x in vals), 2),
        'total_trades': sum(x['trades'] for x in vals),
        'total_damped_entries': sum(x['damped_entries'] for x in vals),
        'total_cash_rejects': sum(x['reject_cash'] for x in vals),
        'total_capacity_rejects': sum(x['reject_capacity'] for x in vals),
        'mean_avg_cash_pct': round(mean(x['avg_cash_pct'] for x in vals), 1),
        'mean_avg_exposure_pct': round(mean(x['avg_exposure_pct'] for x in vals), 1),
        'mean_sector_proxy_coverage_pct': round(mean(x['sector_proxy_coverage_pct'] for x in vals), 1),
        'total_same_sector_2plus_entries': sum(x['entries_same_sector_2plus'] for x in vals),
        'total_corr_075plus_entries': sum(x['entries_corr_075plus'] for x in vals),
    }
    if key != 'baseline':
        out['folds_beating_reference'] = sum(x > y + 0.01 for x, y in zip(returns, ref))
        out['mean_delta_vs_reference_pct'] = round(mean(x - y for x, y in zip(returns, ref)), 2)
        out['folds_lower_mdd_than_reference'] = sum(
            f['variants'][key]['mdd_pct'] > f['variants']['baseline']['mdd_pct'] + 0.01 for f in folds
        )
    return out


def main() -> None:
    pool = json.loads(POOL.read_text(encoding='utf-8'))
    if not pool.get('ready') or int(pool.get('version') or 0) < 4:
        raise SystemExit('Replay pool V4 is required')
    candidates = list(pool.get('trades') or [])
    for candidate in candidates:
        candidate['_quality'] = selection.quality_score(candidate)
    family = next(f for f in selection.FAMILIES if f['id'] == v2.FAMILY_ID)
    folds = wf.folds_for(opt.parse_day(pool['available_start']), opt.parse_day(pool['available_end']))

    symbols = sorted({str(c.get('symbol')) for c in candidates if c.get('symbol')} | set(SECTORS))
    returns, missing = _download_returns(symbols)
    if len(set(SECTORS) & set(returns)) < 8:
        raise SystemExit('Insufficient sector ETF history for behavior-sector research')

    execute_cache = {}
    sector_cache = {}

    def executed(candidate):
        key = (candidate.get('symbol'), candidate.get('strategy_id'), candidate.get('signal_date'))
        if key not in execute_cache:
            execute_cache[key] = mtm.execute_candidate_mtm(candidate, pool, None, None)
        return execute_cache[key]

    fold_rows = []
    for fold in folds:
        _, rows = v2.fixed_pairs(family, candidates, fold, executed)
        variants = {
            key: compact(concentration_portfolio(rows, fold['test_start'], fold['test_end'], policy, returns, sector_cache))
            for key, policy in POLICIES.items()
        }
        fold_rows.append({
            'fold': fold['id'],
            'test_start': str(fold['test_start']),
            'test_end': str(fold['test_end']),
            'variants': variants,
        })

    summary = {key: summarize(fold_rows, key) for key in POLICIES}
    payload = {
        'version': 2,
        'ready': True,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'promotion_status': 'development_only_concentration_risk_damp_not_main_picker',
        'method': {
            'family': family.get('name') or family.get('id'),
            'quality_gate': 'TRAIN strategy top 50%',
            'priority': 'TRAIN hybrid_50',
            'base_risk_pct': BASE_RISK_PCT,
            'capacity': CAPACITY,
            'lookback_sessions': LOOKBACK,
            'minimum_overlap_sessions': MIN_OVERLAP,
            'behavior_sector': 'For each signal date, assign the stock to the one of 11 sector ETFs with highest trailing-60-session return correlation; uses only information available through signal date.',
            'risk_damp': 'Never reject a valid candidate. Pre-registered variants only halve new-entry risk when the specified concentration condition is present.',
            'correlation_threshold': 0.75,
            'sector_trigger': 'two or more existing positions map to the same behavior-sector ETF; the fresh candidate would become at least the third exposure in that factor bucket',
            'grid_search': False,
            'production_main_picker_mutated': False,
            'forward_v1_v2_mutated': False,
            'historical_status': 'development data already inspected; rolling TEST is mechanism evidence, not pristine final holdout',
            'prior_research_note': 'Legacy max-3 study rejected hard correlation caps and found low-correlation priority time-unstable; this V2 tests soft risk damp on the current max-10 / 0.75% baseline instead of repeating hard rejection.',
        },
        'data': {
            'requested_return_series': len(symbols),
            'loaded_return_series': len(returns),
            'missing_symbols': missing,
            'sector_etfs_loaded': sorted(set(SECTORS) & set(returns)),
        },
        'policies': POLICIES,
        'folds': fold_rows,
        'summary': summary,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Concentration risk-damp V2')
    print('history', len(returns), '/', len(symbols), 'sector ETFs', len(payload['data']['sector_etfs_loaded']))
    for key, value in summary.items():
        print(key, 'ret', value['stitched_test_return_pct'], 'mdd', value['worst_mdd_pct'], 'damped', value['total_damped_entries'], 'beat', value.get('folds_beating_reference'))
    print('FOLD RETURNS')
    for fold in fold_rows:
        print(fold['fold'], {k: v['return_pct'] for k, v in fold['variants'].items()})


if __name__ == '__main__':
    main()
