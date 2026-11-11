"""Forward diagnostics for official close-confirmed recommendations.

Reads ``static/trade_history.json`` only and writes ``static/forward_diagnostics.json``.
It never changes strategy rules, thresholds, the journal or any forward state; the
findings are review material for humans and for frozen challenger research.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean, median

from config import BACKTEST_MAX_POSITIONS

ROOT = Path(__file__).parent
STATIC = ROOT / 'static'
HISTORY = STATIC / 'trade_history.json'
OUT = STATIC / 'forward_diagnostics.json'

# VALIDATION/roadmap contract: no tuning talk before 30 closed, formal review from 50.
MIN_REVIEW_CLOSED = 50
MIN_BUCKET_CLOSED = 20
MFE_LEVELS_PCT = (1.0, 2.0, 3.0, 4.0, 5.0)
ELITE_BUCKET_WIDTH = 4


def _n(value, default=None):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if out == out else default


def _r(value, digits=2):
    return None if value is None else round(float(value), digits)


def _pct(part: int, total: int):
    return round(part / total * 100.0, 1) if total else None


def load_items(history: dict) -> list[dict]:
    """Official public recommendations, flattened with their market date."""
    items = []
    for day in history.get('days') or []:
        for item in day.get('items') or []:
            if item.get('experimental') or item.get('performance_bucket') not in (None, 'official_public'):
                continue
            row = dict(item)
            row['_day'] = str(item.get('market_date') or day.get('date') or '')[:10]
            items.append(row)
    return items


def closed_items(items: list[dict]) -> list[dict]:
    return [x for x in items if x.get('status_code') != 'OPEN' and _n(x.get('outcome_return_pct')) is not None]


def _reference_entry(item: dict):
    low, high = _n(item.get('entry_low')), _n(item.get('entry_high'))
    if low and high and low > 0 and high > 0:
        return (low + high) / 2.0
    return _n(item.get('current_reference_price'))


def mfe_pct(item: dict):
    """Best favourable move inside the observation window, from the BUY-zone midpoint."""
    entry, best = _reference_entry(item), _n(item.get('best_high'))
    if not entry or not best or entry <= 0:
        return None
    return (best / entry - 1.0) * 100.0


def metrics(rows: list[dict]) -> dict:
    returns = [_n(x.get('outcome_return_pct')) for x in rows]
    returns = [x for x in returns if x is not None]
    total = len(returns)
    if not total:
        return {'closed': 0}
    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x < 0]
    gross_win, gross_loss = sum(wins), -sum(losses)
    codes = [str(x.get('status_code') or '') for x in rows]
    return {
        'closed': total,
        'avg_return_pct': _r(mean(returns)),
        'median_return_pct': _r(median(returns)),
        'win_rate_pct': _pct(len(wins), total),
        'profit_factor': _r(gross_win / gross_loss) if gross_loss > 0 else None,
        'avg_win_pct': _r(mean(wins)) if wins else None,
        'avg_loss_pct': _r(mean(losses)) if losses else None,
        'realized_reward_risk': _r(mean(wins) / -mean(losses)) if wins and losses else None,
        'target_hit_pct': _pct(codes.count('SUCCESS'), total),
        'stop_pct': _pct(codes.count('STOP'), total),
        'time_exit_pct': _pct(sum(1 for c in codes if c.startswith('EXPIRED')), total),
    }


def _grouped(rows: list[dict], key) -> dict:
    groups = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    return {str(k): metrics(v) for k, v in sorted(groups.items(), key=lambda kv: str(kv[0]))}


def target_reachability(rows: list[dict]) -> dict:
    pairs = [(mfe_pct(x), _n(x.get('target_pct'))) for x in rows]
    pairs = [(m, t) for m, t in pairs if m is not None and t is not None and t > 0]
    if not pairs:
        return {'sample': 0}
    mfes = [m for m, _ in pairs]
    targets = [t for _, t in pairs]
    planned_rr = [x for x in (_n(r.get('risk_reward')) for r in rows) if x is not None]
    bars = [x for x in (_n(r.get('bars_observed')) for r in rows) if x is not None]
    return {
        'sample': len(pairs),
        'median_target_pct': _r(median(targets)),
        'median_mfe_pct': _r(median(mfes)),
        'median_bars_observed': _r(median(bars), 1) if bars else None,
        'median_planned_reward_risk': _r(median(planned_rr)) if planned_rr else None,
        'mfe_reached_target_pct': _pct(sum(1 for m, t in pairs if m >= t), len(pairs)),
        'mfe_reach_by_level': [
            {'level_pct': level, 'reached_pct': _pct(sum(1 for m in mfes if m >= level), len(mfes))}
            for level in MFE_LEVELS_PCT
        ],
    }


def stop_recovery(rows: list[dict]) -> dict:
    """Where stopped-out picks trade now. A single mark-date snapshot, not a tested rule."""
    stopped = [x for x in rows if x.get('status_code') == 'STOP']
    marks = [_n(x.get('current_return_pct')) for x in stopped]
    marks = [x for x in marks if x is not None]
    all_marks = [x for x in (_n(r.get('current_return_pct')) for r in rows) if x is not None]
    mark_dates = sorted({str(x.get('current_price_market_date')) for x in rows if x.get('current_price_market_date')})
    return {
        'stopped': len(stopped),
        'stopped_with_mark': len(marks),
        'stopped_now_above_entry_pct': _pct(sum(1 for x in marks if x > 0), len(marks)),
        'stopped_avg_mark_return_pct': _r(mean(marks)) if marks else None,
        'all_avg_mark_return_pct': _r(mean(all_marks)) if all_marks else None,
        'mark_date': mark_dates[-1] if mark_dates else None,
        'basis': 'single_mark_date_snapshot_not_a_tested_exit_rule',
    }


def _rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]):
    if len(xs) < 3:
        return None
    rx, ry = _rank(xs), _rank(ys)
    mx, my = mean(rx), mean(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    return cov / (vx * vy) ** 0.5 if vx > 0 and vy > 0 else None


def score_calibration(rows: list[dict]) -> dict:
    scored = [(_n(x.get('elite_score_at_close'), _n(x.get('score'))), _n(x.get('outcome_return_pct')), x) for x in rows]
    scored = [(s, r, x) for s, r, x in scored if s is not None and r is not None]
    buckets = defaultdict(list)
    for score, _, row in scored:
        low = int(score // ELITE_BUCKET_WIDTH * ELITE_BUCKET_WIDTH)
        buckets[low].append(row)
    table = [
        {'score_from': low, 'score_to': low + ELITE_BUCKET_WIDTH, **metrics(group)}
        for low, group in sorted(buckets.items())
    ]
    rho = spearman([s for s, _, _ in scored], [r for _, r, _ in scored])
    return {'sample': len(scored), 'spearman_score_vs_return': _r(rho, 3), 'buckets': table}


def signal_load(items: list[dict]) -> dict:
    per_day = defaultdict(int)
    for item in items:
        per_day[item['_day']] += 1
    counts = sorted(per_day.values())
    if not counts:
        return {'days': 0}
    return {
        'days': len(counts),
        'median_per_day': _r(median(counts), 1),
        'max_per_day': counts[-1],
        'account_max_positions': BACKTEST_MAX_POSITIONS,
        'days_over_capacity_pct': _pct(sum(1 for c in counts if c > BACKTEST_MAX_POSITIONS), len(counts)),
    }


def _finding(code: str, severity: str, title: str, evidence: str, next_step: str) -> dict:
    return {'code': code, 'severity': severity, 'title': title, 'evidence': evidence, 'next_step': next_step}


def findings(report: dict) -> list[dict]:
    """Plain-language flags. Each one points at research, never at a production edit."""
    out = []
    overall, reach = report['overall'], report['target_reachability']
    if overall.get('closed', 0) < MIN_REVIEW_CLOSED:
        return out

    if reach.get('sample') and reach['median_mfe_pct'] < reach['median_target_pct'] * 0.6 and (overall.get('target_hit_pct') or 0) < 20:
        out.append(_finding(
            'TARGET_OUT_OF_REACH', 'high', '목표가가 보유기간 안에 닿지 않습니다',
            f"목표가 중앙값 +{reach['median_target_pct']}% · 관찰기간 최고가 중앙값 +{reach['median_mfe_pct']}% · 목표가 도달 {overall['target_hit_pct']}%",
            '목표가를 실제로 닿는 폭에 맞춘 청산 규칙을 별도 가상계좌로 검증',
        ))
    planned, realized = reach.get('median_planned_reward_risk'), overall.get('realized_reward_risk')
    if planned and realized and realized < planned * 0.6:
        out.append(_finding(
            'REWARD_RISK_GAP', 'high', '표시 손익비와 실제 손익비가 다릅니다',
            f"표시 손익비 중앙값 {planned}:1 · 실제 평균이익/평균손실 {realized}:1",
            '카드의 손익비를 실제 청산 방식 기준으로 다시 계산하는 안 검토',
        ))
    recovery = report['stop_recovery']
    if recovery.get('stopped_with_mark', 0) >= MIN_BUCKET_CLOSED and (recovery.get('stopped_now_above_entry_pct') or 0) >= 55:
        out.append(_finding(
            'STOPPED_THEN_RECOVERED', 'medium', '손절된 종목의 다수가 이후 회복했습니다',
            f"손절 {recovery['stopped']}건 중 {recovery['stopped_now_above_entry_pct']}%가 {recovery['mark_date']} 기준 진입가 위 (한 시점 스냅샷)",
            '손절 폭·보유기간을 넓힌 안을 백테스트로 비교',
        ))
    calibration = report['score_calibration']
    rho = calibration.get('spearman_score_vs_return')
    if calibration.get('sample', 0) >= MIN_REVIEW_CLOSED and rho is not None and rho < 0.05:
        out.append(_finding(
            'SCORE_NOT_PREDICTIVE', 'medium', '엄선점수가 결과를 구분하지 못합니다',
            f"점수와 결과의 관련도 {rho} (1에 가까울수록 점수가 잘 맞음, 0이면 무관)",
            '점수 구성요소별 기여도를 다시 측정하고 정렬 기준을 재검토',
        ))
    by_state = report['by_market_state']
    good = by_state.get('좋음') or {}
    if good.get('closed', 0) >= MIN_REVIEW_CLOSED and good['closed'] / overall['closed'] >= 0.7 and (good.get('avg_return_pct') or 0) < 0:
        out.append(_finding(
            'MARKET_STATE_NOT_DISCRIMINATING', 'medium', '시장 상태 "좋음"에서도 평균 손실입니다',
            f"전체 {overall['closed']}건 중 {good['closed']}건이 좋음 · 평균 {good['avg_return_pct']}%",
            '시장 상태 판정 기준을 과거 구간으로 재점검',
        ))
    load = report['signal_load']
    if load.get('days') and (load.get('days_over_capacity_pct') or 0) >= 50:
        out.append(_finding(
            'MORE_SIGNALS_THAN_SLOTS', 'low', '추천 수가 계좌 슬롯보다 많습니다',
            f"하루 중앙값 {load['median_per_day']}건 · 최대 {load['max_per_day']}건 · 동시보유 한도 {load['account_max_positions']}",
            '하루 상위 N개만 노출하는 안 검토',
        ))
    names = report.get('strategy_names') or {}
    for sid, row in report['by_strategy'].items():
        if row.get('closed', 0) >= MIN_REVIEW_CLOSED and (row.get('profit_factor') or 0) < 0.8:
            out.append(_finding(
                f'STRATEGY_NEGATIVE_{sid.upper()}', 'medium', f'{names.get(sid, sid)} 전략의 실전 결과가 손실입니다',
                f"종료 {row['closed']}건 · 평균 {row['avg_return_pct']}% · PF {row['profit_factor']}",
                '검증 규정에 따라 추천에서 내릴지 검토',
            ))
    return out


def build_report(history: dict | None = None) -> dict:
    history = history if history is not None else json.loads(HISTORY.read_text(encoding='utf-8'))
    items = load_items(history)
    closed = closed_items(items)
    days = sorted({x['_day'] for x in items if x['_day']})
    report = {
        'version': 1,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'status': 'FORWARD_DIAGNOSTICS',
        'scope': 'official_public_close_confirmed',
        'source': 'static/trade_history.json',
        'read_only': True,
        'production_rules_mutated': False,
        'first_market_date': days[0] if days else None,
        'last_market_date': days[-1] if days else None,
        'total_signals': len(items),
        'open_signals': len(items) - len(closed),
        'review_ready': len(closed) >= MIN_REVIEW_CLOSED,
        'minimum_closed_for_review': MIN_REVIEW_CLOSED,
        'overall': metrics(closed),
        'strategy_names': {str(x['strategy_id']): str(x['strategy_name']) for x in items if x.get('strategy_id') and x.get('strategy_name')},
        'by_strategy': _grouped(closed, lambda x: x.get('strategy_id') or 'unknown'),
        'by_month': _grouped(closed, lambda x: x['_day'][:7] or 'unknown'),
        'by_market_state': _grouped(closed, lambda x: x.get('market_state') or '미기록'),
        'by_outcome': _grouped(closed, lambda x: x.get('status_code') or 'unknown'),
        'target_reachability': target_reachability(closed),
        'stop_recovery': stop_recovery(closed),
        'score_calibration': score_calibration(closed),
        'signal_load': signal_load(items),
    }
    report['findings'] = findings(report)
    return report


def write_report(out: Path = OUT, history: dict | None = None) -> dict:
    report = build_report(history)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    report = write_report()
    print(json.dumps({
        'closed': report['overall'].get('closed'),
        'review_ready': report['review_ready'],
        'findings': [x['code'] for x in report['findings']],
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
