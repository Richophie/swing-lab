"""Can the big losers of the washout-rebound rules be avoided?

The two rules that passed the evolution gates both buy deeply fallen stocks and hold
seven trading days. Their average is positive but about one trade in twenty loses 10%
or more. This study asks three questions about the union of their signals:

1. Is there a signal-day warning (a "skip filter") that removes losers without removing the edge?
2. Does a stop help or hurt?
3. Does sizing positions by volatility make the ride smoother?

Skip filters are chosen on 2017-2022 only, then the best few are shown 2023-2024 and
2025+ once. Research only: nothing here changes a frozen rule or a recommendation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

import strategy_evolution as se

OUT = Path('static/washout_risk_research.json')
BASE_RULES = ('evolved_champion_v1', 'evolved_champion_v2')
HOLD = 7
SEGMENTS = {
    'train_1': se.TRAIN_FOLDS[0], 'train_2': se.TRAIN_FOLDS[1], 'train_3': se.TRAIN_FOLDS[2],
    'validation': se.VALIDATION, 'lockbox': se.LOCKBOX,
}
TRAIN = ('train_1', 'train_2', 'train_3')
BIG_LOSS_PCT = -10.0
# Skip the trade when the feature is on its extreme side. Direction is fixed in advance.
WARNINGS = {
    'atr_pct': '>=', 'realized_vol20': '>=', 'range_atr': '>=', 'rel_volume': '>=',
    'gap_pct': '<=', 'ret1': '<=', 'ret3': '<=', 'ret5': '<=', 'down_streak': '>=',
    'drawdown_252d': '<=', 'dist_low_252d': '<=', 'days_since_low20': '<=', 'dollar_volume_log': '<=',
    'spy_ret1': '<=', 'spy_ret5': '<=', 'vix': '>=', 'vix_vs_sma20': '>=',
    'breadth_oversold': '>=', 'breadth_change5': '<=',
}
SKIP_SHARES = (0.1, 0.2, 0.3)
FINALISTS = 3
STOPS = (None, 3.0, 2.0)


def stats(values: np.ndarray) -> dict:
    n = int(len(values))
    if n == 0:
        return {'trades': 0}
    return {
        'trades': n, 'avg_return_pct': round(float(values.mean()), 3), 'win_rate_pct': round(float((values > 0).mean() * 100), 1),
        'big_loss_share_pct': round(float((values <= BIG_LOSS_PCT).mean() * 100), 1),
        'p5_return_pct': round(float(np.percentile(values, 5)), 2), 'worst_return_pct': round(float(values.min()), 2),
    }


def base_signals(ctx: se.Context, ledger: dict) -> np.ndarray:
    """A stock-day counts once even when both rules fire, and not again while it would still be held."""
    mask = np.zeros(ctx.panel['close'].shape, dtype=bool)
    for candidate in ledger.get('family_candidates') or []:
        if candidate['name'] in BASE_RULES:
            mask |= se.frozen_signals(ctx, candidate)[1]
    counts = np.cumsum(mask, axis=0, dtype=np.int32)
    before = np.zeros_like(counts); before[1:] = counts[:-1]
    start = np.zeros_like(counts); start[HOLD + 1:] = counts[:-(HOLD + 1)]
    return mask & ((before - start) == 0)


def by_segment(ctx: se.Context, returns: np.ndarray, signals: np.ndarray) -> dict:
    taken = signals & np.isfinite(returns)
    return {name: stats(returns[ctx.rows(*span)][taken[ctx.rows(*span)]]) for name, span in SEGMENTS.items()}


def skip_filters(ctx: se.Context, returns: np.ndarray, signals: np.ndarray) -> list[dict]:
    """Every pre-declared warning at every skip share, scored on TRAIN folds only."""
    taken = signals & np.isfinite(returns)
    train_rows = ctx.rows(se.TRAIN_FOLDS[0][0], se.TRAIN_FOLDS[-1][1])
    base = by_segment(ctx, returns, signals)
    out = []
    for feature, op in WARNINGS.items():
        if feature not in ctx.features:
            continue
        values = ctx.features[feature]
        sample = values[train_rows][taken[train_rows]]
        sample = sample[np.isfinite(sample)]
        if len(sample) < 100:
            continue
        seen = set()
        for share in SKIP_SHARES:
            threshold = float(np.quantile(sample, 1 - share if op == '>=' else share))
            if threshold in seen:
                continue
            seen.add(threshold)
            with np.errstate(invalid='ignore'):
                skip = (values >= threshold) if op == '>=' else (values <= threshold)
            kept = by_segment(ctx, returns, signals & ~skip)
            gains = [(kept[f]['avg_return_pct'] - base[f]['avg_return_pct'], base[f]['big_loss_share_pct'] - kept[f]['big_loss_share_pct']) for f in TRAIN if kept[f]['trades']]
            helps_everywhere = len(gains) == len(TRAIN) and all(a >= 0 and b >= 0 for a, b in gains)
            out.append({
                'feature': feature, 'op': op, 'skip_share': share, 'threshold': round(threshold, 5),
                'train_helps_in_every_fold': helps_everywhere,
                'train_worst_fold_avg_gain_pct': round(min(a for a, _ in gains), 3) if gains else None,
                'train_worst_fold_big_loss_cut_pct': round(min(b for _, b in gains), 2) if gains else None,
                'kept': kept,
            })
    return out


def choose(filters: list[dict], limit: int = FINALISTS) -> list[dict]:
    """Best filter per feature among those that helped in every TRAIN fold. Validation is not consulted."""
    good = sorted((f for f in filters if f['train_helps_in_every_fold']),
                  key=lambda f: (f['train_worst_fold_big_loss_cut_pct'], f['train_worst_fold_avg_gain_pct']), reverse=True)
    chosen, used = [], set()
    for f in good:
        if f['feature'] not in used:
            used.add(f['feature']); chosen.append(f)
        if len(chosen) == limit:
            break
    return chosen


def judge(base: dict, kept: dict) -> dict:
    """A filter survives only if it cuts big losses and keeps the average in both unseen periods."""
    result = {}
    for name in ('validation', 'lockbox'):
        b, k = base[name], kept[name]
        result[name] = {
            'avg_change_pct': round(k['avg_return_pct'] - b['avg_return_pct'], 3),
            'big_loss_share_change_pct': round(k['big_loss_share_pct'] - b['big_loss_share_pct'], 2),
            'trades_kept_pct': round(k['trades'] / b['trades'] * 100, 1) if b['trades'] else None,
        }
    result['survives'] = all(result[n]['avg_change_pct'] >= 0 and result[n]['big_loss_share_change_pct'] < 0 for n in ('validation', 'lockbox'))
    return result


def portfolio(ctx: se.Context, returns: np.ndarray, signals: np.ndarray, slots: int, weights: np.ndarray | None = None) -> dict:
    """Equal slots, most liquid first. With `weights`, each slot is scaled (capped at 1) and the rest stays in cash."""
    liquidity = ctx.features['dollar_volume_log']
    free_at = [0] * slots
    equity = peak = 1.0
    max_drawdown, taken = 0.0, 0
    for day in range(len(ctx.dates)):
        names = np.flatnonzero(signals[day] & np.isfinite(returns[day]))
        for j in names[np.argsort(-liquidity[day][names])]:
            slot = next((i for i in range(slots) if free_at[i] <= day), None)
            if slot is None:
                break
            free_at[slot] = day + HOLD + 1
            scale = 1.0 if weights is None else float(min(1.0, weights[day, j])) if np.isfinite(weights[day, j]) else 0.5
            equity *= 1.0 + float(returns[day, j]) / 100.0 / slots * scale
            peak = max(peak, equity); max_drawdown = min(max_drawdown, equity / peak - 1.0)
            taken += 1
    years = ctx.span_years(ctx.dates)
    return {'slots': slots, 'trades': taken, 'cagr_pct': round((equity ** (1 / years) - 1) * 100, 2) if years > 0 else None,
            'max_drawdown_pct': round(max_drawdown * 100, 1)}


def build(ctx: se.Context, ledger: dict) -> dict:
    signals = base_signals(ctx, ledger)
    plain = se.trade_returns(ctx.panel, HOLD, None, None)
    base = by_segment(ctx, plain, signals)
    filters = skip_filters(ctx, plain, signals)
    finalists = [{**f, 'unseen': judge(base, f['kept'])} for f in choose(filters)]

    stops = {}
    for stop in STOPS:
        returns = plain if stop is None else se.trade_returns(ctx.panel, HOLD, stop, None)
        stops['none' if stop is None else f'{stop:g}_atr'] = by_segment(ctx, returns, signals)

    train_rows = ctx.rows(se.TRAIN_FOLDS[0][0], se.TRAIN_FOLDS[-1][1])
    atr_pct = ctx.features['atr_pct']
    typical = float(np.nanmedian(atr_pct[train_rows][signals[train_rows]]))
    sizing = {
        'equal_3_slots': portfolio(ctx, plain, signals, 3),
        'equal_5_slots': portfolio(ctx, plain, signals, 5),
        'volatility_scaled_3_slots': portfolio(ctx, plain, signals, 3, typical / atr_pct),
        'volatility_scaled_5_slots': portfolio(ctx, plain, signals, 5, typical / atr_pct),
        'typical_atr_pct': round(typical, 4),
        'note': '변동성 조절은 하루 평균 움직임이 기준보다 큰 종목을 그만큼 적게 사고 나머지는 현금으로 둡니다. 수익은 진입일에 반영한 근사치입니다.',
    }
    return {
        'version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'status': 'RESEARCH_ONLY', 'production_rules_mutated': False, 'frozen_rules_mutated': False,
        'base_rules': list(BASE_RULES), 'hold_days': HOLD, 'big_loss_pct': BIG_LOSS_PCT,
        'base': base, 'filters_tried': len(filters),
        'filters_helping_in_every_train_fold': sum(1 for f in filters if f['train_helps_in_every_fold']),
        'finalists': finalists, 'survivors': [f['feature'] for f in finalists if f['unseen']['survives']],
        'all_filters': [{k: v for k, v in f.items() if k != 'kept'} for f in filters],
        'stops': stops, 'sizing': sizing,
        'limitations': [
            '실적 발표일은 무료로 믿을 만한 과거 자료가 없어 시험하지 못했습니다.',
            '경고 조건의 방향과 목록은 미리 정했지만 57개를 시험했으므로 우연히 좋아 보이는 것이 섞일 수 있습니다.',
            '가격이 남아 있지 않은 상장폐지 회사는 빠져 있습니다. 가장 큰 손실은 이런 회사에서 나기 쉽습니다.',
        ],
    }


def main():
    ctx = se.Context(se.load_panel() if se.PANEL_CACHE.exists() else se.build_panel())
    ledger = json.loads(se.OUT.read_text(encoding='utf-8'))
    report = build(ctx, ledger)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({'base': report['base'], 'helping_in_train': report['filters_helping_in_every_train_fold'],
                      'finalists': [{k: f[k] for k in ('feature', 'op', 'skip_share', 'threshold', 'train_worst_fold_avg_gain_pct', 'train_worst_fold_big_loss_cut_pct', 'unseen')} for f in report['finalists']],
                      'stops': report['stops'], 'sizing': report['sizing']}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
