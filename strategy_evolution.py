"""Strategy evolution: search entry rules and holding plans on history, then try to break them.

A candidate ("genome") is a small set of signal-day conditions plus a holding plan:
buy at the next open, hold N days, optional ATR stop and target. A genetic search
optimises candidates on TRAIN folds only. Survivors must then pass, in order:

1. VALIDATION   later years, same symbols      (never seen by the search)
2. SYMBOL TEST  TRAIN years, held-out symbols  (never seen by the search)
3. LOCKBOX      most recent period, all symbols (opened only for finalists)

Every run is appended to one ledger. The more candidates that reach validation,
the higher the bar becomes, so running the loop forever cannot buy a pass by luck.

Research only: nothing here changes production recommendations.
"""
from __future__ import annotations

from datetime import datetime, timezone
import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

from config import BACKTEST_COMMISSION_PCT, BACKTEST_HALF_SPREAD_BPS, BACKTEST_SLIPPAGE_BPS, BACKTEST_MAX_POSITIONS

OUT = Path('static/strategy_evolution.json')
SHADOW_OUT = Path('static/evolution_candidate_shadow.json')
PANEL_CACHE = Path('data/evolution_panel.npz')

# ---- time and symbol splits (fixed; changing them invalidates the ledger) ----
TRAIN_FOLDS = (('2017-11-01', '2019-06-30'), ('2019-07-01', '2021-03-31'), ('2021-04-01', '2022-12-31'))
VALIDATION = ('2023-01-01', '2024-12-31')
LOCKBOX = ('2025-01-01', '2099-12-31')
HOLDOUT_SYMBOL_PCT = 30
SPLIT_VERSION = 'split-v1-2026-11-11'

# ---- search space ----
# Swing horizon only: three trading days up to about a week and a half.
HOLDS = (3, 4, 5, 7)
STOPS_ATR = (None, 2.0, 3.0)
TARGETS_ATR = (None, 1.5, 3.0)
QUANTILES = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
MIN_CONDITIONS, MAX_CONDITIONS = 1, 4
MARKET_FEATURES = ('spy_ret5', 'spy_ret20', 'spy_dist_sma200')

# ---- always-on tradability filter ----
MIN_PRICE = 5.0
MIN_DOLLAR_VOLUME_LOG = 7.3  # about $20M a day

# ---- fitness and gates ----
MIN_FOLD_TRADES = 80
# A rule must fire on many separate days and show evidence in every era, otherwise a
# handful of crash days (2018-12, 2020-03) can carry an entire fold.
MIN_FOLD_SIGNAL_DAYS = 60
MIN_FOLD_T = 1.0
MIN_TRADES_PER_YEAR = 40
COMPLEXITY_PENALTY_PCT = 0.03
MIN_VALIDATION_TRADES = 100
BASE_ALPHA = 0.05
MIN_LOCKBOX_T = 1.0

POPULATION = 300
GENERATIONS = 30
ELITE = 20
FINALISTS = 5


# ---------------------------------------------------------------- panel ----
def build_panel(symbols: list[str] | None = None) -> dict:
    """Aligned (day x symbol) arrays of prices and signal-day features."""
    from entry_feature_pool import download, feature_frame
    from market_data import indicators, load_price_history, load_us_universe, prefilter_symbols
    from config import SCAN_CANDIDATE_LIMIT

    symbols = symbols or prefilter_symbols(load_us_universe(), SCAN_CANDIDATE_LIMIT)
    frames = download(symbols)
    spy = load_price_history('SPY', 'max')
    spy_close = spy['Close'].astype(float)
    market = pd.DataFrame({
        'spy_ret5': spy_close / spy_close.shift(5) - 1,
        'spy_ret20': spy_close / spy_close.shift(20) - 1,
        'spy_dist_sma200': spy_close / spy_close.rolling(200).mean() - 1,
    })
    return panel_from_frames(frames, market, feature_frame, indicators)


def panel_from_frames(frames: dict, market: pd.DataFrame, feature_frame, indicators) -> dict:
    names = sorted(frames)
    days = sorted(set().union(*[frames[s].index for s in names]))
    index = pd.DatetimeIndex(days)
    stack = lambda series_by_symbol: np.column_stack([series_by_symbol[s].reindex(index).to_numpy(dtype=np.float32) for s in names])
    price = {k: stack({s: frames[s][col].astype(float) for s in names}) for k, col in (('open', 'Open'), ('high', 'High'), ('low', 'Low'), ('close', 'Close'))}
    per_symbol = {s: feature_frame(frames[s]) for s in names}
    feature_names = list(next(iter(per_symbol.values())).columns)
    features = {f: stack({s: per_symbol[s][f] for s in names}) for f in feature_names}
    atr = stack({s: indicators(frames[s])['atr14'] for s in names})
    market = market.copy()
    market.index = pd.DatetimeIndex(market.index).tz_localize(None) if getattr(market.index, 'tz', None) is not None else pd.DatetimeIndex(market.index)
    for f in MARKET_FEATURES:
        column = market[f].reindex(index).ffill().to_numpy(dtype=np.float32)
        features[f] = np.repeat(column[:, None], len(names), axis=1)
    return {
        'dates': np.array([d.strftime('%Y-%m-%d') for d in index]), 'symbols': np.array(names),
        'atr': atr, **price, 'feature_names': list(features), 'features': features,
    }


def save_panel(panel: dict, path: Path = PANEL_CACHE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, dates=panel['dates'], symbols=panel['symbols'], atr=panel['atr'],
                        open=panel['open'], high=panel['high'], low=panel['low'], close=panel['close'],
                        feature_names=np.array(panel['feature_names']),
                        **{f'f_{k}': v for k, v in panel['features'].items()})


def load_panel(path: Path = PANEL_CACHE) -> dict:
    z = np.load(path, allow_pickle=False)
    names = [str(x) for x in z['feature_names']]
    return {
        'dates': z['dates'].astype(str), 'symbols': z['symbols'].astype(str), 'atr': z['atr'],
        'open': z['open'], 'high': z['high'], 'low': z['low'], 'close': z['close'],
        'feature_names': names, 'features': {k: z[f'f_{k}'] for k in names},
    }


# ------------------------------------------------------------ execution ----
def _ahead(a: np.ndarray, k: int) -> np.ndarray:
    """Value k trading days after each row; NaN where the future does not exist yet."""
    out = np.full_like(a, np.nan)
    if k < len(a):
        out[:-k] = a[k:]
    return out


def trade_returns(panel: dict, hold: int, stop_atr: float | None, target_atr: float | None) -> np.ndarray:
    """Net % return of buying at the next open after each (day, symbol) and following the plan.

    Stop is checked before target inside a bar; a gap through the stop fills at the open.
    """
    commission = BACKTEST_COMMISSION_PCT / 100.0
    friction = (BACKTEST_SLIPPAGE_BPS + BACKTEST_HALF_SPREAD_BPS) / 10000.0
    entry = _ahead(panel['open'], 1)
    atr = panel['atr']
    stop = entry - stop_atr * atr if stop_atr else None
    target = entry + target_atr * atr if target_atr else None
    exit_price = np.full_like(entry, np.nan)
    alive = np.isfinite(entry) & np.isfinite(atr) & (atr > 0)
    for k in range(1, hold + 1):
        o, h, l, c = (_ahead(panel[x], k) for x in ('open', 'high', 'low', 'close'))
        alive &= np.isfinite(c)
        if stop is not None:
            if k > 1:
                gap = alive & (o <= stop)
                exit_price[gap] = o[gap]; alive &= ~gap
            hit = alive & (l <= stop)
            exit_price[hit] = stop[hit]; alive &= ~hit
        if target is not None:
            hit = alive & (h >= target)
            exit_price[hit] = target[hit]; alive &= ~hit
        if k == hold:
            exit_price[alive] = c[alive]
    # A plan whose full holding window is not in the data yet has no outcome.
    exit_price[~np.isfinite(_ahead(panel['close'], hold))] = np.nan
    paid = entry * (1 + friction) * (1 + commission)
    received = exit_price * (1 - friction) * (1 - commission)
    return ((received / paid - 1.0) * 100.0).astype(np.float32)


# -------------------------------------------------------------- context ----
class Context:
    def __init__(self, panel: dict):
        self.panel = panel
        self.dates, self.symbols = panel['dates'], panel['symbols']
        self.feature_names = list(panel['feature_names'])
        self.features = panel['features']
        self.holdout_symbol = np.array([int(hashlib.sha256(s.encode()).hexdigest(), 16) % 100 < HOLDOUT_SYMBOL_PCT for s in self.symbols])
        self.tradable = (panel['close'] >= MIN_PRICE) & (self.features['dollar_volume_log'] >= MIN_DOLLAR_VOLUME_LOG)
        self._returns = {}
        train_rows = self.rows(TRAIN_FOLDS[0][0], TRAIN_FOLDS[-1][1])
        search = ~self.holdout_symbol
        # Thresholds come from TRAIN years on search symbols only.
        self.thresholds = {}
        for f in self.feature_names:
            sample = self.features[f][train_rows][:, search]
            sample = sample[np.isfinite(sample)]
            self.thresholds[f] = np.quantile(sample, QUANTILES) if sample.size else np.full(len(QUANTILES), np.nan)
        self.segments = {
            **{f'train_{i + 1}': (self.rows(a, b), search) for i, (a, b) in enumerate(TRAIN_FOLDS)},
            'validation': (self.rows(*VALIDATION), search),
            'symbol_test': (train_rows, self.holdout_symbol),
            'lockbox': (self.rows(*LOCKBOX), np.ones(len(self.symbols), dtype=bool)),
        }
        self.years = {name: self.span_years(self.dates[rows]) for name, (rows, _) in self.segments.items()}

    @staticmethod
    def span_years(days: np.ndarray) -> float:
        return (pd.Timestamp(str(days[-1])) - pd.Timestamp(str(days[0]))).days / 365.25 if len(days) > 1 else 0.0

    def rows(self, start: str, end: str) -> np.ndarray:
        return (self.dates >= start) & (self.dates <= end)

    def returns(self, genome: dict) -> np.ndarray:
        key = (genome['hold'], genome['stop_atr'], genome['target_atr'])
        if key not in self._returns:
            self._returns[key] = trade_returns(self.panel, *key)
        return self._returns[key]

    def signals(self, genome: dict) -> np.ndarray:
        mask = self.tradable.copy()
        for feature, op, q in genome['conditions']:
            threshold = self.thresholds[feature][q]
            values = self.features[feature]
            with np.errstate(invalid='ignore'):
                mask &= (values >= threshold) if op == '>=' else (values <= threshold)
        # Only a fresh setup counts: the condition must have been off for the whole previous holding
        # window. A condition that stays on for weeks is one trade, not one trade per day.
        hold = genome['hold']
        counts = np.cumsum(mask, axis=0, dtype=np.int32)
        before = np.zeros_like(counts); before[1:] = counts[:-1]
        window_start = np.zeros_like(counts); window_start[hold + 1:] = counts[:-(hold + 1)]
        return mask & ((before - window_start) == 0)


def segment_stats(returns: np.ndarray, signals: np.ndarray, rows: np.ndarray, cols: np.ndarray, years: float) -> dict:
    r = returns[rows][:, cols]
    taken = signals[rows][:, cols] & np.isfinite(r)
    n = int(taken.sum())
    if n == 0:
        return {'trades': 0}
    values = r[taken]
    wins, losses = values[values > 0], values[values < 0]
    # Trades opened on the same day share the market move, so the t-stat uses one number per day.
    per_day_sum = np.where(taken, r, 0.0).sum(axis=1)
    per_day_n = taken.sum(axis=1)
    daily = per_day_sum[per_day_n > 0] / per_day_n[per_day_n > 0]
    spread = float(daily.std(ddof=1)) if len(daily) > 1 else 0.0
    t = float(daily.mean() / spread * math.sqrt(len(daily))) if spread > 0 else 0.0
    return {
        'trades': n, 'avg_return_pct': round(float(values.mean()), 3), 'win_rate_pct': round(float(len(wins) / n * 100), 1),
        'profit_factor': round(float(wins.sum() / -losses.sum()), 3) if len(losses) else None,
        'signal_days': int(len(daily)), 't_stat': round(t, 2), 'trades_per_year': round(n / years, 1) if years > 0 else None,
    }


def evaluate(ctx: Context, genome: dict, names: tuple[str, ...]) -> dict:
    returns, signals = ctx.returns(genome), ctx.signals(genome)
    out = {}
    for name in names:
        rows, cols = ctx.segments[name]
        out[name] = segment_stats(returns, signals, rows, cols, ctx.years[name])
    return out


TRAIN_NAMES = tuple(f'train_{i + 1}' for i in range(len(TRAIN_FOLDS)))


def fitness(train: dict, n_conditions: int) -> float:
    """Worst TRAIN fold decides. A rule that only worked in one era scores badly."""
    folds = [train[name] for name in TRAIN_NAMES]
    if any(f.get('trades', 0) < MIN_FOLD_TRADES or f['signal_days'] < MIN_FOLD_SIGNAL_DAYS or f['t_stat'] < MIN_FOLD_T for f in folds):
        return float('-inf')
    if sum(f['trades_per_year'] or 0 for f in folds) / len(folds) < MIN_TRADES_PER_YEAR:
        return float('-inf')
    return min(f['avg_return_pct'] for f in folds) - COMPLEXITY_PENALTY_PCT * n_conditions


# --------------------------------------------------------------- genome ----
def genome_key(genome: dict) -> str:
    conditions = sorted(f'{f}{op}{q}' for f, op, q in genome['conditions'])
    return f"{'&'.join(conditions)}|h{genome['hold']}|s{genome['stop_atr']}|t{genome['target_atr']}"


def random_condition(rng, features: list[str]):
    return (str(rng.choice(features)), str(rng.choice(['>=', '<='])), int(rng.integers(len(QUANTILES))))


def normalise(genome: dict) -> dict:
    """One condition per feature and direction, so a rule cannot contradict or repeat itself."""
    seen, conditions = set(), []
    for f, op, q in genome['conditions']:
        if (f, op) not in seen:
            seen.add((f, op)); conditions.append((f, op, int(q)))
    genome['conditions'] = conditions[:MAX_CONDITIONS]
    return genome


def random_genome(rng, features: list[str]) -> dict:
    n = int(rng.integers(MIN_CONDITIONS, MAX_CONDITIONS + 1))
    pick = lambda options: options[int(rng.integers(len(options)))]
    return normalise({'conditions': [random_condition(rng, features) for _ in range(n)],
                      'hold': pick(HOLDS), 'stop_atr': pick(STOPS_ATR), 'target_atr': pick(TARGETS_ATR)})


def mutate(rng, genome: dict, features: list[str]) -> dict:
    g = {**genome, 'conditions': list(genome['conditions'])}
    pick = lambda options: options[int(rng.integers(len(options)))]
    move = rng.random()
    if move < 0.35 and g['conditions']:
        i = int(rng.integers(len(g['conditions']))); f, op, q = g['conditions'][i]
        g['conditions'][i] = (f, op, int(np.clip(q + rng.choice([-1, 1]), 0, len(QUANTILES) - 1)))
    elif move < 0.55 and g['conditions']:
        g['conditions'][int(rng.integers(len(g['conditions'])))] = random_condition(rng, features)
    elif move < 0.70 and len(g['conditions']) < MAX_CONDITIONS:
        g['conditions'].append(random_condition(rng, features))
    elif move < 0.80 and len(g['conditions']) > MIN_CONDITIONS:
        g['conditions'].pop(int(rng.integers(len(g['conditions']))))
    elif move < 0.90:
        g['hold'] = pick(HOLDS)
    else:
        g['stop_atr'], g['target_atr'] = pick(STOPS_ATR), pick(TARGETS_ATR)
    return normalise(g)


def crossover(rng, a: dict, b: dict) -> dict:
    pool = list(a['conditions']) + list(b['conditions'])
    rng.shuffle(pool)
    n = int(rng.integers(MIN_CONDITIONS, MAX_CONDITIONS + 1))
    parent = a if rng.random() < 0.5 else b
    return normalise({'conditions': pool[:n], 'hold': parent['hold'], 'stop_atr': parent['stop_atr'], 'target_atr': parent['target_atr']})


def evolve(ctx: Context, seed: int, seeds: list[dict] | None = None, population: int = POPULATION, generations: int = GENERATIONS) -> tuple[list[dict], int]:
    """Genetic search on TRAIN folds only. Returns candidates sorted by fitness and how many were scored."""
    rng = np.random.default_rng(seed)
    scored: dict[str, dict] = {}

    def score(genome: dict) -> dict:
        key = genome_key(genome)
        if key not in scored:
            train = evaluate(ctx, genome, TRAIN_NAMES)
            # Seeds from an older ledger may use plans that are no longer in the search space.
            in_space = genome['hold'] in HOLDS and genome['stop_atr'] in STOPS_ATR and genome['target_atr'] in TARGETS_ATR
            scored[key] = {'key': key, 'genome': genome, 'train': train,
                           'fitness': fitness(train, len(genome['conditions'])) if in_space else float('-inf')}
        return scored[key]

    current = [score(normalise(dict(g, conditions=[tuple(c) for c in g['conditions']]))) for g in (seeds or [])]
    current += [score(random_genome(rng, ctx.feature_names)) for _ in range(population - len(current))]
    for _ in range(generations):
        current.sort(key=lambda x: x['fitness'], reverse=True)
        elite = current[:ELITE]
        children = []
        while len(children) < population - ELITE:
            contenders = [current[int(rng.integers(len(current)))] for _ in range(4)]
            a, b = sorted(contenders, key=lambda x: x['fitness'], reverse=True)[:2]
            child = crossover(rng, a['genome'], b['genome']) if rng.random() < 0.5 else dict(a['genome'], conditions=list(a['genome']['conditions']))
            children.append(score(mutate(rng, child, ctx.feature_names)))
        current = elite + children
    ranked = sorted((x for x in scored.values() if math.isfinite(x['fitness'])), key=lambda x: x['fitness'], reverse=True)
    return ranked, len(scored)


# ---------------------------------------------------------------- gates ----
def required_t(validation_looks: int) -> float:
    """One-sided bar for VALIDATION, raised as more candidates are ever allowed to look."""
    return NormalDist().inv_cdf(1 - BASE_ALPHA / max(1, validation_looks))


def distinct_finalists(ranked: list[dict], limit: int = FINALISTS) -> list[dict]:
    """Best candidates that do not share the same set of features."""
    out, seen = [], set()
    for item in ranked:
        signature = (frozenset(f for f, _, _ in item['genome']['conditions']), item['genome']['hold'])
        if signature not in seen:
            seen.add(signature); out.append(item)
        if len(out) == limit:
            break
    return out


def gate(ctx: Context, item: dict, t_required: float) -> dict:
    """Validation, then symbol test, then lockbox. A later stage is only opened if the earlier one passes."""
    genome = item['genome']
    result = {'stage_failed': None, 'lockbox_opened': False}
    v = evaluate(ctx, genome, ('validation',))['validation']
    result['validation'] = v
    if v.get('trades', 0) < MIN_VALIDATION_TRADES or v['signal_days'] < MIN_FOLD_SIGNAL_DAYS or v['avg_return_pct'] <= 0 or (v['profit_factor'] is not None and v['profit_factor'] <= 1) or v['t_stat'] < t_required:
        result['stage_failed'] = 'validation'
        return result
    s = evaluate(ctx, genome, ('symbol_test',))['symbol_test']
    result['symbol_test'] = s
    if s.get('trades', 0) < MIN_FOLD_TRADES or s['avg_return_pct'] <= 0:
        result['stage_failed'] = 'symbol_test'
        return result
    box = evaluate(ctx, genome, ('lockbox',))['lockbox']
    result['lockbox'], result['lockbox_opened'] = box, True
    if box.get('trades', 0) < MIN_FOLD_TRADES or box['avg_return_pct'] <= 0 or box['t_stat'] < MIN_LOCKBOX_T:
        result['stage_failed'] = 'lockbox'
    return result


def portfolio(ctx: Context, genome: dict, slots: int = BACKTEST_MAX_POSITIONS) -> dict:
    """What a person with a few equal slots would have earned taking signals as they came."""
    returns, signals = ctx.returns(genome), ctx.signals(genome)
    liquidity = ctx.features['dollar_volume_log']
    hold = genome['hold']
    free_at = [0] * slots
    equity, peak, max_drawdown = 1.0, 1.0, 0.0
    taken, by_year = 0, {}
    for day in range(len(ctx.dates)):
        candidates = np.flatnonzero(signals[day] & np.isfinite(returns[day]))
        if not len(candidates):
            continue
        # More liquid names first: a fixed, non-predictive tie-break.
        for symbol in candidates[np.argsort(-liquidity[day][candidates])]:
            slot = next((i for i in range(slots) if free_at[i] <= day), None)
            if slot is None:
                break
            free_at[slot] = day + hold + 1
            change = float(returns[day, symbol]) / 100.0 / slots
            equity *= 1.0 + change
            peak = max(peak, equity); max_drawdown = min(max_drawdown, equity / peak - 1.0)
            year = ctx.dates[day][:4]; by_year[year] = by_year.get(year, 1.0) * (1.0 + change)
            taken += 1
    years = ctx.span_years(ctx.dates)
    return {
        'slots': slots, 'trades': taken, 'total_return_pct': round((equity - 1) * 100, 1),
        'cagr_pct': round((equity ** (1 / years) - 1) * 100, 2) if years > 0 and equity > 0 else None,
        'max_drawdown_pct': round(max_drawdown * 100, 1),
        'by_year_pct': {y: round((v - 1) * 100, 1) for y, v in sorted(by_year.items())},
        'note': '수익은 청산일이 아닌 진입일에 반영한 근사치입니다.',
    }


# --------------------------------------------------------------- ledger ----
def describe(genome: dict, ctx: Context, labels: dict) -> dict:
    conditions = []
    for f, op, q in genome['conditions']:
        conditions.append({'feature': f, 'label': labels.get(f, f), 'op': op, 'quantile': QUANTILES[q], 'threshold': round(float(ctx.thresholds[f][q]), 5)})
    return {'conditions': conditions, 'hold_days': genome['hold'], 'stop_atr': genome['stop_atr'], 'target_atr': genome['target_atr']}


def run(ctx: Context, ledger: dict, seed: int | None = None, population: int = POPULATION, generations: int = GENERATIONS) -> dict:
    from entry_feature_pool import FEATURES
    labels = {**FEATURES, 'spy_dist_sma200': 'SPY의 200일선과의 거리'}
    if ledger.get('split_version') not in (None, SPLIT_VERSION):
        raise RuntimeError('Ledger was built with another split; start a new ledger instead of mixing them')
    ledger.setdefault('split_version', SPLIT_VERSION)
    ledger.setdefault('runs', []); ledger.setdefault('hall_of_fame', []); ledger.setdefault('champions', [])
    ledger.setdefault('validation_looks', 0); ledger.setdefault('lockbox_looks', 0)
    seed = len(ledger['runs']) + 1 if seed is None else seed
    seeds = [h['genome'] for h in ledger['hall_of_fame'][:ELITE]]
    ranked, scored = evolve(ctx, seed, seeds, population, generations)
    already_judged = {h['key'] for h in ledger['hall_of_fame']}
    finalists = [x for x in distinct_finalists(ranked, FINALISTS * 3) if x['key'] not in already_judged][:FINALISTS]

    judged = []
    for item in finalists:
        ledger['validation_looks'] = ledger.get('validation_looks', 0) + 1
        t_required = required_t(ledger['validation_looks'])
        result = gate(ctx, item, t_required)
        ledger['lockbox_looks'] = ledger.get('lockbox_looks', 0) + int(result['lockbox_opened'])
        entry = {
            'key': item['key'], 'genome': {**item['genome'], 'conditions': [list(c) for c in item['genome']['conditions']]},
            'rule': describe(item['genome'], ctx, labels), 'fitness': round(item['fitness'], 4), 'train': item['train'],
            'validation_t_required': round(t_required, 2), **result, 'found_in_run': len(ledger['runs']) + 1,
            'passed_all': result['stage_failed'] is None,
        }
        if entry['passed_all']:
            entry['portfolio'] = portfolio(ctx, item['genome'])
            ledger['champions'].append(entry)
        judged.append(entry); ledger['hall_of_fame'].append(entry)
    ledger['hall_of_fame'].sort(key=lambda x: x['fitness'], reverse=True)
    ledger['hall_of_fame'] = ledger['hall_of_fame'][:200]
    ledger['candidates_scored_total'] = ledger.get('candidates_scored_total', 0) + scored
    ledger['runs'].append({
        'run': len(ledger['runs']) + 1, 'seed': seed, 'at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'candidates_scored': scored, 'best_train_fitness': round(ranked[0]['fitness'], 4) if ranked else None,
        'finalists': [x['key'] for x in judged], 'passed': [x['key'] for x in judged if x['passed_all']],
        'failed_at': {x['key']: x['stage_failed'] for x in judged if x['stage_failed']},
    })
    ledger.update({
        'version': 1, 'status': 'STRATEGY_EVOLUTION', 'research_only': True, 'production_rules_mutated': False,
        'updated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'data': {'first_date': str(ctx.dates[0]), 'last_date': str(ctx.dates[-1]), 'symbols': int(len(ctx.symbols)),
                 'search_symbols': int((~ctx.holdout_symbol).sum()), 'holdout_symbols': int(ctx.holdout_symbol.sum())},
        'splits': {'train_folds': TRAIN_FOLDS, 'validation': VALIDATION, 'lockbox': LOCKBOX, 'holdout_symbol_pct': HOLDOUT_SYMBOL_PCT},
        'search_space': {'holds': HOLDS, 'stops_atr': STOPS_ATR, 'targets_atr': TARGETS_ATR, 'quantiles': QUANTILES,
                         'max_conditions': MAX_CONDITIONS, 'features': ctx.feature_names},
        'gates': {'min_fold_trades': MIN_FOLD_TRADES, 'min_fold_signal_days': MIN_FOLD_SIGNAL_DAYS, 'min_fold_t': MIN_FOLD_T, 'min_trades_per_year': MIN_TRADES_PER_YEAR, 'min_validation_trades': MIN_VALIDATION_TRADES,
                  'validation_alpha': BASE_ALPHA, 'min_lockbox_t': MIN_LOCKBOX_T, 'next_validation_t_required': round(required_t(ledger.get('validation_looks', 0) + 1), 2)},
        'limitations': [
            '현재 유동성 상위 종목을 과거로 되감은 데이터라 생존편향이 있습니다.',
            '탐색을 오래 돌릴수록 우연히 좋아 보이는 규칙이 나옵니다. 그래서 검증 기준(t값)이 시도 횟수에 따라 올라갑니다.',
            '최종 시험 구간(lockbox)도 여러 번 열면 닳습니다. 연 횟수를 기록합니다.',
            '통과한 규칙도 실전 추천에 넣기 전에 사람이 확인합니다.',
        ],
    })
    return ledger


# ----------------------------------------------------- family candidates ----
def freeze_family_candidate(ctx: Context, ledger: dict, name: str, genome: dict, reason: str) -> dict:
    """Record one representative of a rule family and open the remaining tests for it once.

    Used when many near-identical finalists fail validation only because each one counted
    as a separate look. The representative must be chosen from TRAIN information alone.
    """
    from entry_feature_pool import FEATURES
    existing = next((c for c in ledger.setdefault('family_candidates', []) if c['name'] == name), None)
    if existing:
        return existing
    stats = evaluate(ctx, genome, TRAIN_NAMES + ('validation', 'symbol_test', 'lockbox'))
    ledger['validation_looks'] = ledger.get('validation_looks', 0) + 1
    ledger['lockbox_looks'] = ledger.get('lockbox_looks', 0) + 1
    entry = {
        'name': name, 'status': 'FORWARD_SHADOW', 'frozen_at': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'reason': reason, 'key': genome_key(genome),
        'genome': {**genome, 'conditions': [list(c) for c in genome['conditions']]},
        'rule': describe(genome, ctx, {**FEATURES, 'spy_dist_sma200': 'SPY의 200일선과의 거리'}),
        'stats': stats, 'portfolio': portfolio(ctx, genome),
        'passed_automatic_gate': False,
        'positive_in_every_segment': all((v.get('avg_return_pct') or 0) > 0 for v in stats.values()),
    }
    ledger['family_candidates'].append(entry)
    return entry


def track_candidates(ctx: Context, ledger: dict, shadow: dict) -> dict:
    """Append today's signals of frozen candidates and fill in outcomes that have matured.

    Signals are written on the day they appear and never edited, so this record is free of
    the survivorship bias that the historical panel carries.
    """
    shadow.setdefault('version', 1); shadow.setdefault('signals', [])
    shadow.update({'status': 'FORWARD_SHADOW', 'live_trading_enabled': False, 'production_mutation_enabled': False})
    known = {(x['candidate'], x['signal_date'], x['symbol']) for x in shadow['signals']}
    day_index = {str(d): i for i, d in enumerate(ctx.dates)}
    symbol_index = {str(s): i for i, s in enumerate(ctx.symbols)}
    last = len(ctx.dates) - 1
    for candidate in ledger.get('family_candidates') or []:
        genome = dict(candidate['genome'], conditions=[tuple(c) for c in candidate['genome']['conditions']])
        signals, returns = ctx.signals(genome), ctx.returns(genome)
        if str(ctx.dates[last]) >= candidate['frozen_at']:
            for j in np.flatnonzero(signals[last]):
                key = (candidate['name'], str(ctx.dates[last]), str(ctx.symbols[j]))
                if key in known:
                    continue
                known.add(key)
                shadow['signals'].append({
                    'candidate': key[0], 'signal_date': key[1], 'symbol': key[2],
                    'signal_close': round(float(ctx.panel['close'][last, j]), 4), 'atr': round(float(ctx.panel['atr'][last, j]), 4),
                    'plan': f"다음 거래일 시가 매수 · {genome['hold']}거래일 뒤 종가 매도", 'hold_days': genome['hold'],
                    'status': 'OPEN', 'return_pct': None,
                })
        for row in shadow['signals']:
            if row['candidate'] != candidate['name'] or row['status'] != 'OPEN':
                continue
            i, j = day_index.get(row['signal_date']), symbol_index.get(row['symbol'])
            if i is None or j is None:
                continue
            value = float(returns[i, j])
            if math.isfinite(value):
                row['status'], row['return_pct'] = 'CLOSED', round(value, 3)
    closed = [x['return_pct'] for x in shadow['signals'] if x['status'] == 'CLOSED']
    shadow['summary'] = {
        'signals': len(shadow['signals']), 'closed': len(closed),
        'avg_return_pct': round(float(np.mean(closed)), 3) if closed else None,
        'win_rate_pct': round(sum(1 for x in closed if x > 0) / len(closed) * 100, 1) if closed else None,
    }
    shadow['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    shadow['panel_last_date'] = str(ctx.dates[last])
    return shadow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runs', type=int, default=1)
    parser.add_argument('--rebuild-panel', action='store_true')
    parser.add_argument('--population', type=int, default=POPULATION)
    parser.add_argument('--generations', type=int, default=GENERATIONS)
    args = parser.parse_args()
    if args.rebuild_panel or not PANEL_CACHE.exists():
        save_panel(build_panel())
    ctx = Context(load_panel())
    ledger = json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {}
    shadow = json.loads(SHADOW_OUT.read_text(encoding='utf-8')) if SHADOW_OUT.exists() else {}
    SHADOW_OUT.write_text(json.dumps(track_candidates(ctx, ledger, shadow), ensure_ascii=False, indent=1), encoding='utf-8')
    for _ in range(args.runs):
        ledger = run(ctx, ledger, population=args.population, generations=args.generations)
        last = ledger['runs'][-1]
        print(json.dumps({'run': last['run'], 'scored': last['candidates_scored'], 'best_train': last['best_train_fitness'],
                          'passed': len(last['passed']), 'failed_at': list(last['failed_at'].values())}, ensure_ascii=False), flush=True)
        OUT.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
