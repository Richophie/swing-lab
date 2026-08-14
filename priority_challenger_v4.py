from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path

from backtest_engine import market_buy_fill
from config import BACKTEST_HALF_SPREAD_BPS, BACKTEST_SLIPPAGE_BPS
from strategy_rules import ENTRY_GAP_ATR, ENTRY_GAP_PCT
import priority_challenger_v1 as engine
import priority_challenger_v2 as v2

ROOT = Path(__file__).parent
STATIC = ROOT / 'static'
V2_CALIBRATION = STATIC / 'priority_challenger_v2_calibration.json'
CALIBRATION = STATIC / 'priority_challenger_v4_calibration.json'
STATE = STATIC / 'priority_challenger_v4_state.json'

CHALLENGER_ID = 'priority_challenger_v4_same_day_rank1_full'
COMPARISON_BASELINE = v2.CHALLENGER_ID
HYPOTHESIS_FREEZE_DATE = '2026-08-14'
FORWARD_START_DATE = '2026-08-14'
TOP_RANK_RISK_BUDGET = 0.0075
TOP_RANK_RISK_BUDGET_PCT = 0.75
OTHER_RANK_RISK_BUDGET = 0.00375
OTHER_RANK_RISK_BUDGET_PCT = 0.375


def _load(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {} if default is None else default


def configure_engine() -> None:
    # Candidate generation, frozen quality, priority, execution and exits remain V2-identical.
    engine.CALIBRATION = CALIBRATION
    engine.STATE = STATE
    engine.CHALLENGER_ID = CHALLENGER_ID
    engine.FREEZE_DATE = HYPOTHESIS_FREEZE_DATE
    engine.FORWARD_START_DATE = FORWARD_START_DATE
    engine.RISK_BUDGET = TOP_RANK_RISK_BUDGET


def freeze_calibration() -> dict:
    """Freeze one coarse same-entry-day sizing rule before the 2026-08-14 US session."""
    configure_engine()
    if CALIBRATION.exists():
        data = _load(CALIBRATION)
        if data.get('challenger_id') != CHALLENGER_ID:
            raise RuntimeError('Existing V4 calibration belongs to another challenger')
        if data.get('hypothesis_freeze_date') != HYPOTHESIS_FREEZE_DATE:
            raise RuntimeError('Existing V4 calibration has different freeze metadata')
        rule = data.get('same_day_rank_risk') or {}
        if float(rule.get('rank1_risk_budget_pct') or 0.0) != TOP_RANK_RISK_BUDGET_PCT:
            raise RuntimeError('Existing V4 rank1 risk differs from frozen rule')
        if float(rule.get('other_risk_budget_pct') or 0.0) != OTHER_RANK_RISK_BUDGET_PCT:
            raise RuntimeError('Existing V4 non-rank1 risk differs from frozen rule')
        return data

    if not V2_CALIBRATION.exists():
        raise RuntimeError('Frozen V2 calibration is required before creating V4')
    base = _load(V2_CALIBRATION)
    if base.get('challenger_id') != COMPARISON_BASELINE or base.get('status') != 'FROZEN_FORWARD_ONLY':
        raise RuntimeError('V2 calibration is not the expected comparison baseline')
    if base.get('forward_start_date') != FORWARD_START_DATE:
        raise RuntimeError('V2 and V4 must share the exact forward start date')

    data = json.loads(json.dumps(base))
    data['challenger_id'] = CHALLENGER_ID
    data['created_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    data['freeze_date'] = HYPOTHESIS_FREEZE_DATE
    data['hypothesis_freeze_date'] = HYPOTHESIS_FREEZE_DATE
    data['forward_start_date'] = FORWARD_START_DATE
    data['comparison_baseline'] = COMPARISON_BASELINE
    data['risk_budget_pct'] = TOP_RANK_RISK_BUDGET_PCT
    data['source_v2_calibration_created_at'] = base.get('created_at')
    data['source_signal_calibration_freeze_date'] = base.get('freeze_date')
    data['same_day_rank_risk'] = {
        'rank_definition': 'Among gap/fill-valid candidates attempting the same next-session open, sort by frozen challenger_priority desc, then signal_key. Rank is assigned before duplicate/capacity/cash portfolio constraints.',
        'rank1_risk_budget_pct': TOP_RANK_RISK_BUDGET_PCT,
        'other_risk_budget_pct': OTHER_RANK_RISK_BUDGET_PCT,
        'candidate_rejection': False,
        'priority_formula_changed': False,
        'threshold_grid': False,
    }
    data['ab_isolation'] = {
        'same_family_as_v2': True,
        'same_frozen_universe_as_v2': True,
        'same_reference_distributions_as_v2': True,
        'same_quality_filter_as_v2': True,
        'same_priority_formula_as_v2': True,
        'same_entry_gap_and_exit_rules_as_v2': True,
        'same_max_positions_as_v2': True,
        'only_changed_rule': 'same_entry_day_rank_conditioned_risk_budget',
    }
    data['mutable'] = False
    data.setdefault('notes', []).extend([
        'V4 hypothesis was frozen on 2026-08-14 before the US regular session. Historical same-day rank evidence was already inspected and is development evidence, not V4 proof.',
        'V4 does not reject lower-ranked valid candidates. Rank1 keeps V2 0.75% account risk; every other valid candidate attempting that same entry day uses 0.375%.',
        'The binary 0.75/0.375 rule is intentionally coarse. No rank2/rank3/rank4 parameter grid is allowed during forward observation.',
        'If the preassigned rank1 is later blocked by duplicate/capacity/cash, lower ranks remain at 0.375%; the rank is not opportunistically promoted after seeing portfolio constraints.',
        'RESEARCH/FORWARD SHADOW ONLY. Production picker and live-order rules are untouched.',
    ])
    CALIBRATION.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return data


def _attempts_by_day(state: dict, frames: dict) -> tuple[dict[str, list[dict]], list[dict]]:
    """Preflight pending candidates using only information known at the attempted next open."""
    groups = defaultdict(list)
    terminal = []
    for pending in list(state.get('pending') or []):
        frame = frames.get(pending.get('symbol'))
        if frame is None or frame.empty:
            continue
        idx, bar = engine._first_bar_after(frame, str(pending.get('signal_date'))[:10])
        if idx is None:
            continue
        entry_date = idx.strftime('%Y-%m-%d')
        raw_open = float(bar['Open'])
        gap = max(ENTRY_GAP_ATR * engine._num(pending['atr']), ENTRY_GAP_PCT * engine._num(pending['signal_close']))
        if raw_open < engine._num(pending['buy_low']) - gap or raw_open > engine._num(pending['buy_high']) + gap:
            terminal.append({
                'pending': pending, 'entry_date': entry_date, 'raw_open': raw_open,
                'decision': 'REJECT_GAP',
            })
            continue
        entry = market_buy_fill(raw_open, BACKTEST_SLIPPAGE_BPS, BACKTEST_HALF_SPREAD_BPS)
        stop = engine._num(pending['stop']); target = pending.get('target')
        if entry <= stop or (target is not None and engine._num(target) > 0 and entry >= engine._num(target)):
            terminal.append({
                'pending': pending, 'entry_date': entry_date, 'raw_open': raw_open,
                'entry': entry, 'decision': 'REJECT_INVALID_FILL',
            })
            continue
        groups[entry_date].append({
            'pending': pending, 'entry_date': entry_date, 'raw_open': raw_open,
            'entry': entry, 'stop': stop, 'target': target,
        })
    return groups, terminal


def _rank_day(attempts: list[dict]) -> list[dict]:
    ordered = sorted(
        attempts,
        key=lambda x: (
            -engine._num(x['pending'].get('challenger_priority')),
            str(x['pending'].get('signal_key') or ''),
        ),
    )
    count = len(ordered)
    for rank, item in enumerate(ordered, start=1):
        item['entry_day_rank'] = rank
        item['entry_day_candidate_count'] = count
        item['risk_budget'] = TOP_RANK_RISK_BUDGET if rank == 1 else OTHER_RANK_RISK_BUDGET
        item['risk_budget_pct'] = TOP_RANK_RISK_BUDGET_PCT if rank == 1 else OTHER_RANK_RISK_BUDGET_PCT
        item['rank_reduced'] = rank != 1
    return ordered


def _fill_pending_v4(state: dict, frames: dict) -> None:
    groups, terminal = _attempts_by_day(state, frames)
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')

    for item in terminal:
        pending = item['pending']
        if pending not in state.get('pending', []):
            continue
        decision = {
            'at': now,
            'signal_key': pending['signal_key'], 'symbol': pending['symbol'],
            'strategy_id': pending['strategy_id'], 'signal_date': pending['signal_date'],
            'entry_date': item['entry_date'], 'priority': pending['challenger_priority'],
            'decision': item['decision'], 'raw_open_usd': round(item['raw_open'], 6),
        }
        if 'entry' in item:
            decision['entry_fill_usd'] = round(item['entry'], 6)
        state['decisions'].append(decision)
        state['pending'].remove(pending)

    for entry_date in sorted(groups):
        for item in _rank_day(groups[entry_date]):
            pending = item['pending']
            if pending not in state.get('pending', []):
                continue
            symbol = pending['symbol']; sid = pending['strategy_id']; key = pending['signal_key']
            decision = {
                'at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'signal_key': key, 'symbol': symbol, 'strategy_id': sid,
                'signal_date': pending['signal_date'], 'entry_date': entry_date,
                'priority': pending['challenger_priority'],
                'entry_day_rank': item['entry_day_rank'],
                'entry_day_candidate_count': item['entry_day_candidate_count'],
                'risk_budget_pct': item['risk_budget_pct'],
                'rank_reduced': item['rank_reduced'],
            }
            if any(p.get('symbol') == symbol for p in state.get('positions') or []):
                decision['decision'] = 'REJECT_DUPLICATE'; state['decisions'].append(decision); state['pending'].remove(pending); continue
            if len(state.get('positions') or []) >= engine.MAX_POSITIONS:
                decision['decision'] = 'REJECT_MAX_POSITIONS'; state['decisions'].append(decision); state['pending'].remove(pending); continue

            equity = engine._equity(state, frames)
            entry = float(item['entry']); stop = float(item['stop'])
            risk_fraction = max(.001, (entry - stop) / entry)
            desired = min(
                engine._num(state.get('cash_krw')),
                equity * float(item['risk_budget']) / risk_fraction,
                equity * engine.MAX_SHARE,
            )
            if desired < 1:
                decision.update({'decision': 'REJECT_CASH', 'desired_krw': round(desired, 2)})
                state['decisions'].append(decision); state['pending'].remove(pending); continue

            position = dict(pending)
            position.update({
                'id': key, 'status': 'OPEN', 'entry_date': entry_date,
                'raw_entry_open_usd': round(item['raw_open'], 6),
                'entry_fill_usd': round(entry, 6), 'notional_krw': round(desired, 2),
                'risk_fraction': round(risk_fraction, 6),
                'risk_budget_pct': item['risk_budget_pct'],
                'entry_day_rank': item['entry_day_rank'],
                'entry_day_candidate_count': item['entry_day_candidate_count'],
                'rank_reduced': item['rank_reduced'],
                'held_bars': 0, 'last_close_processed': '', 'opened_at': decision['at'],
            })
            state['cash_krw'] = round(engine._num(state.get('cash_krw')) - desired, 2)
            state['positions'].append(position); state['pending'].remove(pending)
            decision.update({
                'decision': 'FILLED', 'entry_fill_usd': round(entry, 6),
                'notional_krw': round(desired, 2), 'cash_after_krw': state['cash_krw'],
            })
            state['decisions'].append(decision)


def _summary_v4(state: dict, frames: dict) -> dict:
    summary = engine._summary(state, frames)
    fills = [x for x in state.get('decisions') or [] if x.get('decision') == 'FILLED']
    summary['same_day_rank_risk'] = {
        'rank1_risk_budget_pct': TOP_RANK_RISK_BUDGET_PCT,
        'other_risk_budget_pct': OTHER_RANK_RISK_BUDGET_PCT,
        'filled_rank1_full_risk': sum(int(x.get('entry_day_rank') or 0) == 1 for x in fills),
        'filled_other_half_risk': sum(int(x.get('entry_day_rank') or 0) > 1 for x in fills),
        'multi_candidate_day_fills': sum(int(x.get('entry_day_candidate_count') or 0) > 1 for x in fills),
    }
    return summary


def run_forward(now_utc: datetime | None = None) -> dict:
    configure_engine()
    calibration = freeze_calibration()
    scan = engine._load(engine.SCAN, {})
    state = engine._load(STATE, {})
    if not state:
        state = engine._default_state(calibration)
        state['version'] = 4
    if state.get('challenger_id') != CHALLENGER_ID or state.get('freeze_date') != HYPOTHESIS_FREEZE_DATE:
        raise RuntimeError('Refusing to mutate a state created by another challenger version')

    now = now_utc or datetime.now(timezone.utc)
    symbols = list(calibration.get('frozen_symbols') or [])
    frames, errors = engine._download_frames(symbols)
    state['errors'] = errors[-100:]

    _fill_pending_v4(state, frames)
    for position in list(state.get('positions') or []):
        frame = frames.get(position.get('symbol'))
        if frame is not None:
            engine._process_position(state, position, frame, now)

    market_state = engine._market_state(scan)
    seen = set(state.get('seen_signal_keys') or [])
    latest = []
    for symbol, frame in frames.items():
        completed = frame.iloc[:-1].copy() if engine._has_incomplete_daily_bar(frame, now) else frame.copy()
        if completed.empty:
            continue
        signal_day = completed.index[-1].strftime('%Y-%m-%d')
        if signal_day < FORWARD_START_DATE:
            continue
        for candidate in engine.candidates_for_symbol(symbol, completed, market_state, calibration):
            key = f"{candidate['signal_date']}|{symbol}|{candidate['strategy_id']}"
            candidate['signal_key'] = key
            latest.append(candidate)
            if key in seen:
                continue
            seen.add(key)
            decision = {
                'at': now.isoformat(timespec='seconds'), 'decision': 'SIGNAL_RECORDED',
                'signal_key': key, 'signal_date': candidate['signal_date'], 'symbol': symbol,
                'strategy_id': candidate['strategy_id'],
                'quality_percentile': candidate['quality_percentile'],
                'current_priority_percentile': candidate['current_priority_percentile'],
                'challenger_priority': candidate['challenger_priority'],
                'passes_frozen_quality': candidate['passes_frozen_quality'],
            }
            if candidate['passes_frozen_quality']:
                pending = dict(candidate); pending['recorded_at'] = decision['at']
                state['pending'].append(pending); decision['decision'] = 'PENDING_NEXT_OPEN'
            else:
                decision['decision'] = 'REJECT_FROZEN_QUALITY'
            state['decisions'].append(decision)

    state['seen_signal_keys'] = sorted(seen)[-10000:]
    state['last_candidates'] = sorted(latest, key=lambda x: (-x['challenger_priority'], x['symbol']))[:100]
    state['updated_at'] = now.isoformat(timespec='seconds')
    state['summary'] = _summary_v4(state, frames)
    state['comparison_baseline'] = COMPARISON_BASELINE
    state['risk_budget_pct'] = TOP_RANK_RISK_BUDGET_PCT
    state.setdefault('meta', {})['last_market_state'] = market_state
    state['meta']['last_completed_signal_date'] = max((str(x.index[-1].date()) for x in frames.values() if x is not None and not x.empty), default=None)
    state['meta']['comparison_baseline'] = COMPARISON_BASELINE
    state['meta']['rank1_risk_budget_pct'] = TOP_RANK_RISK_BUDGET_PCT
    state['meta']['other_rank_risk_budget_pct'] = OTHER_RANK_RISK_BUDGET_PCT
    state['meta']['ab_only_changed_rule'] = 'same_entry_day_rank_conditioned_risk_budget'
    state['meta']['hypothesis_freeze_date'] = HYPOTHESIS_FREEZE_DATE
    state['meta']['calibration_created_at'] = calibration.get('created_at')
    state['meta']['production_main_picker_mutated'] = False
    state['meta']['live_orders_mutated'] = False
    if len(state['decisions']) > 5000:
        state['decisions'] = state['decisions'][-5000:]
    if len(state['closed']) > 2000:
        state['closed'] = state['closed'][-2000:]
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    return state


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('freeze', 'run'), nargs='?', default='run')
    args = parser.parse_args()
    if args.command == 'freeze':
        d = freeze_calibration()
        print('frozen', d['challenger_id'], 'rank1 risk', TOP_RANK_RISK_BUDGET_PCT, 'other risk', OTHER_RANK_RISK_BUDGET_PCT, 'symbols', len(d.get('frozen_symbols') or []))
    else:
        s = run_forward()
        print(json.dumps({'summary': s.get('summary'), 'meta': s.get('meta')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
