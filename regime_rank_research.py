"""Market-regime gate and daily top-N research for the public strategies.

Forward diagnostics showed two things: 86% of losing recommendations were made
while the market state read "좋음", and the account has three slots while a day
can publish thirty picks. This module tests, on the replay pool:

1. a few pre-registered market gates that react faster than the current
   120/200-day trend score, and
2. whether keeping only the top N picks of a day by a known-at-signal ranking
   beats taking all of them.

Chosen on TRAIN only, OOS is pass/fail. Research only; production is untouched.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean

import pandas as pd

from config import BACKTEST_MAX_POSITIONS
from exit_policy_research import (
    FORWARD_START_DATE, MIN_OOS_TRADES, MIN_TRAIN_EDGE_PCT, MIN_TRAIN_TRADES, POLICIES, POOL,
    PUBLIC_STRATEGIES, costs, execute, metrics, split_cutoff, split_of,
)
from market_data import indicators, load_price_history

OUT = Path('static/regime_rank_research.json')
INDEX_SYMBOLS = ('SPY', 'QQQ')
MIN_KEEP_FRACTION = 0.40
TOP_N = BACKTEST_MAX_POSITIONS

# One idea per gate. Each uses only index data known at the signal-day close.
GATES = {
    'current': {'label': '현재 규칙', 'note': '시장 상태가 조심만 아니면 추천'},
    'good_only': {'label': '좋음일 때만', 'note': '시장 상태가 좋음인 날만 추천'},
    'above_sma50': {'label': '50일선 위', 'note': 'SPY와 QQQ가 모두 50일 평균 위'},
    'above_sma20': {'label': '20일선 위', 'note': 'SPY와 QQQ가 모두 20일 평균 위'},
    'ret20_positive': {'label': '한 달 수익 플러스', 'note': 'SPY의 최근 20거래일 수익률이 0보다 큼'},
    'not_sliding': {'label': '급락 중 제외', 'note': 'SPY의 최근 5거래일 수익률이 -2%보다 나쁘면 쉼'},
    'below_sma20': {'label': '20일선 아래', 'note': '반대 가설: 시장이 눌렸을 때만 추천'},
}
RANKERS = {
    'all': {'label': '전부', 'note': '그날 나온 추천을 모두 계산'},
    'top_elite': {'label': f'엄선점수 상위 {TOP_N}개', 'note': '현재 화면의 정렬 기준', 'key': 'elite_score'},
    'top_reward_risk': {'label': f'손익비 상위 {TOP_N}개', 'note': '비용 반영 손익비가 높은 순', 'key': 'net_risk_reward'},
    'top_liquidity': {'label': f'거래대금 상위 {TOP_N}개', 'note': '20일 평균 거래대금이 큰 순', 'key': 'avg_dollar_volume_20d'},
}


def index_features(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Per-date index conditions. Every column is known at that day's close."""
    cols = {}
    for symbol, frame in frames.items():
        ind = indicators(frame)
        close = frame['Close'].astype(float)
        cols[f'{symbol}_above20'] = close > ind['sma20']
        cols[f'{symbol}_above50'] = close > ind['sma50']
        cols[f'{symbol}_ret20'] = close / close.shift(20) - 1.0
        cols[f'{symbol}_ret5'] = close / close.shift(5) - 1.0
    out = pd.DataFrame(cols)
    out.index = [idx.strftime('%Y-%m-%d') for idx in out.index]
    return out


def gate_allows(gate: str, candidate: dict, row) -> bool:
    if gate == 'current':
        return True
    if gate == 'good_only':
        return candidate.get('market_state') == '좋음'
    if row is None:
        return False
    if gate == 'above_sma50':
        return bool(row['SPY_above50'] and row['QQQ_above50'])
    if gate == 'above_sma20':
        return bool(row['SPY_above20'] and row['QQQ_above20'])
    if gate == 'below_sma20':
        return not bool(row['SPY_above20'] and row['QQQ_above20'])
    if gate == 'ret20_positive':
        return bool(row['SPY_ret20'] > 0)
    if gate == 'not_sliding':
        return bool(row['SPY_ret5'] > -0.02)
    raise ValueError(gate)


def rank_value(candidate: dict, key: str) -> float:
    if key == 'avg_dollar_volume_20d':
        return float((candidate.get('smart_money_flow') or {}).get(key) or 0.0)
    return float(candidate.get(key) or 0.0)


def top_n_per_day(trades: list[dict], key: str, n: int = TOP_N) -> list[dict]:
    by_day = defaultdict(list)
    for trade in trades:
        by_day[trade['signal_date']].append(trade)
    kept = []
    for day in sorted(by_day):
        ranked = sorted(by_day[day], key=lambda t: (-rank_value(t['candidate'], key), str(t['symbol'])))
        kept.extend(ranked[:n])
    return kept


def _by_split(trades: list[dict], cutoff: str) -> dict:
    buckets = defaultdict(list)
    for trade in trades:
        buckets[split_of(trade['signal_date'], cutoff)].append(trade)
    return {name: metrics(buckets[name]) for name in ('train', 'oos', 'forward')}


def judge(row: dict, base: dict, keep_fraction: float | None = None) -> tuple[bool, list[str]]:
    train, oos = row['train'], row['oos']
    if train.get('trades', 0) < MIN_TRAIN_TRADES or oos.get('trades', 0) < MIN_OOS_TRADES:
        return False, ['표본 부족']
    reasons = []
    if keep_fraction is not None and keep_fraction < MIN_KEEP_FRACTION:
        reasons.append('추천이 너무 많이 줄어듦')
    if train['avg_return_pct'] - base['train']['avg_return_pct'] < MIN_TRAIN_EDGE_PCT:
        reasons.append('학습구간에서 현재 규칙보다 뚜렷하게 낫지 않음')
    if oos['avg_return_pct'] <= 0 or (oos.get('profit_factor') or 0) <= 1:
        reasons.append('검증구간에서 이익이 아님')
    if oos['avg_return_pct'] <= base['oos'].get('avg_return_pct', 0):
        reasons.append('검증구간에서 현재 규칙보다 낫지 않음')
    return not reasons, reasons


def _pick(table: dict, baseline: str) -> tuple[str | None, bool]:
    """Best TRAIN average among challengers; OOS can veto but never re-rank."""
    challengers = [k for k in table if k != baseline and table[k]['train'].get('trades', 0) >= MIN_TRAIN_TRADES]
    pick = max(challengers, key=lambda k: table[k]['train']['avg_return_pct'], default=None)
    return pick, bool(pick and table[pick]['passes_gate'])


def gate_table(trades: list[dict], features: pd.DataFrame, cutoff: str) -> dict:
    rows = features.to_dict('index')
    developed = sum(1 for t in trades if t['signal_date'] < FORWARD_START_DATE)
    table = {}
    for key, spec in GATES.items():
        kept = [t for t in trades if gate_allows(key, t['candidate'], rows.get(t['signal_date']))]
        kept_dev = sum(1 for t in kept if t['signal_date'] < FORWARD_START_DATE)
        table[key] = {**spec, **_by_split(kept, cutoff), 'keep_fraction': round(kept_dev / developed, 3) if developed else None}
    for key, row in table.items():
        row['passes_gate'], row['fail_reasons'] = (None, []) if key == 'current' else judge(row, table['current'], row['keep_fraction'])
    pick, ok = _pick(table, 'current')
    return {'gates': table, 'train_pick': pick, 'train_pick_passes_oos': ok}


def rank_table(trades: list[dict], cutoff: str) -> dict:
    table = {}
    for key, spec in RANKERS.items():
        kept = trades if key == 'all' else top_n_per_day(trades, spec['key'])
        table[key] = {'label': spec['label'], 'note': spec['note'], **_by_split(kept, cutoff)}
    for key, row in table.items():
        row['passes_gate'], row['fail_reasons'] = (None, []) if key == 'all' else judge(row, table['all'])
    pick, ok = _pick(table, 'all')
    return {'rankers': table, 'train_pick': pick, 'train_pick_passes_oos': ok, 'top_n': TOP_N}


def executed_trades(candidates: list[dict], commission: float, friction: float) -> list[dict]:
    out = []
    for candidate in candidates:
        trade = execute(candidate, POLICIES['baseline'], commission, friction)
        if trade:
            trade['candidate'] = candidate
            out.append(trade)
    return out


def load_index_frames() -> dict[str, pd.DataFrame]:
    return {symbol: load_price_history(symbol, 'max') for symbol in INDEX_SYMBOLS}


def build_report(pool: dict | None = None, frames: dict | None = None) -> dict:
    pool = pool if pool is not None else json.loads(POOL.read_text(encoding='utf-8'))
    features = index_features(frames if frames is not None else load_index_frames())
    commission, friction = costs(pool)
    candidates = [c for c in pool.get('trades') or [] if c.get('strategy_id') in PUBLIC_STRATEGIES]
    cutoff = split_cutoff(candidates)
    trades = executed_trades(candidates, commission, friction)
    names = pool.get('strategy_names') or {}
    by_strategy = {
        sid: {'name': names.get(sid, sid), **gate_table([t for t in trades if t['strategy_id'] == sid], features, cutoff)}
        for sid in PUBLIC_STRATEGIES
    }
    days = defaultdict(int)
    for trade in trades:
        days[trade['signal_date']] += 1
    return {
        'version': 1,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'status': 'REGIME_RANK_RESEARCH',
        'research_only': True,
        'production_rules_mutated': False,
        'pool_generated_at': pool.get('generated_at'),
        'train_end_exclusive': cutoff,
        'forward_start_date': FORWARD_START_DATE,
        'regime_all_strategies': gate_table(trades, features, cutoff),
        'regime_by_strategy': by_strategy,
        'ranking': rank_table(trades, cutoff),
        'signal_days': len(days),
        'avg_signals_per_day': round(mean(days.values()), 2) if days else None,
        'limitations': [
            '후보풀이 80종목이라 실제 추천(500종목)보다 하루 추천 수가 적습니다. 상위 N개 효과는 실제보다 작게 보일 수 있습니다.',
            '현재 유동성 상위 종목을 과거로 되감은 풀이라 생존편향이 있습니다.',
            '건별 계산이며 계좌 현금·동시보유 제한은 반영하지 않았습니다.',
        ],
    }


def write_report(out: Path = OUT) -> dict:
    report = build_report()
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    report = write_report()
    print(json.dumps({
        'regime': [report['regime_all_strategies']['train_pick'], report['regime_all_strategies']['train_pick_passes_oos']],
        'ranking': [report['ranking']['train_pick'], report['ranking']['train_pick_passes_oos']],
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
