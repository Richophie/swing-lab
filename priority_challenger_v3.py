from __future__ import annotations

from datetime import datetime, timezone
import argparse
import json
import math
from pathlib import Path

import pandas as pd

from backtest_engine import market_buy_fill
from config import BACKTEST_HALF_SPREAD_BPS, BACKTEST_SLIPPAGE_BPS
from strategy_rules import ENTRY_GAP_ATR, ENTRY_GAP_PCT
import priority_challenger_v1 as engine

ROOT = Path(__file__).parent
STATIC = ROOT / 'static'
V2_CALIBRATION = STATIC / 'priority_challenger_v2_calibration.json'
CALIBRATION = STATIC / 'priority_challenger_v3_calibration.json'
STATE = STATIC / 'priority_challenger_v3_state.json'

CHALLENGER_ID = 'priority_challenger_v3_corr075_half'
COMPARISON_BASELINE = 'priority_challenger_v2_capital075'
HYPOTHESIS_FREEZE_DATE = '2026-08-14'
FORWARD_START_DATE = '2026-08-14'
BASE_RISK_BUDGET = 0.0075
BASE_RISK_BUDGET_PCT = 0.75
DAMPED_RISK_BUDGET = 0.00375
DAMPED_RISK_BUDGET_PCT = 0.375
CORR_THRESHOLD = 0.75
LOOKBACK_SESSIONS = 60
MIN_OVERLAP_SESSIONS = 40


def _load(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {} if default is None else default


def configure_engine() -> None:
    # Candidate generation/exits are inherited exactly from the frozen V1/V2 engine.
    engine.CALIBRATION = CALIBRATION
    engine.STATE = STATE
    engine.CHALLENGER_ID = CHALLENGER_ID
    engine.FREEZE_DATE = HYPOTHESIS_FREEZE_DATE
    engine.FORWARD_START_DATE = FORWARD_START_DATE
    engine.RISK_BUDGET = BASE_RISK_BUDGET


def freeze_calibration() -> dict:
    """Freeze V3 before the 2026-08-14 US session; never retune it afterward."""
    configure_engine()
    if CALIBRATION.exists():
        data = _load(CALIBRATION)
        if data.get('challenger_id') != CHALLENGER_ID:
            raise RuntimeError('Existing V3 calibration belongs to another challenger')
        if data.get('hypothesis_freeze_date') != HYPOTHESIS_FREEZE_DATE:
            raise RuntimeError('Existing V3 calibration has different hypothesis freeze metadata')
        if float((data.get('correlation_risk_damp') or {}).get('threshold') or 0.0) != CORR_THRESHOLD:
            raise RuntimeError('Existing V3 calibration has a different correlation threshold')
        return data

    if not V2_CALIBRATION.exists():
        raise RuntimeError('Frozen V2 calibration is required before creating V3')
    v2 = _load(V2_CALIBRATION)
    if v2.get('challenger_id') != COMPARISON_BASELINE or v2.get('status') != 'FROZEN_FORWARD_ONLY':
        raise RuntimeError('V2 calibration is not the expected frozen comparison baseline')
    if v2.get('forward_start_date') != FORWARD_START_DATE:
        raise RuntimeError('V2 and V3 must observe the same first forward signal date')

    data = json.loads(json.dumps(v2))
    data['challenger_id'] = CHALLENGER_ID
    data['created_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    data['freeze_date'] = HYPOTHESIS_FREEZE_DATE
    data['hypothesis_freeze_date'] = HYPOTHESIS_FREEZE_DATE
    data['forward_start_date'] = FORWARD_START_DATE
    data['comparison_baseline'] = COMPARISON_BASELINE
    data['risk_budget_pct'] = BASE_RISK_BUDGET_PCT
    data['source_v2_calibration_created_at'] = v2.get('created_at')
    data['source_signal_calibration_freeze_date'] = v2.get('freeze_date')
    data['correlation_risk_damp'] = {
        'lookback_sessions': LOOKBACK_SESSIONS,
        'minimum_overlap_sessions': MIN_OVERLAP_SESSIONS,
        'threshold': CORR_THRESHOLD,
        'base_risk_budget_pct': BASE_RISK_BUDGET_PCT,
        'damped_risk_budget_pct': DAMPED_RISK_BUDGET_PCT,
        'condition': 'If a fresh candidate has trailing-60-session return correlation >= 0.75 with any position already open in the V3 book, halve only that fresh entry risk budget.',
        'insufficient_history': 'Use the full 0.75% V2 risk budget and log insufficient correlation coverage; never reject the candidate.',
        'candidate_rejection': False,
    }
    data['ab_isolation'] = {
        'same_family_as_v2': True,
        'same_frozen_universe_as_v2': True,
        'same_reference_distributions_as_v2': True,
        'same_quality_filter_as_v2': True,
        'same_priority_formula_as_v2': True,
        'same_entry_and_exit_rules_as_v2': True,
        'base_risk_same_as_v2': True,
        'only_changed_rule': 'correlation_conditioned_fresh_entry_risk_budget',
    }
    data['mutable'] = False
    data.setdefault('notes', []).extend([
        'V3 가설은 2026-08-14 미국 정규장 시작 전에 동결했습니다. 2021~2026 corr_half 결과는 이미 본 development evidence이며 V3의 최종 검증 데이터가 아닙니다.',
        'V3는 V2와 같은 후보·엄선·우선순위·진입·자연청산을 사용하고, 이미 열린 V3 포지션과 trailing-60d correlation >=0.75인 신규 진입의 위험예산만 0.75%→0.375%로 줄입니다.',
        '0.75 threshold, 60-session lookback, half-risk multiplier를 forward 중 자동 변경하지 않습니다.',
        'RESEARCH/FORWARD SHADOW ONLY. production 메인 종목선정과 실제 주문 규칙을 변경하지 않습니다.',
    ])
    CALIBRATION.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return data


def _return_series(frame: pd.DataFrame, asof: str) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype=float)
    col = 'Adj Close' if 'Adj Close' in frame.columns else 'Close'
    s = pd.to_numeric(frame[col], errors='coerce').dropna()
    if s.empty:
        return pd.Series(dtype=float)
    s = s.loc[:pd.Timestamp(str(asof)[:10])]
    return s.astype(float).pct_change().replace([float('inf'), float('-inf')], float('nan')).dropna().tail(LOOKBACK_SESSIONS)


def trailing_corr(frame_a: pd.DataFrame, frame_b: pd.DataFrame, asof: str):
    a = _return_series(frame_a, asof).rename('a')
    b = _return_series(frame_b, asof).rename('b')
    joined = pd.concat([a, b], axis=1, join='inner').dropna().tail(LOOKBACK_SESSIONS)
    if len(joined) < MIN_OVERLAP_SESSIONS:
        return None
    value = joined['a'].corr(joined['b'])
    if value is None or not math.isfinite(float(value)):
        return None
    return float(value)


def correlation_risk_context(pending: dict, state: dict, frames: dict[str, pd.DataFrame]) -> dict:
    symbol = str(pending.get('symbol') or '')
    asof = str(pending.get('signal_date') or '')[:10]
    open_positions = list(state.get('positions') or [])
    if not open_positions:
        return {
            'risk_budget': BASE_RISK_BUDGET,
            'risk_budget_pct': BASE_RISK_BUDGET_PCT,
            'corr_reduced': False,
            'max_peer_corr': None,
            'corr_peer': None,
            'corr_pairs_available': 0,
            'corr_pairs_required': 0,
            'corr_coverage': 'NO_OPEN_PEERS',
        }

    values = []
    for position in open_positions:
        peer = str(position.get('symbol') or '')
        if not peer or peer == symbol:
            continue
        value = trailing_corr(frames.get(symbol), frames.get(peer), asof)
        if value is not None:
            values.append((value, peer))
    max_pair = max(values, key=lambda x: x[0]) if values else (None, None)
    max_corr, peer = max_pair
    reduced = max_corr is not None and float(max_corr) >= CORR_THRESHOLD
    return {
        'risk_budget': DAMPED_RISK_BUDGET if reduced else BASE_RISK_BUDGET,
        'risk_budget_pct': DAMPED_RISK_BUDGET_PCT if reduced else BASE_RISK_BUDGET_PCT,
        'corr_reduced': bool(reduced),
        'max_peer_corr': None if max_corr is None else round(float(max_corr), 6),
        'corr_peer': peer,
        'corr_pairs_available': len(values),
        'corr_pairs_required': len([p for p in open_positions if p.get('symbol') != symbol]),
        'corr_coverage': 'AVAILABLE' if values else 'INSUFFICIENT_HISTORY',
    }


def _fill_pending_v3(state: dict, frames: dict[str, pd.DataFrame]) -> None:
    attempts = []
    for pending in list(state.get('pending') or []):
        frame = frames.get(pending.get('symbol'))
        if frame is None or frame.empty:
            continue
        idx, bar = engine._first_bar_after(frame, str(pending.get('signal_date'))[:10])
        if idx is None:
            continue
        attempts.append((idx.strftime('%Y-%m-%d'), -engine._num(pending.get('challenger_priority')), str(pending.get('symbol')), pending, bar))

    for entry_date, _, _, pending, bar in sorted(attempts, key=lambda x: (x[0], x[1], x[2])):
        if pending not in state.get('pending', []):
            continue
        symbol = pending['symbol']; sid = pending['strategy_id']; key = pending['signal_key']
        raw_open = float(bar['Open'])
        decision = {
            'at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'signal_key': key, 'symbol': symbol, 'strategy_id': sid,
            'signal_date': pending['signal_date'], 'entry_date': entry_date,
            'priority': pending['challenger_priority'],
        }
        if any(p.get('symbol') == symbol for p in state.get('positions') or []):
            decision['decision'] = 'REJECT_DUPLICATE'; state['decisions'].append(decision); state['pending'].remove(pending); continue
        if len(state.get('positions') or []) >= engine.MAX_POSITIONS:
            decision['decision'] = 'REJECT_MAX_POSITIONS'; state['decisions'].append(decision); state['pending'].remove(pending); continue
        gap = max(ENTRY_GAP_ATR * engine._num(pending['atr']), ENTRY_GAP_PCT * engine._num(pending['signal_close']))
        if raw_open < engine._num(pending['buy_low']) - gap or raw_open > engine._num(pending['buy_high']) + gap:
            decision.update({'decision': 'REJECT_GAP', 'raw_open_usd': round(raw_open, 6)}); state['decisions'].append(decision); state['pending'].remove(pending); continue
        entry = market_buy_fill(raw_open, BACKTEST_SLIPPAGE_BPS, BACKTEST_HALF_SPREAD_BPS)
        stop = engine._num(pending['stop']); target = pending.get('target')
        if entry <= stop or (target is not None and engine._num(target) > 0 and entry >= engine._num(target)):
            decision.update({'decision': 'REJECT_INVALID_FILL', 'entry_fill_usd': round(entry, 6)}); state['decisions'].append(decision); state['pending'].remove(pending); continue

        corr = correlation_risk_context(pending, state, frames)
        equity = engine._equity(state, frames)
        risk_fraction = max(.001, (entry - stop) / entry)
        desired = min(
            engine._num(state.get('cash_krw')),
            equity * float(corr['risk_budget']) / risk_fraction,
            equity * engine.MAX_SHARE,
        )
        decision.update({k: v for k, v in corr.items() if k != 'risk_budget'})
        if desired < 1:
            decision.update({'decision': 'REJECT_CASH', 'desired_krw': round(desired, 2)}); state['decisions'].append(decision); state['pending'].remove(pending); continue

        position = dict(pending)
        position.update({
            'id': key, 'status': 'OPEN', 'entry_date': entry_date,
            'raw_entry_open_usd': round(raw_open, 6), 'entry_fill_usd': round(entry, 6),
            'notional_krw': round(desired, 2), 'risk_fraction': round(risk_fraction, 6),
            'risk_budget_pct': corr['risk_budget_pct'], 'corr_reduced': corr['corr_reduced'],
            'entry_max_peer_corr': corr['max_peer_corr'], 'entry_corr_peer': corr['corr_peer'],
            'entry_corr_coverage': corr['corr_coverage'], 'held_bars': 0,
            'last_close_processed': '', 'opened_at': decision['at'],
        })
        state['cash_krw'] = round(engine._num(state.get('cash_krw')) - desired, 2)
        state['positions'].append(position); state['pending'].remove(pending)
        decision.update({
            'decision': 'FILLED', 'entry_fill_usd': round(entry, 6),
            'notional_krw': round(desired, 2), 'cash_after_krw': state['cash_krw'],
        })
        state['decisions'].append(decision)


def _v3_summary(state: dict, frames: dict[str, pd.DataFrame]) -> dict:
    summary = engine._summary(state, frames)
    fills = [x for x in state.get('decisions') or [] if x.get('decision') == 'FILLED']
    summary['correlation_risk'] = {
        'base_risk_budget_pct': BASE_RISK_BUDGET_PCT,
        'damped_risk_budget_pct': DAMPED_RISK_BUDGET_PCT,
        'threshold': CORR_THRESHOLD,
        'lookback_sessions': LOOKBACK_SESSIONS,
        'filled_full_risk': sum(not bool(x.get('corr_reduced')) for x in fills),
        'filled_damped_risk': sum(bool(x.get('corr_reduced')) for x in fills),
        'filled_insufficient_history_full_risk': sum(x.get('corr_coverage') == 'INSUFFICIENT_HISTORY' for x in fills),
    }
    return summary


def run_forward(now_utc: datetime | None = None) -> dict:
    configure_engine()
    calibration = freeze_calibration()
    scan = engine._load(engine.SCAN, {})
    state = engine._load(STATE, {})
    if not state:
        state = engine._default_state(calibration)
        state['version'] = 3
    if state.get('challenger_id') != CHALLENGER_ID or state.get('freeze_date') != HYPOTHESIS_FREEZE_DATE:
        raise RuntimeError('Refusing to mutate a state created by another challenger version')

    now = now_utc or datetime.now(timezone.utc)
    symbols = list(calibration.get('frozen_symbols') or [])
    frames, errors = engine._download_frames(symbols)
    state['errors'] = errors[-100:]

    _fill_pending_v3(state, frames)
    for position in list(state.get('positions') or []):
        frame = frames.get(position.get('symbol'))
        if frame is not None:
            engine._process_position(state, position, frame, now)

    market_state = engine._market_state(scan); seen = set(state.get('seen_signal_keys') or [])
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
            candidate['signal_key'] = key; latest.append(candidate)
            if key in seen:
                continue
            seen.add(key)
            decision = {
                'at': now.isoformat(timespec='seconds'), 'decision': 'SIGNAL_RECORDED',
                'signal_key': key, 'signal_date': candidate['signal_date'], 'symbol': symbol,
                'strategy_id': candidate['strategy_id'], 'quality_percentile': candidate['quality_percentile'],
                'current_priority_percentile': candidate['current_priority_percentile'],
                'challenger_priority': candidate['challenger_priority'],
                'passes_frozen_quality': candidate['passes_frozen_quality'],
            }
            if candidate['passes_frozen_quality']:
                pending = dict(candidate); pending['recorded_at'] = decision['at']; state['pending'].append(pending); decision['decision'] = 'PENDING_NEXT_OPEN'
            else:
                decision['decision'] = 'REJECT_FROZEN_QUALITY'
            state['decisions'].append(decision)

    state['seen_signal_keys'] = sorted(seen)[-10000:]
    state['last_candidates'] = sorted(latest, key=lambda x: (-x['challenger_priority'], x['symbol']))[:100]
    state['updated_at'] = now.isoformat(timespec='seconds')
    state['summary'] = _v3_summary(state, frames)
    state['comparison_baseline'] = COMPARISON_BASELINE
    state['risk_budget_pct'] = BASE_RISK_BUDGET_PCT
    state['meta']['last_market_state'] = market_state
    state['meta']['last_completed_signal_date'] = max((str(x.index[-1].date()) for x in frames.values() if x is not None and not x.empty), default=None)
    state['meta']['comparison_baseline'] = COMPARISON_BASELINE
    state['meta']['base_risk_budget_pct'] = BASE_RISK_BUDGET_PCT
    state['meta']['damped_risk_budget_pct'] = DAMPED_RISK_BUDGET_PCT
    state['meta']['correlation_threshold'] = CORR_THRESHOLD
    state['meta']['correlation_lookback_sessions'] = LOOKBACK_SESSIONS
    state['meta']['ab_only_changed_rule'] = 'correlation_conditioned_fresh_entry_risk_budget'
    state['meta']['hypothesis_freeze_date'] = HYPOTHESIS_FREEZE_DATE
    state['meta']['production_main_picker_mutated'] = False
    state['meta']['auto_retune'] = False
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
        print('frozen', d['challenger_id'], 'forward', d['forward_start_date'], 'corr', d['correlation_risk_damp'])
    else:
        s = run_forward()
        print(json.dumps({'summary': s.get('summary'), 'meta': s.get('meta')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
