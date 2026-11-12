"""An AI stock ranker, the way the popular open-source quant stacks do it.

Microsoft's Qlib benchmark trains a gradient-boosted tree model (LightGBM) on technical
features to rank stocks by their return over the next few days, then buys the top of the
list. This repeats that recipe on our data and our swing horizon:

- features: the same signal-day indicators the evolution search uses
- label:    return from the next open to the close five trading days later, compared with
            the other index members on the same day
- model A:  trained on 2017-11 .. 2022-12, judged on 2023-2024
- model B:  trained on 2017-11 .. 2024-12, judged on 2025+
- settings: fixed in advance, never tuned on the judged periods

Needs `pip install lightgbm` (research only; not a dependency of the app).
Research only: nothing here changes a frozen rule or a recommendation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path

import numpy as np

import strategy_evolution as se
from washout_refine_research import account

OUT = Path('static/ml_ranker_research.json')
HOLD = 5
TOP_N = 5
EMBARGO_DAYS = 10          # labels look a week ahead, so the last days before a judged period are not trained on
PARAMS = {'objective': 'regression', 'learning_rate': 0.05, 'num_leaves': 31, 'min_data_in_leaf': 500, 'feature_fraction': 0.7,
          'bagging_fraction': 0.7, 'bagging_freq': 1, 'lambda_l2': 10.0, 'verbose': -1, 'seed': 7, 'num_threads': 4}
ROUNDS = 300
PERIODS = {'validation': (se.TRAIN_FOLDS[0][0], se.TRAIN_FOLDS[-1][1], *se.VALIDATION),
           'lockbox': (se.TRAIN_FOLDS[0][0], se.VALIDATION[1], *se.LOCKBOX)}


def dataset(ctx: se.Context):
    names = [f for f in ctx.feature_names if np.isfinite(ctx.features[f]).mean() > 0.7]
    returns = se.trade_returns(ctx.panel, HOLD, None, None).astype(np.float64)
    usable = ctx.tradable & np.isfinite(returns)
    # Relative label: how the stock did against the other tradable members bought the same day.
    day_mean = np.where(usable, returns, np.nan)
    relative = returns - np.nanmean(day_mean, axis=1, keepdims=True)
    return names, returns, relative, usable


def matrix(ctx: se.Context, names: list[str], cells: np.ndarray) -> np.ndarray:
    return np.column_stack([ctx.features[f][cells] for f in names]).astype(np.float32)


def day_t(values_by_day: list[float]) -> float:
    a = np.array(values_by_day)
    spread = float(a.std(ddof=1)) if len(a) > 1 else 0.0
    return round(float(a.mean() / spread * math.sqrt(len(a))), 2) if spread > 0 else 0.0


def judge_period(ctx: se.Context, scores: np.ndarray, returns: np.ndarray, usable: np.ndarray, rows: np.ndarray) -> dict:
    """Top-N picks of every day in the period against the average tradable member bought the same day."""
    picks, top_daily, excess_daily, ics, trades = [], [], [], [], []
    liquid = ctx.features['dollar_volume_log']
    for day in np.flatnonzero(rows):
        cols = np.flatnonzero(usable[day] & np.isfinite(scores[day]))
        if len(cols) < 50:
            continue
        s, r = scores[day, cols], returns[day, cols]
        order = np.argsort(-s)[:TOP_N]
        top_daily.append(float(r[order].mean())); excess_daily.append(float(r[order].mean() - r.mean()))
        rank = lambda v: np.argsort(np.argsort(v))
        ics.append(float(np.corrcoef(rank(s), rank(r))[0, 1]))
        for k in order:
            picks.append(float(r[k]))
            trades.append({'day': int(day), 'col': int(cols[k]), 'entry_day': int(day) + 1, 'exit_day': int(day) + HOLD, 'return_pct': float(r[k]), 'score': float(s[k])})
    picks = np.array(picks)
    return {
        'days': len(top_daily), 'picks': int(len(picks)),
        'top_avg_return_pct': round(float(picks.mean()), 3), 'top_win_rate_pct': round(float((picks > 0).mean() * 100), 1),
        'top_big_loss_share_pct': round(float((picks <= -10).mean() * 100), 1), 'top_t_stat': day_t(top_daily),
        'excess_over_average_member_pct': round(float(np.mean(excess_daily)), 3), 'excess_t_stat': day_t(excess_daily),
        'rank_ic': round(float(np.mean(ics)), 4), 'rank_ic_t_stat': day_t(ics),
        'account_5_slots': account(trades, lambda t: t['score'], None, 5),
    }


def run(ctx: se.Context) -> dict:
    import lightgbm as lgb
    names, returns, relative, usable = dataset(ctx)
    result = {}
    for period, (train_from, train_to, test_from, test_to) in PERIODS.items():
        train_rows = np.flatnonzero(ctx.rows(train_from, train_to))[:-EMBARGO_DAYS]
        cells = np.zeros_like(usable); cells[train_rows] = usable[train_rows]
        y = np.clip(relative[cells], -20, 20)
        model = lgb.train(PARAMS, lgb.Dataset(matrix(ctx, names, cells), label=y, feature_name=names), num_boost_round=ROUNDS)
        test_rows = ctx.rows(test_from, test_to)
        test_cells = np.zeros_like(usable); test_cells[test_rows] = ctx.tradable[test_rows]
        scores = np.full(returns.shape, np.nan)
        scores[test_cells] = model.predict(matrix(ctx, names, test_cells))
        gain = model.feature_importance('gain')
        top = np.argsort(-gain)[:10]
        result[period] = {'train': [train_from, str(ctx.dates[train_rows[-1]])], 'train_rows': int(cells.sum()), 'test': [test_from, test_to],
                          **judge_period(ctx, scores, returns, usable, test_rows),
                          'most_used_features': [{'feature': names[k], 'gain_share_pct': round(float(gain[k] / gain.sum() * 100), 1)} for k in top]}
    passes = all(r['top_avg_return_pct'] > 0 and r['excess_t_stat'] >= 2.0 for r in result.values())
    return {
        'version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'status': 'RESEARCH_ONLY', 'production_rules_mutated': False, 'frozen_rules_mutated': False,
        'recipe': 'LightGBM cross-sectional ranker (Qlib benchmark style)', 'hold_days': HOLD, 'top_n_per_day': TOP_N,
        'features': len(names), 'params': PARAMS, 'rounds': ROUNDS, 'embargo_days': EMBARGO_DAYS,
        'pass_rule': '두 구간 모두 상위 종목의 비용 차감 평균이 플러스이고, 같은 날 평균 종목 대비 초과수익의 t값이 2 이상',
        'periods': result, 'passes': bool(passes),
        'limitations': [
            '설정을 한 가지로 고정하고 한 번만 돌렸습니다. 설정을 바꿔 가며 다시 보면 그만큼 우연이 섞입니다.',
            '기술적 지표만 썼습니다. 뉴스·실적·수급 같은 자료는 없습니다.',
            '가격이 남아 있지 않은 상장폐지 회사는 빠져 있습니다.',
        ],
    }


def main():
    ctx = se.Context(se.load_panel() if se.PANEL_CACHE.exists() else se.build_panel())
    report = run(ctx)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    for name, r in report['periods'].items():
        print(name, {k: v for k, v in r.items() if k != 'most_used_features'})
        print('  ', [(x['feature'], x['gain_share_pct']) for x in r['most_used_features']])
    print('PASSES', report['passes'])


if __name__ == '__main__':
    main()
