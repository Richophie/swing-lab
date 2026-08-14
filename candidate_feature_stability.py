from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean

import portfolio_candidate_capital_v2 as v2
import portfolio_walkforward_research as wf
import strategy_optimizer_runner as mtm
import strategy_optimizer_v2 as opt
import strategy_selection_research as selection

POOL = Path('static/replay_backtest_pool_v2.json')
OUT = Path('static/candidate_feature_stability.json')

# Existing signal-day features only. Expected directions come from the current
# hand-coded quality logic; this audit does not discover a new direction from TEST.
FEATURES = {
    'confirmed_pullback': {
        'elite_score': 'higher',
        'net_risk_reward': 'higher',
    },
    'sma200_20_squeeze': {
        'body_atr': 'higher',
        'ma_spread_pct': 'lower',
        'crosses_30': 'lower',
        'volume_ratio': 'higher',
        'ma_clearance_atr': 'higher',
        'sma200_slope_20d_pct': 'higher',
        'atr_pct': 'diagnostic',
    },
    'donchian_55': {
        'breakout_atr': 'higher',
        'volume_ratio': 'higher',
        'close_position': 'higher',
        'body_atr': 'higher',
        'sma200_slope_20d_pct': 'higher',
        'distance_sma200_pct': 'diagnostic',
        'atr_pct': 'diagnostic',
    },
}


def feature_value(candidate: dict, feature: str):
    if feature in {'elite_score', 'net_risk_reward'}:
        value = candidate.get(feature)
    else:
        value = (candidate.get('quality_features') or {}).get(feature)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def cuts(values: list[float]):
    if len(values) < 9:
        return None
    return selection.quantile(values, 1/3), selection.quantile(values, 2/3)


def bucket(value: float, low: float, high: float) -> str:
    if value <= low:
        return 'low'
    if value >= high:
        return 'high'
    return 'mid'


def feature_fold(pairs: list[tuple[dict, dict]], sid: str, feature: str, direction: str, fold: dict) -> dict:
    train_values = []
    for candidate, row in pairs:
        if candidate.get('strategy_id') != sid:
            continue
        day = opt.parse_day(row['start_date'])
        if not (fold['train_start'] <= day <= fold['train_end']):
            continue
        value = feature_value(candidate, feature)
        if value is not None:
            train_values.append(value)
    thresholds = cuts(train_values)
    if thresholds is None:
        return {'available': False, 'train_values': len(train_values), 'direction': direction}
    lo, hi = thresholds

    grouped = {'low': [], 'mid': [], 'high': []}
    for candidate, row in pairs:
        if candidate.get('strategy_id') != sid:
            continue
        day = opt.parse_day(row['start_date'])
        if not (fold['test_start'] <= day <= fold['test_end'] and opt.parse_day(row['end_date']) <= fold['test_end']):
            continue
        value = feature_value(candidate, feature)
        if value is None:
            continue
        grouped[bucket(value, lo, hi)].append(row)

    stats = {name: v2.outcome_stats(rows) for name, rows in grouped.items()}
    preferred = None
    opposite = None
    if direction == 'higher':
        preferred, opposite = 'high', 'low'
    elif direction == 'lower':
        preferred, opposite = 'low', 'high'
    delta = None
    supported = None
    if preferred and stats[preferred]['signals'] >= 3 and stats[opposite]['signals'] >= 3:
        delta = stats[preferred]['avg_realized_r'] - stats[opposite]['avg_realized_r']
        supported = delta > 0
    return {
        'available': True,
        'direction': direction,
        'train_values': len(train_values),
        'train_low_cut': round(float(lo), 6),
        'train_high_cut': round(float(hi), 6),
        'test': stats,
        'preferred_bucket': preferred,
        'opposite_bucket': opposite,
        'preferred_minus_opposite_r': None if delta is None else round(delta, 3),
        'direction_supported': supported,
    }


def same_day_rank_by_strategy(pairs: list[tuple[dict, dict]], fold: dict) -> dict:
    by_day = defaultdict(list)
    for candidate, row in pairs:
        day = opt.parse_day(row['start_date'])
        if fold['test_start'] <= day <= fold['test_end'] and opt.parse_day(row['end_date']) <= fold['test_end']:
            by_day[row['start_date']].append((candidate, row))

    grouped = defaultdict(lambda: {'rank1': [], 'rank2_3': [], 'rank4_plus': []})
    for day_pairs in by_day.values():
        ordered = sorted(day_pairs, key=lambda x: (-opt.num(x[1].get('priority')), str(x[1].get('key') or '')))
        seen = set()
        effective = []
        for candidate, row in ordered:
            symbol = row.get('symbol')
            if symbol and symbol in seen:
                continue
            if symbol:
                seen.add(symbol)
            effective.append((candidate, row))
        for rank, (candidate, row) in enumerate(effective, start=1):
            key = 'rank1' if rank == 1 else ('rank2_3' if rank <= 3 else 'rank4_plus')
            grouped[str(candidate.get('strategy_id'))][key].append(row)

    return {
        sid: {rank: v2.outcome_stats(rows) for rank, rows in ranks.items()}
        for sid, ranks in grouped.items()
    }


def fold_result(family: dict, candidates: list[dict], fold: dict, executed) -> dict:
    thresholds, rows = v2.fixed_pairs(family, candidates, fold, executed)

    # Recover candidate-row pairs with the same fixed top-50% gate and the same
    # TRAIN-frozen hybrid ranking used by V2/V1 research.
    allowed = set(family['strategies'])
    pairs = []
    distributions_source = []
    for candidate in candidates:
        sid = candidate.get('strategy_id')
        if sid not in allowed:
            continue
        threshold = thresholds[sid][v2.QUALITY_INTENSITY]
        if threshold is not None and candidate['_quality'] < threshold:
            continue
        row = executed(candidate)
        if row:
            distributions_source.append((candidate, v2.audit._audit_row(candidate, row)))
    distributions = v2.audit.train_distributions(distributions_source, fold['train_start'], fold['train_end'])
    for candidate, raw in distributions_source:
        row = dict(raw)
        row['priority'] = v2.audit.rank_value('hybrid_50', candidate, row, distributions)
        pairs.append((candidate, row))

    feature_rows = {}
    for sid, features in FEATURES.items():
        if sid not in allowed:
            continue
        feature_rows[sid] = {
            name: feature_fold(pairs, sid, name, direction, fold)
            for name, direction in features.items()
        }

    return {
        'fold': fold['id'],
        'train_start': str(fold['train_start']),
        'train_end': str(fold['train_end']),
        'test_start': str(fold['test_start']),
        'test_end': str(fold['test_end']),
        'features': feature_rows,
        'same_day_rank_by_strategy': same_day_rank_by_strategy(pairs, fold),
    }


def summarize_features(folds: list[dict]) -> dict:
    out = {}
    for sid, features in FEATURES.items():
        out[sid] = {}
        for feature, direction in features.items():
            entries = [f['features'].get(sid, {}).get(feature, {}) for f in folds]
            usable = [x for x in entries if x.get('direction_supported') is not None]
            deltas = [float(x['preferred_minus_opposite_r']) for x in usable]
            out[sid][feature] = {
                'direction': direction,
                'usable_folds': len(usable),
                'supported_folds': sum(1 for x in usable if x['direction_supported']),
                'mean_preferred_minus_opposite_r': round(mean(deltas), 3) if deltas else None,
                'strong_repeat': bool(len(usable) >= 4 and sum(1 for x in usable if x['direction_supported']) / len(usable) >= 0.75),
            }
    return out


def summarize_rank(folds: list[dict]) -> dict:
    out = {}
    for sid in FEATURES:
        fold_entries = [f['same_day_rank_by_strategy'].get(sid, {}) for f in folds]
        summary = {}
        for rank in ('rank1', 'rank2_3', 'rank4_plus'):
            items = [x.get(rank, {}) for x in fold_entries if x.get(rank, {}).get('signals')]
            summary[rank] = {
                'signals': sum(int(x.get('signals') or 0) for x in items),
                'mean_fold_avg_realized_r': round(mean(float(x['avg_realized_r']) for x in items), 3) if items else None,
                'mean_fold_avg_trade_pct': round(mean(float(x['avg_trade_pct']) for x in items), 3) if items else None,
            }
        eligible = 0
        wins = 0
        for x in fold_entries:
            a, b = x.get('rank1', {}), x.get('rank4_plus', {})
            if a.get('signals', 0) >= 3 and b.get('signals', 0) >= 3:
                eligible += 1
                wins += int(float(a['avg_realized_r']) > float(b['avg_realized_r']))
        summary['rank1_beats_rank4_plus_folds'] = wins
        summary['eligible_folds'] = eligible
        out[sid] = summary
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
    payload = {
        'version': 1,
        'ready': True,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'pool_generated_at': pool.get('generated_at'),
        'promotion_status': 'diagnostic_only_not_fresh_holdout',
        'family': {'id': family['id'], 'name': family['name'], 'strategies': family['strategies']},
        'method': {
            'quality_filter': 'fixed top 50% within strategy',
            'ranking': 'fixed hybrid_50',
            'feature_cuts': '33/67 percentiles estimated on each fold TRAIN only',
            'feature_direction': 'pre-existing expected direction from current quality logic; TEST never chooses direction',
            'outcome': 'realized R and daily-close MTM outcome diagnostics',
            'v1_untouched': True,
            'warning': 'development history has already been inspected; results diagnose score components and do not promote a rule',
        },
        'summary': {
            'features': summarize_features(results),
            'same_day_rank_by_strategy': summarize_rank(results),
        },
        'folds': results,
        'notes': [
            'Feature values are signal-day known data; realized R is used only after the fact to audit discrimination.',
            'A strong_repeat flag requires at least four usable TEST folds and the expected direction to win at least 75% of them.',
            'This audit does not change the Frozen Challenger V1 or create a production selector.',
            'Current-universe survivorship bias remains.',
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    print('\nCandidate feature stability')
    for sid, features in payload['summary']['features'].items():
        print('\n', sid)
        for name, x in features.items():
            print(name, 'direction', x['direction'], 'support', f"{x['supported_folds']}/{x['usable_folds']}", 'deltaR', x['mean_preferred_minus_opposite_r'], 'strong', x['strong_repeat'])
    print('\nSame-day rank by strategy')
    print(json.dumps(payload['summary']['same_day_rank_by_strategy'], ensure_ascii=False))


if __name__ == '__main__':
    main()
