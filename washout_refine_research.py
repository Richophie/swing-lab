"""Four ways to sharpen the washout-rebound rules without touching their conditions.

A. Which signal first?  When more signals fire than there are slots, order them by a feature.
B. Sector cap.          Never hold more than two names from one sector at once.
C. Wait for a bounce.   Only buy if the day after the signal closes above its open, one day later.
D. A learned score.     A ridge model on all signal-day features, trained on 2017-2022 signals.

Each idea is chosen or fitted on 2017-2022 only and shown 2023-2024 and 2025+ once.
Research only: nothing here changes a frozen rule or a recommendation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

import strategy_evolution as se
from washout_risk_research import SEGMENTS, TRAIN, base_signals, stats

OUT = Path('static/washout_refine_research.json')
HOLD, SLOTS, SECTOR_CAP = 7, 5, 2
UNSEEN = ('validation', 'lockbox')
# (feature, take the highest first?) — declared before looking at any result.
ORDERINGS = [(f, high) for f in ('drawdown_252d', 'drawdown_60d', 'dist_sma120', 'atr_pct', 'rel_volume', 'volume_5d_vs_20d', 'rsi2', 'ret5',
                                 'rank_ret20', 'lower_wick_atr', 'close_in_range', 'dollar_volume_log') for high in (True, False)]
BASE_ORDER = ('dollar_volume_log', True)
RIDGE_PENALTY = 10.0


def trade_list(ctx: se.Context, signals: np.ndarray, returns: np.ndarray, delay: int = 0) -> list[dict]:
    rows = []
    for i, j in zip(*np.nonzero(signals & np.isfinite(returns))):
        rows.append({'day': int(i), 'col': int(j), 'entry_day': int(i) + 1 + delay, 'exit_day': int(i) + HOLD + delay, 'return_pct': float(returns[i, j])})
    return rows


def account(trades: list[dict], priority, sector: dict | None = None, slots: int = SLOTS) -> dict:
    """Equal slots filled in `priority` order (higher first); a slot is reusable the day after its exit."""
    open_until, open_sector, taken = [], [], []
    for t in sorted(trades, key=lambda t: (t['day'], -priority(t))):
        live = [k for k, end in enumerate(open_until) if end >= t['entry_day']]
        open_until, open_sector = [open_until[k] for k in live], [open_sector[k] for k in live]
        if len(open_until) >= slots:
            continue
        group = sector.get(t['col']) if sector is not None else None
        if group is not None and open_sector.count(group) >= SECTOR_CAP:
            continue
        open_until.append(t['exit_day']); open_sector.append(group); taken.append(t)
    equity = peak = 1.0
    max_drawdown = 0.0
    for t in sorted(taken, key=lambda t: t['exit_day']):
        equity *= 1.0 + t['return_pct'] / 100.0 / slots
        peak = max(peak, equity); max_drawdown = min(max_drawdown, equity / peak - 1.0)
    values = np.array([t['return_pct'] for t in taken])
    return {'trades_taken': len(taken), 'total_return_pct': round((equity - 1) * 100, 1), 'max_drawdown_pct': round(max_drawdown * 100, 1),
            'avg_return_pct': round(float(values.mean()), 3) if len(values) else None}


def by_segment(ctx: se.Context, trades: list[dict], priority, sector: dict | None = None) -> dict:
    out = {}
    for name, span in SEGMENTS.items():
        rows = ctx.rows(*span)
        out[name] = account([t for t in trades if rows[t['day']]], priority, sector)
    return out


def judge(base: dict, plan: dict) -> dict:
    result = {name: {'total_return_change_pct': round(plan[name]['total_return_pct'] - base[name]['total_return_pct'], 1),
                     'max_drawdown_change_pct': round(plan[name]['max_drawdown_pct'] - base[name]['max_drawdown_pct'], 1)} for name in UNSEEN}
    result['survives'] = all(result[n]['total_return_change_pct'] > 0 and result[n]['max_drawdown_change_pct'] >= -2.0 for n in UNSEEN)
    return result


def ordering_study(ctx: se.Context, trades: list[dict]) -> dict:
    def priority_of(feature: str, high: bool):
        values = ctx.features[feature]
        return lambda t: float(np.nan_to_num(values[t['day'], t['col']] if high else -values[t['day'], t['col']], nan=-1e9))
    base = by_segment(ctx, trades, priority_of(*BASE_ORDER))
    table = {}
    for feature, high in ORDERINGS:
        if feature in ctx.features:
            table[f"{feature}|{'high' if high else 'low'}_first"] = by_segment(ctx, trades, priority_of(feature, high))
    worst = lambda p: min(p[f]['total_return_pct'] for f in TRAIN)
    beats_everywhere = [k for k, p in table.items() if all(p[f]['total_return_pct'] > base[f]['total_return_pct'] for f in TRAIN)]
    chosen = max(beats_everywhere, key=lambda k: worst(table[k])) if beats_everywhere else None
    return {'base_order': 'dollar_volume_log|high_first', 'base': base, 'orderings_tried': len(table),
            'beating_base_in_every_train_fold': beats_everywhere, 'chosen': chosen,
            'unseen': judge(base, table[chosen]) if chosen else None, 'chosen_segments': table.get(chosen), 'all': table}


def sector_study(ctx: se.Context, trades: list[dict], sector_by_symbol: dict) -> dict:
    liquidity = ctx.features['dollar_volume_log']
    priority = lambda t: float(np.nan_to_num(liquidity[t['day'], t['col']], nan=-1e9))
    sector = {j: sector_by_symbol.get(str(s)) for j, s in enumerate(ctx.symbols)}
    base, capped = by_segment(ctx, trades, priority), by_segment(ctx, trades, priority, sector)
    known = sum(1 for t in trades if sector.get(t['col']))
    return {'sector_cap': SECTOR_CAP, 'trades_with_known_sector_pct': round(known / len(trades) * 100, 1) if trades else None,
            'base': base, 'capped': capped, 'unseen': judge(base, capped),
            'train_helped_in_every_fold': all(capped[f]['total_return_pct'] > base[f]['total_return_pct'] for f in TRAIN)}


def confirmation_study(ctx: se.Context, signals: np.ndarray) -> dict:
    """Buy one day later, and only when the day after the signal closed above its open."""
    o, c = ctx.panel['open'], ctx.panel['close']
    next_up = np.zeros_like(signals)
    next_up[:-1] = c[1:] > o[1:]
    plain = se.trade_returns(ctx.panel, HOLD, None, None)
    delayed = np.full_like(plain, np.nan)
    delayed[:-1] = plain[1:]                       # the trade that starts one day later
    out = {}
    for name, span in SEGMENTS.items():
        rows = ctx.rows(*span)
        pick = lambda mask, r: stats(r[rows][(mask & np.isfinite(r))[rows]])
        out[name] = {'buy_next_open': pick(signals, plain), 'wait_and_bounced': pick(signals & next_up, delayed),
                     'wait_and_did_not_bounce': pick(signals & ~next_up, delayed)}
    gain = lambda n: out[n]['wait_and_bounced'].get('avg_return_pct', -99) - out[n]['buy_next_open'].get('avg_return_pct', 0)
    return {'segments': out, 'train_helped_in_every_fold': all(gain(f) > 0 for f in TRAIN),
            'survives': all(gain(f) > 0 for f in TRAIN) and all(gain(n) > 0 for n in UNSEEN)}


def score_study(ctx: se.Context, trades: list[dict]) -> dict:
    """Ridge regression of the trade return on rank-scaled features, fitted on TRAIN signals only."""
    names = [f for f in ctx.feature_names if np.isfinite(ctx.features[f]).mean() > 0.7]
    raw = np.array([[ctx.features[f][t['day'], t['col']] for f in names] for t in trades], dtype=np.float64)
    target = np.array([t['return_pct'] for t in trades])
    segment = {name: np.array([ctx.rows(*span)[t['day']] for t in trades]) for name, span in SEGMENTS.items()}
    train = segment['train_1'] | segment['train_2'] | segment['train_3']
    # Scale with TRAIN quantiles so one crash day cannot dominate, then clip.
    low, mid, high = np.nanpercentile(raw[train], [5, 50, 95], axis=0)
    width = np.where(high - low > 0, high - low, 1.0)
    x = np.clip((np.where(np.isfinite(raw), raw, mid) - mid) / width, -1.5, 1.5)
    y = np.clip(target, -20, 20)
    a = x[train]
    weights = np.linalg.solve(a.T @ a + RIDGE_PENALTY * np.eye(a.shape[1]), a.T @ (y[train] - y[train].mean()))
    score = x @ weights
    cut = float(np.median(score[train]))
    out = {}
    for name in SEGMENTS:
        mine = segment[name]
        out[name] = {'all': stats(target[mine]), 'high_score': stats(target[mine & (score >= cut)]), 'low_score': stats(target[mine & (score < cut)])}
    for t, value in zip(trades, score):
        t['score'] = float(value)
    liquidity = ctx.features['dollar_volume_log']
    base = by_segment(ctx, trades, lambda t: float(np.nan_to_num(liquidity[t['day'], t['col']], nan=-1e9)))
    ranked = by_segment(ctx, trades, lambda t: t['score'])
    gain = lambda n: out[n]['high_score'].get('avg_return_pct', -99) - out[n]['low_score'].get('avg_return_pct', 0)
    top = np.argsort(-np.abs(weights))[:8]
    return {'features_used': len(names), 'ridge_penalty': RIDGE_PENALTY, 'fitted_on': 'train folds only', 'segments': out,
            'high_minus_low_avg_pct': {n: round(gain(n), 3) for n in SEGMENTS},
            'survives': all(gain(n) > 0 for n in UNSEEN), 'account_ranked_by_score': ranked, 'account_base': base,
            'account_unseen': judge(base, ranked),
            'largest_weights': [{'feature': names[k], 'weight': round(float(weights[k]), 3)} for k in top],
            'note': 'TRAIN 구간의 높은 점수·낮은 점수 차이는 학습에 쓴 자료라 크게 나오는 것이 당연합니다. 검증·lockbox만 봅니다.'}


def fetch_sectors() -> dict:
    """GICS sector of today's S&P 500 members (free). Former members stay unknown and are never capped."""
    import requests
    from washout_universe_research import _Tables
    html = requests.get('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', timeout=30, headers={'User-Agent': 'Mozilla/5.0 swing-lab research'}).text
    parser = _Tables(); parser.feed(html)
    for rows in parser.tables:
        header = [c.lower() for c in rows[0]] if rows else []
        if len(rows) > 400 and 'symbol' in header and 'gics sector' in header:
            a, b = header.index('symbol'), header.index('gics sector')
            return {r[a].replace('.', '-'): r[b] for r in rows[1:] if len(r) > max(a, b) and r[a]}
    raise RuntimeError('no sector table found')


def build(ctx: se.Context, ledger: dict, sectors: dict) -> dict:
    signals = base_signals(ctx, ledger)
    plain = se.trade_returns(ctx.panel, HOLD, None, None)
    trades = trade_list(ctx, signals, plain)
    report = {
        'version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'status': 'RESEARCH_ONLY', 'production_rules_mutated': False, 'frozen_rules_mutated': False,
        'slots': SLOTS, 'hold_days': HOLD, 'signals': len(trades),
        'ordering': ordering_study(ctx, trades), 'sector_cap': sector_study(ctx, trades, sectors),
        'confirmation': confirmation_study(ctx, signals), 'score': score_study(ctx, trades),
        'limitations': [
            '업종은 오늘 S&P 500에 있는 회사만 알 수 있어, 지수에서 빠진 회사는 업종 제한을 받지 않습니다.',
            '계좌 수익은 5칸에 똑같이 나눠 담고 청산일에 반영한 근사치입니다.',
            '네 가지를 한꺼번에 시험했으므로 하나가 우연히 좋아 보일 수 있습니다.',
            '가격이 남아 있지 않은 상장폐지 회사는 빠져 있습니다.',
        ],
    }
    report['survivors'] = [name for name, ok in (('ordering', bool((report['ordering']['unseen'] or {}).get('survives'))),
                                                   ('sector_cap', report['sector_cap']['train_helped_in_every_fold'] and report['sector_cap']['unseen']['survives']),
                                                   ('confirmation', report['confirmation']['survives']), ('score', report['score']['survives'])) if ok]
    return report


def main():
    ctx = se.Context(se.load_panel() if se.PANEL_CACHE.exists() else se.build_panel())
    report = build(ctx, json.loads(se.OUT.read_text(encoding='utf-8')), fetch_sectors())
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    brief = lambda p: {s: (p[s]['trades_taken'], p[s]['total_return_pct'], p[s]['max_drawdown_pct']) for s in SEGMENTS}
    o = report['ordering']
    print('ORDER base', brief(o['base'])); print('  beats in train:', o['beating_base_in_every_train_fold'], 'chosen', o['chosen'], o['unseen'])
    if o['chosen']:
        print('  chosen', brief(o['chosen_segments']))
    s = report['sector_cap']
    print('SECTOR known%', s['trades_with_known_sector_pct'], 'capped', brief(s['capped']), s['train_helped_in_every_fold'], s['unseen'])
    c = report['confirmation']
    for name, seg in c['segments'].items():
        print('CONFIRM', name, {k: (v.get('trades'), v.get('avg_return_pct'), v.get('win_rate_pct'), v.get('big_loss_share_pct')) for k, v in seg.items()})
    print('  ', c['train_helped_in_every_fold'], c['survives'])
    m = report['score']
    for name, seg in m['segments'].items():
        print('SCORE', name, {k: (v.get('trades'), v.get('avg_return_pct'), v.get('win_rate_pct'), v.get('big_loss_share_pct')) for k, v in seg.items()})
    print('  ', m['high_minus_low_avg_pct'], m['survives'], 'account', brief(m['account_ranked_by_score']), m['account_unseen'])
    print('  weights', m['largest_weights'])
    print('SURVIVORS', report['survivors'])


if __name__ == '__main__':
    main()
