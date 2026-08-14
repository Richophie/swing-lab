from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean, median

import numpy as np

import portfolio_candidate_capital_v2 as v2
import portfolio_priority_audit as audit
import portfolio_walkforward_research as wf
import strategy_optimizer_runner as mtm
import strategy_optimizer_v2 as opt
import strategy_selection_research as selection

POOL = Path('static/replay_backtest_pool_v2.json')
OUT = Path('static/donchian_train_ranker_v23.json')
DONCHIAN = 'donchian_55'
FEATURES = (
    'breakout_atr',
    'volume_ratio',
    'close_position',
    'body_atr',
    'sma200_slope_20d_pct',
    'distance_sma200_pct',
    'atr_pct',
)


def feature_vector(candidate: dict) -> list[float]:
    q = candidate.get('quality_features') or {}
    return [float(q.get(name) or 0.0) for name in FEATURES]


def realized_r(row: dict) -> float:
    risk = max(opt.num(row.get('risk_fraction')), 0.001)
    return opt.num(row.get('change')) / risk


def fit_train_model(pairs: list[tuple[dict, dict]], fold: dict) -> dict:
    """Fit one OLS model on TRAIN only; no hyperparameter selection.

    Target is the within-TRAIN percentile of realized R, which bounds the
    target and prevents a few huge trend winners from dominating least squares.
    Only trades fully closed before TRAIN end are allowed as labels.
    """
    samples = []
    for candidate, row in pairs:
        if candidate.get('strategy_id') != DONCHIAN:
            continue
        start = opt.parse_day(row['start_date'])
        end = opt.parse_day(row['end_date'])
        if fold['train_start'] <= start <= fold['train_end'] and end <= fold['train_end']:
            samples.append((candidate, row))
    if len(samples) < 100:
        raise ValueError(f'not enough Donchian TRAIN labels: {len(samples)}')

    x = np.asarray([feature_vector(c) for c, _ in samples], dtype=float)
    r = np.asarray([realized_r(row) for _, row in samples], dtype=float)
    sorted_r = sorted(float(v) for v in r)
    y = np.asarray([audit.empirical_percentile(sorted_r, float(v)) for v in r], dtype=float)

    means = np.mean(x, axis=0)
    stds = np.std(x, axis=0)
    stds = np.where(stds < 1e-9, 1.0, stds)
    z = (x - means) / stds
    design = np.column_stack([np.ones(len(z)), z])
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    train_predictions = design @ beta

    return {
        'n': len(samples),
        'means': means.tolist(),
        'stds': stds.tolist(),
        'beta': beta.tolist(),
        'train_predictions': sorted(float(v) for v in train_predictions),
        'target_mean': float(np.mean(y)),
        'coefficients': {
            'intercept': round(float(beta[0]), 6),
            **{name: round(float(beta[i + 1]), 6) for i, name in enumerate(FEATURES)},
        },
    }


def model_prediction(candidate: dict, model: dict) -> float:
    x = np.asarray(feature_vector(candidate), dtype=float)
    means = np.asarray(model['means'], dtype=float)
    stds = np.asarray(model['stds'], dtype=float)
    beta = np.asarray(model['beta'], dtype=float)
    z = (x - means) / stds
    design = np.concatenate([[1.0], z])
    return float(design @ beta)


def build_pairs(family: dict, candidates: list[dict], fold: dict, executed):
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
    return thresholds, pairs


def current_rows(pairs: list[tuple[dict, dict]], fold: dict) -> tuple[list[dict], dict]:
    distributions = audit.train_distributions(pairs, fold['train_start'], fold['train_end'])
    rows = []
    for candidate, raw in pairs:
        row = dict(raw)
        conviction = audit.rank_value('hybrid_50', candidate, row, distributions)
        row['priority'] = conviction
        row['_v2_conviction'] = conviction
        row['_v2_tier'] = v2.conviction_tier(conviction)
        rows.append(row)
    return rows, distributions


def learned_rows(pairs: list[tuple[dict, dict]], fold: dict, original_distributions: dict) -> tuple[list[dict], dict]:
    model = fit_train_model(pairs, fold)
    rows = []
    for candidate, raw in pairs:
        sid = str(candidate.get('strategy_id'))
        dist = original_distributions.get(sid) or {'quality': [], 'priority': []}
        current_pct = audit.empirical_percentile(
            dist.get('priority') or [],
            float(raw.get('_audit_current_priority', raw.get('priority') or 0.0)),
        )
        if sid == DONCHIAN:
            pred = model_prediction(candidate, model)
            quality_pct = audit.empirical_percentile(model['train_predictions'], pred)
        else:
            quality_pct = audit.empirical_percentile(
                dist.get('quality') or [], float(candidate.get('_quality') or 0.0)
            )
        conviction = 0.5 * current_pct + 0.5 * quality_pct
        row = dict(raw)
        row['priority'] = conviction
        row['_v2_conviction'] = conviction
        row['_v2_tier'] = v2.conviction_tier(conviction)
        row['_v23_quality_pct'] = quality_pct
        rows.append(row)
    return rows, model


def fold_result(family: dict, candidates: list[dict], fold: dict, executed) -> dict:
    thresholds, pairs = build_pairs(family, candidates, fold, executed)
    base_rows, original_dist = current_rows(pairs, fold)
    ml_rows, model = learned_rows(pairs, fold, original_dist)
    flat = next(p for p in v2.POLICIES if p['id'] == 'v1_flat')
    tiered = next(p for p in v2.POLICIES if p['id'] == 'tiered_all')
    variants = {
        'v1_flat': v2.weighted_mtm_portfolio(base_rows, fold['test_start'], fold['test_end'], family['capacity'], flat),
        'current_tiered': v2.weighted_mtm_portfolio(base_rows, fold['test_start'], fold['test_end'], family['capacity'], tiered),
        'train_ranker_tiered': v2.weighted_mtm_portfolio(ml_rows, fold['test_start'], fold['test_end'], family['capacity'], tiered),
    }
    return {
        'fold': fold['id'],
        'train_start': str(fold['train_start']),
        'train_end': str(fold['train_end']),
        'test_start': str(fold['test_start']),
        'test_end': str(fold['test_end']),
        'model': {
            'train_labels': model['n'],
            'target_mean': round(model['target_mean'], 6),
            'coefficients': model['coefficients'],
        },
        'thresholds': {
            sid: None if thresholds[sid][v2.QUALITY_INTENSITY] is None else round(float(thresholds[sid][v2.QUALITY_INTENSITY]), 6)
            for sid in family['strategies']
        },
        'variants': {
            key: {'test': wf.metric(value), 'allocation': v2.allocation_meta(value)}
            for key, value in variants.items()
        },
    }


def summarize(folds: list[dict], variant: str) -> dict:
    tests = [f['variants'][variant]['test'] for f in folds]
    returns = [x['return_pct'] for x in tests]
    compound = 1.0
    for value in returns:
        compound *= 1.0 + value / 100.0
    flat = [f['variants']['v1_flat']['test']['return_pct'] for f in folds]
    current = [f['variants']['current_tiered']['test']['return_pct'] for f in folds]
    result = {
        'stitched_test_return_pct': round((compound - 1.0) * 100.0, 2),
        'median_test_return_pct': round(median(returns), 2),
        'positive_test_folds': sum(1 for x in returns if x > 0),
        'worst_test_return_pct': round(min(returns), 2),
        'worst_test_mdd_pct': round(min(x['mdd_pct'] for x in tests), 2),
        'total_test_trades': sum(x['trades'] for x in tests),
    }
    if variant != 'v1_flat':
        result['folds_beating_v1'] = sum(1 for x, y in zip(returns, flat) if x > y + 0.01)
        result['mean_delta_vs_v1_pct'] = round(mean(x - y for x, y in zip(returns, flat)), 2)
    if variant == 'train_ranker_tiered':
        result['folds_beating_current_tiered'] = sum(1 for x, y in zip(returns, current) if x > y + 0.01)
        result['mean_delta_vs_current_tiered_pct'] = round(mean(x - y for x, y in zip(returns, current)), 2)
    return result


def coefficient_stability(folds: list[dict]) -> dict:
    out = {}
    for feature in FEATURES:
        vals = [float(f['model']['coefficients'][feature]) for f in folds]
        positives = sum(1 for x in vals if x > 0)
        negatives = sum(1 for x in vals if x < 0)
        out[feature] = {
            'mean_coefficient': round(mean(vals), 6),
            'positive_folds': positives,
            'negative_folds': negatives,
            'same_sign_5_of_6': max(positives, negatives) >= 5,
        }
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
    summary = {key: summarize(results, key) for key in ('v1_flat', 'current_tiered', 'train_ranker_tiered')}
    payload = {
        'version': 1,
        'ready': True,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'pool_generated_at': pool.get('generated_at'),
        'promotion_status': 'development_only_train_fitted_not_fresh_holdout',
        'family': {'id': family['id'], 'name': family['name'], 'strategies': family['strategies']},
        'model': {
            'scope': 'Donchian candidate quality component only',
            'features': list(FEATURES),
            'algorithm': 'ordinary least squares on standardized signal-day features',
            'target': 'within-TRAIN percentile of realized R',
            'hyperparameter_search': False,
            'label_boundary': 'TRAIN labels require exit_date <= train_end',
            'other_strategies': 'retain current quality percentile',
            'current_priority_weight': 0.5,
            'model_quality_weight': 0.5,
            'capital_policy': 'fixed global tiered 0.5/0.75/1.0% risk budget',
        },
        'method': {
            'top50_gate': 'unchanged original quality gate using TRAIN only',
            'rolling_validation': '4y TRAIN -> next 1y TEST',
            'equity': 'daily_close_mark_to_market',
            'test_never_fits_model': True,
            'v1_untouched': True,
            'warning': 'model idea follows prior development diagnostics; TEST is rolling robustness evidence but history is not a fresh final holdout',
        },
        'summary': summary,
        'coefficient_stability': coefficient_stability(results),
        'folds': results,
        'notes': [
            'No coefficient, feature subset, threshold, or regularization hyperparameter is selected from TEST.',
            'The linear model is refit from scratch using only prior TRAIN data in each fold.',
            'Frozen Challenger V1 remains unchanged and continues forward-only.',
            'Current-universe survivorship bias remains.',
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    print('\nDonchian TRAIN ranker V2.3')
    for key, x in summary.items():
        print(key, 'ret', x['stitched_test_return_pct'], 'mdd', x['worst_test_mdd_pct'], 'positive', x['positive_test_folds'], 'trades', x['total_test_trades'], 'beats_v1', x.get('folds_beating_v1'), 'beats_current', x.get('folds_beating_current_tiered'), 'delta_current', x.get('mean_delta_vs_current_tiered_pct'))
    print('coefficient stability', json.dumps(payload['coefficient_stability'], ensure_ascii=False))
    for f in results:
        print(f['fold'], 'n', f['model']['train_labels'], {k: v['test']['return_pct'] for k, v in f['variants'].items()})


if __name__ == '__main__':
    main()
