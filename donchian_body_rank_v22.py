from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean, median

import portfolio_candidate_capital_v2 as v2
import portfolio_priority_audit as audit
import portfolio_walkforward_research as wf
import strategy_optimizer_runner as mtm
import strategy_optimizer_v2 as opt
import strategy_selection_research as selection

POOL = Path('static/replay_backtest_pool_v2.json')
OUT = Path('static/donchian_body_rank_v22.json')
DONCHIAN = 'donchian_55'


def revised_quality_raw(candidate: dict) -> float:
    """Single simplification hypothesis: Donchian uses body/ATR only.

    Other strategies keep their existing quality score. This function uses only
    signal-day data. The top-50% eligibility gate remains the original V1 gate,
    so this experiment isolates ordering/allocation rather than eligibility.
    """
    if candidate.get('strategy_id') == DONCHIAN:
        return float((candidate.get('quality_features') or {}).get('body_atr') or 0.0)
    return float(candidate.get('_quality') or 0.0)


def train_distributions(pairs: list[tuple[dict, dict]], fold: dict) -> dict:
    out = defaultdict(lambda: {'current': [], 'revised_quality': []})
    for candidate, row in pairs:
        day = opt.parse_day(row['start_date'])
        if not (fold['train_start'] <= day <= fold['train_end']):
            continue
        sid = str(candidate.get('strategy_id'))
        out[sid]['current'].append(float(row.get('_audit_current_priority', row.get('priority') or 0.0)))
        out[sid]['revised_quality'].append(revised_quality_raw(candidate))
    for values in out.values():
        values['current'].sort()
        values['revised_quality'].sort()
    return dict(out)


def revised_rows(pairs: list[tuple[dict, dict]], distributions: dict) -> list[dict]:
    rows = []
    for candidate, raw in pairs:
        sid = str(candidate.get('strategy_id'))
        dist = distributions.get(sid) or {'current': [], 'revised_quality': []}
        p = audit.empirical_percentile(
            dist['current'], float(raw.get('_audit_current_priority', raw.get('priority') or 0.0))
        )
        q = audit.empirical_percentile(dist['revised_quality'], revised_quality_raw(candidate))
        conviction = 0.5 * p + 0.5 * q
        row = dict(raw)
        row['priority'] = conviction
        row['_v2_conviction'] = conviction
        row['_v2_tier'] = v2.conviction_tier(conviction)
        row['_v22_quality_component'] = q
        rows.append(row)
    return rows


def original_pairs_and_rows(family: dict, candidates: list[dict], fold: dict, executed):
    thresholds = wf.thresholds_for(candidates, family['strategies'], fold['train_start'], fold['train_end'])
    allowed = set(family['strategies'])
    pairs = []
    for candidate in candidates:
        sid = candidate.get('strategy_id')
        if sid not in allowed:
            continue
        threshold = thresholds[sid][v2.QUALITY_INTENSITY]
        if threshold is not None and candidate['_quality'] < threshold:
            continue
        row = executed(candidate)
        if row:
            pairs.append((candidate, audit._audit_row(candidate, row)))
    original_dist = audit.train_distributions(pairs, fold['train_start'], fold['train_end'])
    original_rows = []
    for candidate, raw in pairs:
        row = dict(raw)
        conviction = audit.rank_value('hybrid_50', candidate, row, original_dist)
        row['priority'] = conviction
        row['_v2_conviction'] = conviction
        row['_v2_tier'] = v2.conviction_tier(conviction)
        original_rows.append(row)
    return thresholds, pairs, original_rows


def fold_result(family: dict, candidates: list[dict], fold: dict, executed) -> dict:
    thresholds, pairs, original_rows = original_pairs_and_rows(family, candidates, fold, executed)
    revised_dist = train_distributions(pairs, fold)
    body_rows = revised_rows(pairs, revised_dist)

    flat = next(p for p in v2.POLICIES if p['id'] == 'v1_flat')
    tiered = next(p for p in v2.POLICIES if p['id'] == 'tiered_all')
    variants = {
        'v1_flat': v2.weighted_mtm_portfolio(original_rows, fold['test_start'], fold['test_end'], family['capacity'], flat),
        'current_tiered': v2.weighted_mtm_portfolio(original_rows, fold['test_start'], fold['test_end'], family['capacity'], tiered),
        'donchian_body_tiered': v2.weighted_mtm_portfolio(body_rows, fold['test_start'], fold['test_end'], family['capacity'], tiered),
    }
    return {
        'fold': fold['id'],
        'train_start': str(fold['train_start']),
        'train_end': str(fold['train_end']),
        'test_start': str(fold['test_start']),
        'test_end': str(fold['test_end']),
        'variants': {
            key: {'test': wf.metric(value), 'allocation': v2.allocation_meta(value)}
            for key, value in variants.items()
        },
        'thresholds': {
            sid: None if thresholds[sid][v2.QUALITY_INTENSITY] is None else round(float(thresholds[sid][v2.QUALITY_INTENSITY]), 6)
            for sid in family['strategies']
        },
    }


def summarize(folds: list[dict], variant: str) -> dict:
    tests = [f['variants'][variant]['test'] for f in folds]
    returns = [x['return_pct'] for x in tests]
    compound = 1.0
    for value in returns:
        compound *= 1.0 + value / 100.0
    current = [f['variants']['current_tiered']['test']['return_pct'] for f in folds]
    flat = [f['variants']['v1_flat']['test']['return_pct'] for f in folds]
    out = {
        'stitched_test_return_pct': round((compound - 1.0) * 100.0, 2),
        'median_test_return_pct': round(median(returns), 2),
        'positive_test_folds': sum(1 for x in returns if x > 0),
        'worst_test_return_pct': round(min(returns), 2),
        'worst_test_mdd_pct': round(min(x['mdd_pct'] for x in tests), 2),
        'total_test_trades': sum(x['trades'] for x in tests),
    }
    if variant != 'v1_flat':
        out['folds_beating_v1'] = sum(1 for x, y in zip(returns, flat) if x > y + 0.01)
        out['mean_delta_vs_v1_pct'] = round(mean(x - y for x, y in zip(returns, flat)), 2)
    if variant == 'donchian_body_tiered':
        out['folds_beating_current_tiered'] = sum(1 for x, y in zip(returns, current) if x > y + 0.01)
        out['mean_delta_vs_current_tiered_pct'] = round(mean(x - y for x, y in zip(returns, current)), 2)
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

    cache = {}
    def executed(candidate):
        key = (candidate.get('symbol'), candidate.get('strategy_id'), candidate.get('signal_date'))
        if key not in cache:
            cache[key] = mtm.execute_candidate_mtm(candidate, pool, None, None)
        return cache[key]

    results = [fold_result(family, candidates, fold, executed) for fold in folds]
    summary = {key: summarize(results, key) for key in ('v1_flat', 'current_tiered', 'donchian_body_tiered')}
    payload = {
        'version': 1,
        'ready': True,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'pool_generated_at': pool.get('generated_at'),
        'promotion_status': 'posthoc_development_only_not_fresh_holdout',
        'family': {'id': family['id'], 'name': family['name'], 'strategies': family['strategies']},
        'hypothesis': {
            'source': 'feature audit found Donchian body_atr supported expected direction in 5/6 usable TEST folds; other Donchian quality components were weaker',
            'change': 'replace only Donchian quality-ranking component with TRAIN percentile of body_atr; retain current priority 50% and quality component 50%',
            'eligibility_gate_changed': False,
            'capital_policy': 'same fixed global tiered 0.5/0.75/1.0% risk budget',
            'grid_search': False,
        },
        'method': {
            'top50_gate': 'unchanged original within-strategy quality top50, estimated on TRAIN only',
            'other_strategy_scores': 'unchanged',
            'donchian_score': 'body_atr percentile in TRAIN only',
            'equity': 'daily_close_mark_to_market',
            'v1_untouched': True,
            'warning': 'body_atr was chosen after inspecting development diagnostics; this is a single post-hoc robustness test, not fresh holdout evidence',
        },
        'summary': summary,
        'folds': results,
        'notes': [
            'Frozen Challenger V1 is not changed.',
            'No threshold or weight grid is searched.',
            'This experiment simplifies Donchian ordering only; eligibility and risk ceilings remain unchanged.',
            'Current-universe survivorship bias remains.',
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    print('\nDonchian body rank V2.2')
    for key, x in summary.items():
        print(key, 'ret', x['stitched_test_return_pct'], 'mdd', x['worst_test_mdd_pct'], 'positive', x['positive_test_folds'], 'trades', x['total_test_trades'], 'beats_v1', x.get('folds_beating_v1'), 'beats_current', x.get('folds_beating_current_tiered'), 'delta_current', x.get('mean_delta_vs_current_tiered_pct'))
    for f in results:
        print(f['fold'], {k: v['test']['return_pct'] for k, v in f['variants'].items()})


if __name__ == '__main__':
    main()
