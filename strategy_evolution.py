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

from datetime import datetime, timedelta, timezone
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
# v2: the universe is historical S&P 500 membership on the signal day, not today's large caps.
SPLIT_VERSION = 'split-v2-pit-lite-2026-11-11'

# ---- search space ----
# Swing horizon only: three trading days up to about a week and a half.
HOLDS = (3, 4, 5, 7)
STOPS_ATR = (None, 2.0, 3.0)
TARGETS_ATR = (None, 1.5, 3.0)
QUANTILES = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
# Up to six conditions at once: a rule is the overlap (intersection) of all of them.
MIN_CONDITIONS, MAX_CONDITIONS = 1, 6

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
# Two rules that pick the same stock in the same week more than half the time are one idea, not two.
SAME_FAMILY_OVERLAP = 0.5
# Watched alongside the frozen plan (washout_plan_research): a next-day limit this far below the signal close.
LIMIT_ENTRY_DISCOUNT_ATR = 0.5


# ---------------------------------------------------------------- panel ----
def membership_mask(dates: np.ndarray, symbols: np.ndarray, snapshots: list[dict]) -> np.ndarray:
    """True where the symbol was an index member on that day (latest snapshot on or before it)."""
    from bisect import bisect_right
    days = [row['date'].isoformat() for row in snapshots]
    members = [set(row['members']) for row in snapshots]
    column = {str(s): j for j, s in enumerate(symbols)}
    mask = np.zeros((len(dates), len(symbols)), dtype=bool)
    for i, day in enumerate(dates):
        k = bisect_right(days, str(day)) - 1
        for symbol in (members[k] if k >= 0 else ()):
            j = column.get(symbol)
            if j is not None:
                mask[i, j] = True
    return mask


def evolution_features(d: pd.DataFrame) -> pd.DataFrame:
    """Everything the search may condition on for one symbol: the entry-pool features plus the indicator library."""
    from entry_feature_pool import feature_frame
    from indicator_library import extra_features
    return pd.concat([feature_frame(d), extra_features(d)], axis=1)


def last_completed_session(now: datetime | None = None) -> str:
    """Latest date whose regular US session has certainly closed.

    The data source returns a half-finished bar for today while the market is open. A signal read
    from it is wrong (volume looks low, the close is not the close), so such a day is never used.
    21:30 UTC is after the close in both winter and summer time.
    """
    now = now or datetime.now(timezone.utc)
    return (now - timedelta(hours=21, minutes=30)).date().isoformat()


def build_panel(frames: dict | None = None) -> dict:
    """Aligned (day x symbol) arrays of prices and signal-day features.

    Universe: every company that was in the S&P 500 at some point since mid-2016 and whose
    prices are still published. A day only counts while the company was a member, so a
    company that later shrank out of the index stays in the test. Companies whose prices
    are gone (delisted, merged) cannot be included; that part of survivorship bias remains.
    """
    from entry_feature_pool import download
    from indicator_library import add_panel_features, market_features
    from market_data import indicators, load_price_history
    from sp500_pit_diagnostic import fetch_snapshots

    snapshots = fetch_snapshots()
    symbols = sorted(set().union(*[set(r['members']) for r in snapshots if r['date'].isoformat() >= '2016-06-01']))
    latest = set(snapshots[-1]['members'])
    frames = download(symbols) if frames is None else frames
    cutoff = last_completed_session()
    frames = {s: f.loc[:cutoff] for s, f in frames.items()}
    frames = {s: f for s, f in frames.items() if len(f)}
    try:
        vix = load_price_history('^VIX', 'max')
    except Exception:
        vix = None
    market = market_features(load_price_history('SPY', 'max'), vix)
    panel = panel_from_frames(frames, market, evolution_features, indicators)
    panel['member'] = membership_mask(panel['dates'], panel['symbols'], snapshots)
    add_panel_features(panel['features'], panel['member'])
    panel['feature_names'] = list(panel['features'])
    panel['current_member'] = np.array([str(s) in latest for s in panel['symbols']])
    panel['requested_symbols'] = len(symbols)
    return panel


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
    for f in market.columns:
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
                        member=panel.get('member', np.ones_like(panel['close'], dtype=bool)),
                        current_member=panel.get('current_member', np.ones(len(panel['symbols']), dtype=bool)),
                        requested_symbols=np.array(panel.get('requested_symbols', len(panel['symbols']))),
                        **{f'f_{k}': v for k, v in panel['features'].items()})


def load_panel(path: Path = PANEL_CACHE) -> dict:
    z = np.load(path, allow_pickle=False)
    names = [str(x) for x in z['feature_names']]
    return {
        'dates': z['dates'].astype(str), 'symbols': z['symbols'].astype(str), 'atr': z['atr'],
        'open': z['open'], 'high': z['high'], 'low': z['low'], 'close': z['close'],
        'feature_names': names, 'features': {k: z[f'f_{k}'] for k in names},
        'member': z['member'], 'current_member': z['current_member'], 'requested_symbols': int(z['requested_symbols']),
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
        if 'member' in panel:
            self.tradable &= panel['member']
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
        return self.signals_at([(f, op, self.thresholds[f][q]) for f, op, q in genome['conditions']], genome['hold'])

    def signals_at(self, conditions: list[tuple], hold: int) -> np.ndarray:
        """Signals for (feature, op, absolute threshold) conditions."""
        mask = self.tradable.copy()
        for feature, op, threshold in conditions:
            values = self.features[feature]
            with np.errstate(invalid='ignore'):
                mask &= (values >= threshold) if op == '>=' else (values <= threshold)
        # Only a fresh setup counts: the condition must have been off for the whole previous holding
        # window. A condition that stays on for weeks is one trade, not one trade per day.
        counts = np.cumsum(mask, axis=0, dtype=np.int32)
        before = np.zeros_like(counts); before[1:] = counts[:-1]
        window_start = np.zeros_like(counts); window_start[hold + 1:] = counts[:-(hold + 1)]
        return mask & ((before - window_start) == 0)


def footprint(signals: np.ndarray) -> np.ndarray:
    """Which (week, symbol) cells a rule trades. Uses signals only, never outcomes."""
    days, cols = np.nonzero(signals)
    return np.unique((days // 5).astype(np.int64) * signals.shape[1] + cols)


def overlap(a: np.ndarray, b: np.ndarray) -> float:
    smaller = min(len(a), len(b))
    return len(np.intersect1d(a, b, assume_unique=True)) / smaller if smaller else 0.0


def same_family(mark: np.ndarray, others: list[np.ndarray]) -> bool:
    return any(overlap(mark, other) > SAME_FAMILY_OVERLAP for other in others)


def entry_footprint(ctx: Context, entry: dict) -> np.ndarray:
    """Footprint of a rule already in the ledger, from its frozen absolute thresholds."""
    return footprint(frozen_signals(ctx, entry)[1])


def judged_families(ctx: Context, ledger: dict) -> list[np.ndarray]:
    """One footprint per distinct idea that has already been shown validation data."""
    families: list[np.ndarray] = []
    for entry in (ledger.get('family_candidates') or []) + (ledger.get('hall_of_fame') or []):
        if any(c['feature'] not in ctx.features for c in entry['rule']['conditions']):
            continue
        mark = entry_footprint(ctx, entry)
        if len(mark) and not same_family(mark, families):
            families.append(mark)
    return families


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


def climb_score(train: dict, value: float) -> float:
    """Selection score inside the search. A rule that fails the hard limits still gets a slope to climb:
    first towards enough trades, then towards evidence in every fold. Never used to judge a rule."""
    if math.isfinite(value):
        return value
    folds = [train[name] for name in TRAIN_NAMES]
    enough = min(min(f.get('trades', 0) / MIN_FOLD_TRADES, f.get('signal_days', 0) / MIN_FOLD_SIGNAL_DAYS, 1.0) for f in folds)
    if enough < 1.0:
        return -2000.0 + 100.0 * enough
    return -1000.0 + max(-50.0, min(f['t_stat'] for f in folds))


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


def evolve(ctx: Context, seed: int, seeds: list[dict] | None = None, population: int = POPULATION, generations: int = GENERATIONS,
           taboo: list[np.ndarray] | None = None) -> tuple[list[dict], int]:
    """Genetic search on TRAIN folds only. Returns candidates sorted by fitness and how many were scored.

    `taboo` holds footprints of ideas that were already judged. A candidate that mostly repeats one
    of them scores nothing, which pushes the search towards rules it has not tried yet.
    """
    rng = np.random.default_rng(seed)
    scored: dict[str, dict] = {}

    def score(genome: dict) -> dict:
        key = genome_key(genome)
        if key not in scored:
            train = evaluate(ctx, genome, TRAIN_NAMES)
            # Seeds from an older ledger may use plans that are no longer in the search space.
            in_space = genome['hold'] in HOLDS and genome['stop_atr'] in STOPS_ATR and genome['target_atr'] in TARGETS_ATR
            value = fitness(train, len(genome['conditions'])) if in_space else float('-inf')
            climb = climb_score(train, value)
            # Checked for every rule with enough trades, so the search is steered away early.
            if taboo and climb > -1500 and same_family(footprint(ctx.signals(genome)), taboo):
                value, climb = float('-inf'), -3000.0
            scored[key] = {'key': key, 'genome': genome, 'train': train, 'fitness': value, 'climb': climb}
        return scored[key]

    current = [score(normalise(dict(g, conditions=[tuple(c) for c in g['conditions']]))) for g in (seeds or [])]
    current += [score(random_genome(rng, ctx.feature_names)) for _ in range(population - len(current))]
    for _ in range(generations):
        current.sort(key=lambda x: x['climb'], reverse=True)
        elite = current[:ELITE]
        children = []
        while len(children) < population - ELITE:
            contenders = [current[int(rng.integers(len(current)))] for _ in range(4)]
            a, b = sorted(contenders, key=lambda x: x['climb'], reverse=True)[:2]
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


def neighbour_floor(ctx: Context, genome: dict) -> float:
    """Worst TRAIN-fold average return of the rule and of its neighbours (one threshold moved one step).

    A real effect survives a small change of a threshold; a rule fitted to noise often does not.
    Uses TRAIN folds only, so it costs no validation look.
    """
    floor = float('inf')
    variants = [genome]
    for i, (f, op, q) in enumerate(genome['conditions']):
        for step in (-1, 1):
            if 0 <= q + step < len(QUANTILES):
                conditions = list(genome['conditions']); conditions[i] = (f, op, q + step)
                variants.append({**genome, 'conditions': conditions})
    for variant in variants:
        folds = list(evaluate(ctx, variant, TRAIN_NAMES).values())
        # A tighter neighbour may simply trade too rarely to say anything.
        if any(fold.get('trades', 0) < MIN_FOLD_TRADES // 2 for fold in folds):
            continue
        floor = min(floor, min(fold['avg_return_pct'] for fold in folds))
    return floor if math.isfinite(floor) else float('-inf')


def prune(ctx: Context, genome: dict) -> dict:
    """Drop conditions that do not change which trades the rule takes."""
    genome = {**genome, 'conditions': list(genome['conditions'])}
    mark = footprint(ctx.signals(genome))
    i = 0
    while len(genome['conditions']) > MIN_CONDITIONS and i < len(genome['conditions']):
        shorter = {**genome, 'conditions': genome['conditions'][:i] + genome['conditions'][i + 1:]}
        other = footprint(ctx.signals(shorter))
        if len(other) <= len(mark) * 1.02 and overlap(mark, other) >= 0.98:
            genome, mark = shorter, other
        else:
            i += 1
    return genome


def pick_finalists(ctx: Context, ranked: list[dict], taboo: list[np.ndarray], limit: int = FINALISTS, scan: int = 60) -> tuple[list[dict], int]:
    """Best robust candidates, each a different idea from the others and from everything judged before."""
    chosen, marks, examined, seen = [], list(taboo), 0, set()
    for item in ranked:
        if examined >= scan or len(chosen) >= limit:
            break
        genome = prune(ctx, item['genome'])
        key = genome_key(genome)
        if key in seen:
            continue
        seen.add(key)
        mark = footprint(ctx.signals(genome))
        if same_family(mark, marks):
            continue
        examined += 1
        train = evaluate(ctx, genome, TRAIN_NAMES)
        value = fitness(train, len(genome['conditions']))
        floor = neighbour_floor(ctx, genome)
        # Only rules that stay profitable when a threshold is nudged may spend a validation look.
        if not math.isfinite(value) or floor <= 0:
            continue
        chosen.append({'key': key, 'genome': genome, 'train': train, 'fitness': value, 'neighbour_floor': floor})
        marks.append(mark)
    return chosen, examined


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


def feature_labels() -> dict:
    from entry_feature_pool import FEATURES
    from indicator_library import LABELS
    return {**FEATURES, **LABELS}


def run(ctx: Context, ledger: dict, seed: int | None = None, population: int = POPULATION, generations: int = GENERATIONS) -> dict:
    labels = feature_labels()
    if ledger.get('split_version') not in (None, SPLIT_VERSION):
        raise RuntimeError('Ledger was built with another split; start a new ledger instead of mixing them')
    ledger.setdefault('split_version', SPLIT_VERSION)
    ledger.setdefault('runs', []); ledger.setdefault('hall_of_fame', []); ledger.setdefault('champions', [])
    ledger.setdefault('validation_looks', 0); ledger.setdefault('lockbox_looks', 0)
    seed = len(ledger['runs']) + 1 if seed is None else seed
    taboo = judged_families(ctx, ledger)
    # The bar counts distinct ideas, not near-copies of one idea.
    ledger['validation_families'] = max(ledger.get('validation_families', 0), len(taboo))
    ranked, scored = evolve(ctx, seed, None, population, generations, taboo)
    finalists, examined = pick_finalists(ctx, ranked, taboo)

    judged = []
    for item in finalists:
        ledger['validation_looks'] = ledger.get('validation_looks', 0) + 1
        ledger['validation_families'] += 1
        t_required = required_t(ledger['validation_families'])
        result = gate(ctx, item, t_required)
        ledger['lockbox_looks'] = ledger.get('lockbox_looks', 0) + int(result['lockbox_opened'])
        entry = {
            'key': item['key'], 'genome': {**item['genome'], 'conditions': [list(c) for c in item['genome']['conditions']]},
            'rule': describe(item['genome'], ctx, labels), 'fitness': round(item['fitness'], 4), 'neighbour_floor': round(item['neighbour_floor'], 3), 'train': item['train'],
            'validation_t_required': round(t_required, 2), **result, 'found_in_run': len(ledger['runs']) + 1,
            'passed_all': result['stage_failed'] is None,
        }
        if entry['passed_all']:
            entry['portfolio'] = portfolio(ctx, item['genome'])
            ledger['champions'].append(entry)
        judged.append(entry); ledger['hall_of_fame'].append(entry)
    track_champions(ledger)
    ledger['hall_of_fame'].sort(key=lambda x: x['fitness'], reverse=True)
    ledger['hall_of_fame'] = ledger['hall_of_fame'][:200]
    ledger['candidates_scored_total'] = ledger.get('candidates_scored_total', 0) + scored
    ledger['runs'].append({
        'run': len(ledger['runs']) + 1, 'seed': seed, 'at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'candidates_scored': scored, 'best_train_fitness': round(ranked[0]['fitness'], 4) if ranked else None,
        'new_ideas_examined': examined, 'finalists': [x['key'] for x in judged], 'passed': [x['key'] for x in judged if x['passed_all']],
        'failed_at': {x['key']: x['stage_failed'] for x in judged if x['stage_failed']},
    })
    ledger.update({
        'version': 1, 'status': 'STRATEGY_EVOLUTION', 'research_only': True, 'production_rules_mutated': False,
        'updated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'universe': 'S&P 500 구성 이력(커뮤니티 자료) 기준, 신호일에 지수 구성종목이던 회사만. 가격이 남아 있지 않은 상장폐지·합병 회사는 제외됨',
        'data': {'first_date': str(ctx.dates[0]), 'last_date': str(ctx.dates[-1]), 'symbols': int(len(ctx.symbols)),
                 'requested_symbols': int(ctx.panel.get('requested_symbols', len(ctx.symbols))),
                 'search_symbols': int((~ctx.holdout_symbol).sum()), 'holdout_symbols': int(ctx.holdout_symbol.sum())},
        'splits': {'train_folds': TRAIN_FOLDS, 'validation': VALIDATION, 'lockbox': LOCKBOX, 'holdout_symbol_pct': HOLDOUT_SYMBOL_PCT},
        'search_space': {'holds': HOLDS, 'stops_atr': STOPS_ATR, 'targets_atr': TARGETS_ATR, 'quantiles': QUANTILES,
                         'max_conditions': MAX_CONDITIONS, 'features': ctx.feature_names},
        'gates': {'min_fold_trades': MIN_FOLD_TRADES, 'min_fold_signal_days': MIN_FOLD_SIGNAL_DAYS, 'min_fold_t': MIN_FOLD_T, 'neighbour_floor_must_be_positive': True, 'min_trades_per_year': MIN_TRADES_PER_YEAR, 'min_validation_trades': MIN_VALIDATION_TRADES,
                  'validation_alpha': BASE_ALPHA, 'min_lockbox_t': MIN_LOCKBOX_T, 'same_family_overlap': SAME_FAMILY_OVERLAP,
                  'next_validation_t_required': round(required_t(ledger.get('validation_families', 0) + 1), 2)},
        'limitations': [
            '지수에서 빠진 뒤 상장폐지·합병된 회사는 가격이 남아 있지 않아 빠져 있습니다. 생존편향이 일부 남습니다.',
            '탐색을 오래 돌릴수록 우연히 좋아 보이는 규칙이 나옵니다. 그래서 검증 기준(t값)이 검증에 올린 서로 다른 아이디어 수에 따라 올라갑니다.',
            '같은 주에 같은 종목을 절반 넘게 겹쳐 고르는 규칙은 하나의 아이디어로 셉니다. 이미 판정한 아이디어와 겹치는 규칙은 다시 검증하지 않습니다.',
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
    existing = next((c for c in ledger.setdefault('family_candidates', []) if c['name'] == name), None)
    if existing:
        return existing
    stats = evaluate(ctx, genome, TRAIN_NAMES + ('validation', 'symbol_test', 'lockbox'))
    ledger['validation_looks'] = ledger.get('validation_looks', 0) + 1
    ledger['validation_families'] = ledger.get('validation_families', 0) + 1
    ledger['lockbox_looks'] = ledger.get('lockbox_looks', 0) + 1
    entry = {
        'name': name, 'status': 'FORWARD_SHADOW', 'frozen_at': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'reason': reason, 'key': genome_key(genome),
        'genome': {**genome, 'conditions': [list(c) for c in genome['conditions']]},
        'rule': describe(genome, ctx, feature_labels()),
        'stats': stats, 'portfolio': portfolio(ctx, genome),
        'passed_automatic_gate': False,
        'positive_in_every_segment': all((v.get('avg_return_pct') or 0) > 0 for v in stats.values()),
    }
    ledger['family_candidates'].append(entry)
    return entry


def track_champions(ledger: dict) -> None:
    """Every rule that passed all gates gets an append-only forward record from the day it passed."""
    tracked = {c['key'] for c in ledger.setdefault('family_candidates', [])}
    for champion in ledger.get('champions') or []:
        if champion['key'] in tracked:
            continue
        number = 1 + sum(1 for c in ledger['family_candidates'] if c.get('passed_automatic_gate'))
        ledger['family_candidates'].append({
            'name': f'evolved_champion_v{number}', 'status': 'FORWARD_SHADOW',
            'frozen_at': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            'reason': f"run {champion['found_in_run']}: passed validation, symbol test and lockbox",
            'key': champion['key'], 'genome': champion['genome'], 'rule': champion['rule'],
            'stats': {**champion['train'], 'validation': champion['validation'], 'symbol_test': champion['symbol_test'], 'lockbox': champion['lockbox']},
            'portfolio': champion.get('portfolio'), 'passed_automatic_gate': True, 'positive_in_every_segment': True,
        })
        tracked.add(champion['key'])


def frozen_signals(ctx: Context, candidate: dict) -> tuple[dict, np.ndarray]:
    """Signals from the candidate's frozen absolute thresholds, whatever panel is loaded."""
    genome = {**candidate['genome'], 'conditions': [tuple(c) for c in candidate['genome']['conditions']]}
    conditions = [(c['feature'], c['op'], c['threshold']) for c in candidate['rule']['conditions']]
    return genome, ctx.signals_at(conditions, genome['hold'])


def limit_entry_outcome(panel: dict, day: int, col: int, limit: float, hold: int) -> tuple[bool, float | None] | None:
    """Whether a next-day limit order would have filled and its net % return when sold at the close of the last hold day.

    None while the holding window is not complete. Fill assumes the order is done whenever the low reaches the limit.
    """
    last = day + hold
    if last >= len(panel['close']) or not np.isfinite(panel['close'][last, col]):
        return None
    low, open_ = float(panel['low'][day + 1, col]), float(panel['open'][day + 1, col])
    if not low <= limit:
        return False, None
    commission = BACKTEST_COMMISSION_PCT / 100.0
    friction = (BACKTEST_SLIPPAGE_BPS + BACKTEST_HALF_SPREAD_BPS) / 10000.0
    paid = min(open_, limit) * (1 + friction) * (1 + commission)
    received = float(panel['close'][last, col]) * (1 - friction) * (1 - commission)
    return True, (received / paid - 1.0) * 100.0


def outlook(ctx: Context, candidate: dict) -> dict:
    """How this rule's past trades ended, so a signal can show a realistic range instead of a single target price."""
    genome, signals = frozen_signals(ctx, candidate)
    returns = ctx.returns(genome)
    values = returns[signals & np.isfinite(returns)]
    if len(values) < 100:
        return {'trades': int(len(values))}
    low, middle, high = (round(float(v), 2) for v in np.percentile(values, [25, 50, 75]))
    return {'trades': int(len(values)), 'p25_return_pct': low, 'median_return_pct': middle, 'p75_return_pct': high,
            'win_rate_pct': round(float((values > 0).mean() * 100), 1), 'big_loss_share_pct': round(float((values <= -10).mean() * 100), 1)}


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
        genome, signals = frozen_signals(ctx, candidate)
        returns = ctx.returns(genome)
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
                    'limit_price': round(float(ctx.panel['close'][last, j] - LIMIT_ENTRY_DISCOUNT_ATR * ctx.panel['atr'][last, j]), 4),
                    'limit_filled': None, 'limit_return_pct': None,
                    'stop_atr': genome['stop_atr'], 'entry_date': None, 'entry_price': None,
                    'exit_date': None, 'last_close': None, 'days_held': 0,
                })
        for row in shadow['signals']:
            if row['candidate'] != candidate['name'] or row['status'] != 'OPEN':
                continue
            i, j = day_index.get(row['signal_date']), symbol_index.get(row['symbol'])
            if i is None or j is None:
                continue
            # What a person following the plan needs to see: the price they bought at and where it stands now.
            hold = row['hold_days']
            if i + 1 <= last and np.isfinite(ctx.panel['open'][i + 1, j]):
                row['entry_date'], row['entry_price'] = str(ctx.dates[i + 1]), round(float(ctx.panel['open'][i + 1, j]), 4)
                row['days_held'] = int(min(last - i, hold))
                row['last_close'] = round(float(ctx.panel['close'][min(last, i + hold), j]), 4)
            if i + hold <= last:
                row['exit_date'] = str(ctx.dates[i + hold])
            value = float(returns[i, j])
            if math.isfinite(value):
                row['status'], row['return_pct'] = 'CLOSED', round(value, 3)
            if row.get('limit_price') is not None and row.get('limit_filled') is None:
                outcome = limit_entry_outcome(ctx.panel, i, j, row['limit_price'], row['hold_days'])
                if outcome is not None:
                    row['limit_filled'] = outcome[0]
                    row['limit_return_pct'] = round(outcome[1], 3) if outcome[0] else None
    shadow['outlook'] = {c['name']: outlook(ctx, c) for c in ledger.get('family_candidates') or []}
    closed = [x['return_pct'] for x in shadow['signals'] if x['status'] == 'CLOSED']
    limit = [x['limit_return_pct'] for x in shadow['signals'] if x.get('limit_filled')]
    shadow['limit_entry'] = {
        'discount_atr': LIMIT_ENTRY_DISCOUNT_ATR, 'exit': '보유 마지막 날 종가 매도(손절 없음)',
        'decided': sum(1 for x in shadow['signals'] if x.get('limit_filled') is not None), 'filled': len(limit),
        'avg_return_pct': round(float(np.mean(limit)), 3) if limit else None,
        'win_rate_pct': round(sum(1 for x in limit if x > 0) / len(limit) * 100, 1) if limit else None,
        'note': '저가가 지정가에 닿으면 체결된 것으로 봅니다. 관찰용 기록이며 규칙의 공식 성적이 아닙니다.',
    }
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
    print(json.dumps({'panel_first_date': str(ctx.dates[0]), 'panel_last_date': str(ctx.dates[-1]), 'last_completed_session': last_completed_session(),
                      'symbols': int(len(ctx.symbols))}), flush=True)
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
