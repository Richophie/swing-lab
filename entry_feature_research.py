"""Which setups win? Entry-feature research on the wide-universe pool.

For each pullback strategy, every signal-day feature is cut into TRAIN terciles
and scored in TRAIN, OOS and FORWARD. A single filter rule is then picked on
TRAIN only and OOS decides pass/fail.

Many features are tried, so a good TRAIN number is expected by chance alone; the
report states how many candidates were compared and only an OOS pass counts.

Research only. Production rules are untouched.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean

from exit_policy_research import FORWARD_START_DATE, MIN_TRAIN_EDGE_PCT, TRAIN_FRACTION

POOL = Path('static/entry_feature_pool.json')
OUT = Path('static/entry_feature_research.json')

MIN_TRAIN_TRADES = 150
MIN_OOS_TRADES = 60
MIN_STABLE_SPREAD_PCT = 0.30
# keep_best keeps one tercile of signals, drop_worst keeps two.
RULE_SHAPES = ('drop_worst', 'keep_best')


def split_cutoff(rows: list[dict]) -> str:
    dates = sorted(r['signal_date'] for r in rows if r['signal_date'] < FORWARD_START_DATE)
    return dates[min(len(dates) - 1, int(len(dates) * TRAIN_FRACTION))] if dates else FORWARD_START_DATE


def split_of(signal_date: str, cutoff: str) -> str:
    if signal_date >= FORWARD_START_DATE:
        return 'forward'
    return 'train' if signal_date < cutoff else 'oos'


def stats(rows: list[dict]) -> dict:
    returns = [r['return_pct'] for r in rows]
    if not returns:
        return {'trades': 0}
    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x < 0]
    return {
        'trades': len(returns),
        'avg_return_pct': round(mean(returns), 3),
        'win_rate_pct': round(len(wins) / len(returns) * 100.0, 1),
        'profit_factor': round(sum(wins) / -sum(losses), 3) if losses else None,
        'stop_pct': round(sum(1 for r in rows if str(r.get('reason', '')).startswith('stop')) / len(rows) * 100.0, 1),
    }


def tercile_cuts(values: list[float]) -> tuple[float, float] | None:
    """Tercile boundaries from TRAIN values only. None when the feature barely varies."""
    ordered = sorted(values)
    if len(ordered) < 30:
        return None
    low, high = ordered[len(ordered) // 3], ordered[2 * len(ordered) // 3]
    return (low, high) if high > low else None


def bucket_of(value, cuts: tuple[float, float]) -> int | None:
    if value is None:
        return None
    return 0 if value < cuts[0] else 2 if value >= cuts[1] else 1


def feature_report(rows_by_split: dict, feature: str) -> dict | None:
    cuts = tercile_cuts([r['features'].get(feature) for r in rows_by_split['train'] if r['features'].get(feature) is not None])
    if cuts is None:
        return None
    buckets = {}
    for split, rows in rows_by_split.items():
        grouped = {0: [], 1: [], 2: []}
        for row in rows:
            b = bucket_of(row['features'].get(feature), cuts)
            if b is not None:
                grouped[b].append(row)
        buckets[split] = [stats(grouped[i]) for i in range(3)]
    spread = lambda part: (part[2].get('avg_return_pct', 0) - part[0].get('avg_return_pct', 0)) if part[0].get('trades') and part[2].get('trades') else None
    train_spread, oos_spread = spread(buckets['train']), spread(buckets['oos'])
    stable = (
        train_spread is not None and oos_spread is not None
        and abs(train_spread) >= MIN_STABLE_SPREAD_PCT and abs(oos_spread) >= MIN_STABLE_SPREAD_PCT
        and (train_spread > 0) == (oos_spread > 0)
    )
    return {
        'cuts': [round(cuts[0], 5), round(cuts[1], 5)],
        'train': buckets['train'], 'oos': buckets['oos'], 'forward': buckets['forward'],
        'train_spread_pct': None if train_spread is None else round(train_spread, 3),
        'oos_spread_pct': None if oos_spread is None else round(oos_spread, 3),
        'higher_is_better': None if train_spread is None else train_spread > 0,
        'stable': stable,
    }


def rule_rows(rows: list[dict], feature: str, cuts: tuple[float, float], shape: str, higher_is_better: bool) -> list[dict]:
    best, worst = (2, 0) if higher_is_better else (0, 2)
    kept = []
    for row in rows:
        b = bucket_of(row['features'].get(feature), cuts)
        if b is None:
            continue
        if (shape == 'keep_best' and b == best) or (shape == 'drop_worst' and b != worst):
            kept.append(row)
    return kept


def judge(train: dict, oos: dict, base_train: dict, base_oos: dict) -> tuple[bool, list[str]]:
    if train.get('trades', 0) < MIN_TRAIN_TRADES or oos.get('trades', 0) < MIN_OOS_TRADES:
        return False, ['표본 부족']
    reasons = []
    if train['avg_return_pct'] - base_train['avg_return_pct'] < MIN_TRAIN_EDGE_PCT:
        reasons.append('학습구간에서 원신호보다 뚜렷하게 낫지 않음')
    if train['avg_return_pct'] <= 0:
        reasons.append('학습구간 평균 수익률이 0 이하')
    # profit_factor is None when a bucket has no losing trade at all.
    if oos['avg_return_pct'] <= 0 or (oos.get('profit_factor') is not None and oos['profit_factor'] <= 1):
        reasons.append('검증구간에서 이익이 아님')
    if oos['avg_return_pct'] <= base_oos.get('avg_return_pct', 0):
        reasons.append('검증구간에서 원신호보다 낫지 않음')
    return not reasons, reasons


def research_strategy(rows: list[dict], cutoff: str, labels: dict) -> dict:
    rows_by_split = {'train': [], 'oos': [], 'forward': []}
    for row in rows:
        rows_by_split[split_of(row['signal_date'], cutoff)].append(row)
    base = {split: stats(part) for split, part in rows_by_split.items()}

    features, rules = {}, []
    for feature in labels:
        report = feature_report(rows_by_split, feature)
        if report is None:
            continue
        features[feature] = {'label': labels[feature], **report}
        if report['higher_is_better'] is None:
            continue
        cuts = tuple(report['cuts'])
        for shape in RULE_SHAPES:
            kept = {split: stats(rule_rows(part, feature, cuts, shape, report['higher_is_better'])) for split, part in rows_by_split.items()}
            ok, reasons = judge(kept['train'], kept['oos'], base['train'], base['oos'])
            rules.append({
                'feature': feature, 'label': labels[feature], 'shape': shape,
                'direction': '높을수록 좋음' if report['higher_is_better'] else '낮을수록 좋음',
                'cuts': report['cuts'], **kept, 'passes_gate': ok, 'fail_reasons': reasons,
            })

    # The pick is the best TRAIN average among rules with enough TRAIN signals. OOS can only veto.
    eligible = [r for r in rules if r['train'].get('trades', 0) >= MIN_TRAIN_TRADES]
    pick = max(eligible, key=lambda r: r['train']['avg_return_pct'], default=None)
    ranked = sorted(features.items(), key=lambda kv: -abs(kv[1]['train_spread_pct'] or 0))
    return {
        'signals': len(rows),
        'baseline': base,
        'candidate_rules_compared': len(rules),
        'train_pick': pick,
        'train_pick_passes_oos': bool(pick and pick['passes_gate']),
        'rules_passing_gate': sum(1 for r in rules if r['passes_gate']),
        'stable_features': [k for k, v in ranked if v['stable']],
        'features': dict(ranked),
    }


def build_report(pool: dict | None = None) -> dict:
    pool = pool if pool is not None else json.loads(POOL.read_text(encoding='utf-8'))
    rows = pool.get('signals') or []
    cutoff = split_cutoff(rows)
    labels = pool.get('feature_labels') or {}
    strategies = {
        sid: research_strategy([r for r in rows if r['strategy_id'] == sid], cutoff, labels)
        for sid in pool.get('strategies') or []
    }
    return {
        'version': 1,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'status': 'ENTRY_FEATURE_RESEARCH',
        'research_only': True,
        'production_rules_mutated': False,
        'pool_generated_at': pool.get('generated_at'),
        'symbol_count': pool.get('eligible_symbol_count'),
        'signal_count': len(rows),
        'train_end_exclusive': cutoff,
        'forward_start_date': FORWARD_START_DATE,
        'gate': {
            'min_train_trades': MIN_TRAIN_TRADES, 'min_oos_trades': MIN_OOS_TRADES,
            'min_stable_spread_pct': MIN_STABLE_SPREAD_PCT,
            'rule': 'TRAIN 3분위로 자르고 TRAIN에서 규칙 하나를 고른 뒤 OOS는 통과/탈락만 판정',
        },
        'strategies': strategies,
        'limitations': [
            *(pool.get('limitations') or []),
            '특징 수십 개를 비교하므로 학습구간에서 좋아 보이는 규칙은 우연으로도 나옵니다. 검증구간 통과만 의미가 있습니다.',
            '검증구간 통과도 최종 결론이 아닙니다. 통과한 규칙은 Forward 가상 추적으로 확인해야 합니다.',
        ],
    }


def write_report(out: Path = OUT, pool: dict | None = None) -> dict:
    report = build_report(pool)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    report = write_report()
    print(json.dumps({
        sid: {
            'signals': row['signals'],
            'pick': None if not row['train_pick'] else f"{row['train_pick']['feature']}:{row['train_pick']['shape']}",
            'passes_oos': row['train_pick_passes_oos'], 'stable': row['stable_features'][:6],
        } for sid, row in report['strategies'].items()
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
