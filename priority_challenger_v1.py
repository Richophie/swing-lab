from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import datetime, timezone
import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from backtest_engine import market_buy_fill, market_sell_fill
from config import BACKTEST_COMMISSION_PCT, BACKTEST_HALF_SPREAD_BPS, BACKTEST_SLIPPAGE_BPS, S_THRESHOLD
from market_data import indicators
from scanner import _extract_frame, _has_incomplete_daily_bar
from strategy_rules import canonical_signal_frame, ENTRY_GAP_ATR, ENTRY_GAP_PCT
from structural_stop_research import historical_features, plan_from_row, selection_pass
from strategy_selection_research import quality_score

ROOT = Path(__file__).parent
STATIC = ROOT / 'static'
POOL = STATIC / 'replay_backtest_pool_v2.json'
SCAN = STATIC / 'latest_scan.json'
CALIBRATION = STATIC / 'priority_challenger_v1_calibration.json'
STATE = STATIC / 'priority_challenger_v1_state.json'

CHALLENGER_ID = 'priority_challenger_v1'
FREEZE_DATE = '2026-08-13'
FORWARD_START_DATE = '2026-08-14'
FAMILY = ('confirmed_pullback', 'sma200_20_squeeze', 'donchian_55')
MAX_POSITIONS = 10
MIN_QUALITY_PERCENTILE = 0.50
CURRENT_WEIGHT = 0.50
QUALITY_WEIGHT = 0.50
STARTING_CASH_KRW = 3_000_000.0
RISK_BUDGET = 0.01
MAX_SHARE = 0.40

SMA_ID = 'sma200_20_squeeze'
DONCHIAN_ID = 'donchian_55'
CONFIRMED_ID = 'confirmed_pullback'
STRATEGY_NAMES = {
    CONFIRMED_ID: '확인형 눌림반등',
    SMA_ID: 'SMA200·20 스퀴즈',
    DONCHIAN_ID: 'Donchian 55일 돌파',
}


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def _num(value, default=0.0):
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def empirical_percentile(sorted_values: list[float], value: float) -> float:
    if not sorted_values:
        return 0.5
    x = float(value)
    lo = bisect_left(sorted_values, x)
    hi = bisect_right(sorted_values, x)
    return ((lo + hi) / 2.0) / len(sorted_values)


def current_priority(candidate: dict) -> float:
    rr = candidate.get('net_risk_reward')
    if rr is not None:
        return _num(rr)
    return _num(candidate.get('elite_score')) / 100.0


def freeze_calibration() -> dict:
    """Create the immutable forward calibration once; never overwrite it."""
    if CALIBRATION.exists():
        data = _load(CALIBRATION, {})
        if data.get('challenger_id') != CHALLENGER_ID or data.get('freeze_date') != FREEZE_DATE:
            raise RuntimeError('Existing challenger calibration does not match V1 freeze metadata')
        return data

    pool = _load(POOL, {})
    if not pool.get('ready') or int(pool.get('version') or 0) < 4:
        raise RuntimeError('Replay pool V4 is required before freezing challenger V1')

    refs = {sid: {'quality': [], 'current_priority': []} for sid in FAMILY}
    frozen_candidates = []
    for raw in pool.get('trades') or []:
        sid = raw.get('strategy_id')
        signal_date = str(raw.get('signal_date') or '')[:10]
        if sid not in refs or not signal_date or signal_date > FREEZE_DATE:
            continue
        candidate = dict(raw)
        q = float(quality_score(candidate))
        p = float(current_priority(candidate))
        refs[sid]['quality'].append(q)
        refs[sid]['current_priority'].append(p)
        frozen_candidates.append(candidate)

    for sid, values in refs.items():
        values['quality'] = sorted(round(float(x), 6) for x in values['quality'])
        values['current_priority'] = sorted(round(float(x), 6) for x in values['current_priority'])
        if not values['quality']:
            raise RuntimeError(f'No frozen calibration candidates for {sid}')

    frozen_symbols = sorted(set(pool.get('eligible_symbols') or []))
    if not frozen_symbols:
        frozen_symbols = sorted({str(x.get('symbol') or '') for x in pool.get('trades') or [] if x.get('symbol')})
    payload = {
        'version': 1,
        'challenger_id': CHALLENGER_ID,
        'status': 'FROZEN_FORWARD_ONLY',
        'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'freeze_date': FREEZE_DATE,
        'forward_start_date': FORWARD_START_DATE,
        'source_pool_generated_at': pool.get('generated_at'),
        'source_pool_version': pool.get('version'),
        'family': list(FAMILY),
        'frozen_symbols': frozen_symbols,
        'max_positions': MAX_POSITIONS,
        'quality_filter': {'mode': 'within_strategy_percentile', 'min_percentile': MIN_QUALITY_PERCENTILE},
        'priority': {
            'formula': '0.50 * TRAIN-frozen within-strategy current-priority percentile + 0.50 * TRAIN-frozen within-strategy signal-quality percentile',
            'current_weight': CURRENT_WEIGHT,
            'quality_weight': QUALITY_WEIGHT,
        },
        'reference': refs,
        'reference_counts': {sid: len(refs[sid]['quality']) for sid in FAMILY},
        'mutable': False,
        'notes': [
            '2026-08-13까지 이미 본 모든 과거 데이터는 development data로 취급합니다.',
            '이 파일이 생성된 뒤 reference 분포, 50:50 가중치, 상위 50% 엄선, 최대 10개, 자연청산을 forward 기간 중 자동 재튜닝하지 않습니다.',
            '현재 종목 universe 기반 과거풀의 survivorship bias는 calibration에 남아 있습니다. Forward 관찰은 이 날짜 이후 실제 신호만 누적합니다.',
            'RESEARCH ONLY. production 추천과 주문 규칙을 변경하지 않습니다.',
        ],
    }
    CALIBRATION.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


def _quality_and_priority(candidate: dict, calibration: dict) -> dict:
    sid = candidate['strategy_id']
    ref = (calibration.get('reference') or {}).get(sid) or {}
    q = float(quality_score(candidate))
    p = float(current_priority(candidate))
    qp = empirical_percentile(ref.get('quality') or [], q)
    pp = empirical_percentile(ref.get('current_priority') or [], p)
    return {
        'quality_score': round(q, 6),
        'quality_percentile': round(qp, 6),
        'current_priority': round(p, 6),
        'current_priority_percentile': round(pp, 6),
        'challenger_priority': round(CURRENT_WEIGHT * pp + QUALITY_WEIGHT * qp, 6),
    }


def _market_state(scan: dict) -> str:
    return str((scan.get('market') or {}).get('state') or '중립')


def _confirmed_candidate(d: pd.DataFrame, market_state: str) -> dict | None:
    if len(d) < 205:
        return None
    state = pd.Series(market_state, index=d.index, dtype='object')
    frame = canonical_signal_frame(d, state)
    features = historical_features(d, state, frame)
    i = len(d) - 1
    if not bool(frame[CONFIRMED_ID].iloc[i]):
        return None
    score = float(features['scores'][CONFIRMED_ID].iloc[i])
    if score < S_THRESHOLD:
        return None
    plan = plan_from_row(frame.iloc[i], CONFIRMED_ID, 'force_1_50')
    flow_row = features['flows'].iloc[i]
    flow = {k: (None if pd.isna(v) else float(v)) for k, v in flow_row.items()}
    selected = selection_pass(
        score, flow, plan, market_state, bool(features['overlay'].iloc[i]),
        float(frame['close'].iloc[i]), CONFIRMED_ID,
    )
    if not selected.get('pass'):
        return None
    return {
        'strategy_id': CONFIRMED_ID,
        'strategy_name': STRATEGY_NAMES[CONFIRMED_ID],
        'signal_date': d.index[i].strftime('%Y-%m-%d'),
        'signal_close': round(float(frame['close'].iloc[i]), 6),
        'buy_low': round(float(plan['buy_low']), 6),
        'buy_high': round(float(plan['buy_high']), 6),
        'atr': round(float(plan['atr']), 6),
        'stop': round(float(plan['stop']), 6),
        'target': round(float(plan['target']), 6),
        'max_hold': int(plan['days'][1]),
        'exit_mode': 'price_plan',
        'elite_score': round(float(selected['elite_score']), 6),
        'net_risk_reward': round(float(selected['net_rr']), 6),
        'market_state': market_state,
        'quality_features': {},
    }


def _sma_candidate(d: pd.DataFrame) -> dict | None:
    if len(d) < 205:
        return None
    ind = indicators(d)
    c = d['Close'].astype(float); o = d['Open'].astype(float); l = d['Low'].astype(float); v = d['Volume'].astype(float)
    s20 = ind['sma20'].astype(float); s200 = ind['sma200'].astype(float); atr = ind['atr14'].astype(float)
    vol20 = v.rolling(20).mean().replace(0, np.nan)
    spread = (s20 / s200 - 1).abs(); side = np.sign(s20 - s200)
    crosses = side.ne(side.shift(1)).rolling(30, min_periods=10).sum()
    ma_top = pd.concat([s20, s200], axis=1).max(axis=1)
    vol_ratio = v / vol20
    i = len(d) - 1
    signal = bool(
        c.iloc[i] > s200.iloc[i]
        and s200.iloc[i] > s200.iloc[i-20]
        and spread.iloc[i] <= .035
        and crosses.iloc[i] <= 2
        and c.iloc[i] > o.iloc[i]
        and (c.iloc[i] - o.iloc[i]) >= atr.iloc[i] * .70
        and l.iloc[i] > ma_top.iloc[i]
        and c.iloc[i-1] <= max(s20.iloc[i-1], s200.iloc[i-1]) * 1.015
        and vol_ratio.iloc[i] >= .75
    )
    if not signal:
        return None
    a = float(atr.iloc[i]); close = float(c.iloc[i]); ma20 = float(s20.iloc[i]); ma200 = float(s200.iloc[i])
    if not math.isfinite(a) or a <= 0:
        return None
    body_atr = max(0.0, (float(c.iloc[i]) - float(o.iloc[i])) / a)
    q = {
        'body_atr': body_atr,
        'ma_spread_pct': float(spread.iloc[i]),
        'crosses_30': float(crosses.iloc[i]),
        'volume_ratio': float(vol_ratio.iloc[i]),
        'ma_clearance_atr': float((l.iloc[i] - ma_top.iloc[i]) / a),
        'sma200_slope_20d_pct': float(s200.iloc[i] / s200.iloc[i-20] - 1.0),
        'atr_pct': a / close,
    }
    return {
        'strategy_id': SMA_ID,
        'strategy_name': STRATEGY_NAMES[SMA_ID],
        'signal_date': d.index[i].strftime('%Y-%m-%d'),
        'signal_close': round(close, 6),
        'buy_low': round(close - .18 * a, 6),
        'buy_high': round(close + .18 * a, 6),
        'atr': round(a, 6),
        'stop': round(min(ma20, ma200) - .15 * a, 6),
        'target': None,
        'max_hold': 20,
        'exit_mode': 'sma20_close',
        'elite_score': round(min(95.0, 72.0 + body_atr * 8.0 + max(0.0, .035-float(spread.iloc[i])) * 200), 6),
        'net_risk_reward': round(1.0 + min(1.0, body_atr / 2.0), 6),
        'market_state': 'strategy_only',
        'quality_features': q,
    }


def _donchian_candidate(d: pd.DataFrame) -> dict | None:
    if len(d) < 205:
        return None
    ind = indicators(d)
    c=d['Close'].astype(float); o=d['Open'].astype(float); h=d['High'].astype(float); l=d['Low'].astype(float); v=d['Volume'].astype(float)
    atr=ind['atr14'].astype(float); s200=ind['sma200'].astype(float)
    hh55=h.rolling(55).max().shift(1); vol20=v.rolling(20).mean().shift(1).replace(0,np.nan)
    vol_ratio=v/vol20; rng=(h-l).replace(0,np.nan); body=c-o; close_pos=(c-l)/rng
    i=len(d)-1
    if not bool(c.iloc[i] > s200.iloc[i] and s200.iloc[i] > s200.iloc[i-20] and c.iloc[i] > hh55.iloc[i]):
        return None
    a=float(atr.iloc[i]); close=float(c.iloc[i]); level=float(hh55.iloc[i])
    if not math.isfinite(a) or a <= 0 or not math.isfinite(level):
        return None
    q={
        'breakout_atr': (close-level)/a,
        'volume_ratio': float(vol_ratio.iloc[i]) if pd.notna(vol_ratio.iloc[i]) else 0.0,
        'close_position': float(close_pos.iloc[i]) if pd.notna(close_pos.iloc[i]) else 0.0,
        'body_atr': float(body.iloc[i]/a),
        'sma200_slope_20d_pct': float(s200.iloc[i]/s200.iloc[i-20]-1.0),
        'distance_sma200_pct': float(close/s200.iloc[i]-1.0),
        'atr_pct': a/close,
    }
    return {
        'strategy_id': DONCHIAN_ID,
        'strategy_name': STRATEGY_NAMES[DONCHIAN_ID],
        'signal_date': d.index[i].strftime('%Y-%m-%d'),
        'signal_close': round(close, 6),
        'buy_low': round(close - .18*a, 6),
        'buy_high': round(close + .18*a, 6),
        'atr': round(a, 6),
        'stop': round(close - 2.0*a, 6),
        'target': None,
        'max_hold': 40,
        'exit_mode': 'donchian20_close',
        'elite_score': 78.0,
        'net_risk_reward': 2.0,
        'market_state': 'strategy_only',
        'quality_features': q,
    }


def candidates_for_symbol(symbol: str, completed: pd.DataFrame, market_state: str, calibration: dict) -> list[dict]:
    rows = []
    for builder in (
        lambda: _confirmed_candidate(completed, market_state),
        lambda: _sma_candidate(completed),
        lambda: _donchian_candidate(completed),
    ):
        try:
            candidate = builder()
        except Exception:
            candidate = None
        if not candidate:
            continue
        candidate['symbol'] = symbol
        candidate.update(_quality_and_priority(candidate, calibration))
        candidate['passes_frozen_quality'] = candidate['quality_percentile'] >= MIN_QUALITY_PERCENTILE
        rows.append(candidate)
    return rows


def _default_state(calibration: dict) -> dict:
    return {
        'version': 1,
        'challenger_id': CHALLENGER_ID,
        'status': 'FORWARD_SHADOW',
        'freeze_date': FREEZE_DATE,
        'forward_start_date': FORWARD_START_DATE,
        'live_trading_enabled': False,
        'production_mutation_enabled': False,
        'starting_cash_krw': STARTING_CASH_KRW,
        'cash_krw': STARTING_CASH_KRW,
        'pending': [],
        'positions': [],
        'closed': [],
        'decisions': [],
        'seen_signal_keys': [],
        'last_candidates': [],
        'errors': [],
        'meta': {
            'family': list(FAMILY),
            'max_positions': MAX_POSITIONS,
            'quality_min_percentile': MIN_QUALITY_PERCENTILE,
            'priority_formula': calibration.get('priority'),
            'calibration_created_at': calibration.get('created_at'),
            'human_intervention': False,
            'auto_retune': False,
        },
    }


def _commission() -> float:
    return BACKTEST_COMMISSION_PCT / 100.0


def _friction() -> float:
    return (BACKTEST_SLIPPAGE_BPS + BACKTEST_HALF_SPREAD_BPS) / 10000.0


def _position_mark_factor(position: dict, raw_close: float) -> float:
    entry = _num(position.get('entry_fill_usd'))
    if entry <= 0 or raw_close <= 0:
        return 1.0
    paid = entry * (1.0 + _commission())
    exit_fill = market_sell_fill(raw_close, BACKTEST_SLIPPAGE_BPS, BACKTEST_HALF_SPREAD_BPS)
    received = exit_fill * (1.0 - _commission())
    return max(0.0, received / paid)


def _equity(state: dict, frames: dict[str, pd.DataFrame]) -> float:
    total = _num(state.get('cash_krw'))
    for position in state.get('positions') or []:
        frame = frames.get(position.get('symbol'))
        close = _num(frame['Close'].iloc[-1]) if frame is not None and not frame.empty else _num(position.get('last_close_usd'), _num(position.get('entry_fill_usd')))
        total += _num(position.get('notional_krw')) * _position_mark_factor(position, close)
    return total


def _close_position(state: dict, position: dict, *, date: str, raw_exit: float, reason: str) -> None:
    exit_fill = market_sell_fill(raw_exit, BACKTEST_SLIPPAGE_BPS, BACKTEST_HALF_SPREAD_BPS)
    paid = _num(position.get('entry_fill_usd')) * (1.0 + _commission())
    received = exit_fill * (1.0 - _commission())
    factor = received / paid if paid > 0 else 0.0
    proceeds = _num(position.get('notional_krw')) * factor
    pnl = proceeds - _num(position.get('notional_krw'))
    state['cash_krw'] = round(_num(state.get('cash_krw')) + proceeds, 2)
    closed = dict(position)
    closed.update({
        'status': 'CLOSED', 'exit_date': date, 'exit_fill_usd': round(exit_fill, 6),
        'exit_reason': reason, 'pnl_krw': round(pnl, 2),
        'return_pct': round((factor - 1.0) * 100.0, 4),
        'closed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    })
    state['closed'].append(closed)
    state['positions'] = [x for x in state['positions'] if x.get('id') != position.get('id')]
    state['decisions'].append({'at': closed['closed_at'], 'decision': 'EXIT', 'symbol': position.get('symbol'), 'strategy_id': position.get('strategy_id'), 'date': date, 'reason': reason, 'pnl_krw': closed['pnl_krw']})


def _process_position(state: dict, position: dict, frame: pd.DataFrame, now_utc: datetime) -> None:
    if frame is None or frame.empty:
        return
    entry_date = str(position.get('entry_date') or '')[:10]
    last_close_processed = str(position.get('last_close_processed') or '')[:10]
    sma20 = frame['Close'].astype(float).rolling(20).mean()
    dc20 = frame['Low'].astype(float).rolling(20).min().shift(1)
    last_incomplete = _has_incomplete_daily_bar(frame, now_utc)
    last_day = frame.index[-1].strftime('%Y-%m-%d')

    for idx, bar in frame.iterrows():
        day = idx.strftime('%Y-%m-%d')
        if day < entry_date:
            continue
        if position not in state.get('positions', []):
            break
        o,h,l,c = map(float, (bar['Open'],bar['High'],bar['Low'],bar['Close']))
        sid = position['strategy_id']; stop = _num(position.get('stop')); target = position.get('target')
        hard_stop = sid != SMA_ID and stop > 0
        if hard_stop and o <= stop:
            _close_position(state, position, date=day, raw_exit=o, reason='손절 · 갭')
            break
        if hard_stop and l <= stop:
            _close_position(state, position, date=day, raw_exit=stop, reason='손절')
            break
        if target is not None and _num(target) > 0:
            t = _num(target)
            if o >= t or h >= t:
                # Replay execute_candidate applies the same sell-side friction to
                # a target trigger before commission. Forward must use that exact
                # accounting too; the target trigger itself remains unchanged.
                _close_position(state, position, date=day, raw_exit=t, reason='목표가')
                break

        completed = not (day == last_day and last_incomplete)
        position['last_close_usd'] = round(c, 6)
        if not completed or day <= last_close_processed:
            continue
        position['held_bars'] = int(position.get('held_bars') or 0) + 1
        position['last_close_processed'] = day
        if sid == SMA_ID:
            s20 = _num(sma20.loc[idx], float('nan'))
            if math.isfinite(s20) and c < s20:
                _close_position(state, position, date=day, raw_exit=c, reason='20일선 종가 이탈'); break
        elif sid == DONCHIAN_ID:
            low20 = _num(dc20.loc[idx], float('nan'))
            if math.isfinite(low20) and c < low20:
                _close_position(state, position, date=day, raw_exit=c, reason='Donchian 20일 하단 이탈'); break
        if int(position.get('held_bars') or 0) >= int(position.get('max_hold') or 1):
            _close_position(state, position, date=day, raw_exit=c, reason='최대보유 종료'); break


def _first_bar_after(frame: pd.DataFrame, signal_date: str):
    for idx, bar in frame.iterrows():
        if idx.strftime('%Y-%m-%d') > signal_date:
            return idx, bar
    return None, None


def _fill_pending(state: dict, frames: dict[str, pd.DataFrame]) -> None:
    attempts = []
    for pending in list(state.get('pending') or []):
        frame = frames.get(pending.get('symbol'))
        if frame is None or frame.empty:
            continue
        idx, bar = _first_bar_after(frame, str(pending.get('signal_date'))[:10])
        if idx is None:
            continue
        attempts.append((idx.strftime('%Y-%m-%d'), -_num(pending.get('challenger_priority')), str(pending.get('symbol')), pending, bar))

    for entry_date, _, _, pending, bar in sorted(attempts, key=lambda x: (x[0], x[1], x[2])):
        if pending not in state.get('pending', []):
            continue
        symbol = pending['symbol']; sid = pending['strategy_id']
        key = pending['signal_key']; raw_open = float(bar['Open'])
        decision = {'at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'signal_key':key,'symbol':symbol,'strategy_id':sid,'signal_date':pending['signal_date'],'entry_date':entry_date,'priority':pending['challenger_priority']}
        if any(p.get('symbol') == symbol for p in state.get('positions') or []):
            decision.update({'decision':'REJECT_DUPLICATE'});state['decisions'].append(decision);state['pending'].remove(pending);continue
        if len(state.get('positions') or []) >= MAX_POSITIONS:
            decision.update({'decision':'REJECT_MAX_POSITIONS'});state['decisions'].append(decision);state['pending'].remove(pending);continue
        gap=max(ENTRY_GAP_ATR*_num(pending['atr']),ENTRY_GAP_PCT*_num(pending['signal_close']))
        if raw_open < _num(pending['buy_low'])-gap or raw_open > _num(pending['buy_high'])+gap:
            decision.update({'decision':'REJECT_GAP','raw_open_usd':round(raw_open,6)});state['decisions'].append(decision);state['pending'].remove(pending);continue
        entry=market_buy_fill(raw_open,BACKTEST_SLIPPAGE_BPS,BACKTEST_HALF_SPREAD_BPS)
        stop=_num(pending['stop']);target=pending.get('target')
        if entry <= stop or (target is not None and _num(target)>0 and entry >= _num(target)):
            decision.update({'decision':'REJECT_INVALID_FILL','entry_fill_usd':round(entry,6)});state['decisions'].append(decision);state['pending'].remove(pending);continue
        frame_map=frames
        equity=_equity(state,frame_map)
        risk_fraction=max(.001,(entry-stop)/entry)
        desired=min(_num(state.get('cash_krw')),equity*RISK_BUDGET/risk_fraction,equity*MAX_SHARE)
        if desired < 1:
            decision.update({'decision':'REJECT_CASH','desired_krw':round(desired,2)});state['decisions'].append(decision);state['pending'].remove(pending);continue
        position=dict(pending)
        position.update({'id':key,'status':'OPEN','entry_date':entry_date,'raw_entry_open_usd':round(raw_open,6),'entry_fill_usd':round(entry,6),'notional_krw':round(desired,2),'risk_fraction':round(risk_fraction,6),'held_bars':0,'last_close_processed':'','opened_at':decision['at']})
        state['cash_krw']=round(_num(state.get('cash_krw'))-desired,2)
        state['positions'].append(position);state['pending'].remove(pending)
        decision.update({'decision':'FILLED','entry_fill_usd':round(entry,6),'notional_krw':round(desired,2),'cash_after_krw':state['cash_krw']});state['decisions'].append(decision)


def _summary(state: dict, frames: dict[str, pd.DataFrame]) -> dict:
    equity=_equity(state,frames);start=_num(state.get('starting_cash_krw'),STARTING_CASH_KRW)
    realized=sum(_num(x.get('pnl_krw')) for x in state.get('closed') or [])
    unrealized=equity-_num(state.get('cash_krw'))-sum(_num(x.get('notional_krw')) for x in state.get('positions') or [])
    closed=state.get('closed') or []
    wins=sum(1 for x in closed if _num(x.get('pnl_krw'))>0)
    counts={k:sum(1 for x in state.get('decisions') or [] if x.get('decision')==k) for k in ('FILLED','REJECT_GAP','REJECT_CASH','REJECT_MAX_POSITIONS','REJECT_DUPLICATE')}
    return {
        'cash_krw':round(_num(state.get('cash_krw')),2),'equity_krw':round(equity,2),
        'return_pct':round((equity/start-1)*100,3) if start>0 else 0.0,
        'realized_pnl_krw':round(realized,2),'unrealized_pnl_krw':round(unrealized,2),
        'pending':len(state.get('pending') or []),'open_positions':len(state.get('positions') or []),'closed_trades':len(closed),
        'win_rate_pct':round(wins/len(closed)*100,1) if closed else None,
        'max_positions':MAX_POSITIONS,'decision_counts':counts,
    }


def _download_frames(symbols: list[str]) -> tuple[dict[str,pd.DataFrame], list[dict]]:
    frames={};errors=[]
    if not symbols:return frames,errors
    try:
        bulk=yf.download(' '.join(symbols),period='14mo',interval='1d',auto_adjust=False,group_by='ticker',threads=True,progress=False,timeout=30)
    except Exception as exc:
        return {},[{'scope':'bulk','error':str(exc)}]
    for symbol in symbols:
        try:
            d=_extract_frame(bulk,symbol,len(symbols))
            if d is None or len(d)<205:raise ValueError(f'daily rows {0 if d is None else len(d)} < 205')
            frames[symbol]=d
        except Exception as exc:errors.append({'symbol':symbol,'error':str(exc)})
    return frames,errors


def run_forward(now_utc: datetime | None=None) -> dict:
    calibration=freeze_calibration();scan=_load(SCAN,{})
    state=_load(STATE,{})
    if not state:state=_default_state(calibration)
    if state.get('challenger_id')!=CHALLENGER_ID or state.get('freeze_date')!=FREEZE_DATE:
        raise RuntimeError('Refusing to mutate a state created by another challenger version')
    now=now_utc or datetime.now(timezone.utc)
    symbols=list(calibration.get('frozen_symbols') or [])
    frames,errors=_download_frames(symbols);state['errors']=errors[-100:]

    # Entry attempts are made from signals frozen on a prior completed session.
    _fill_pending(state,frames)

    # Existing/just-filled positions are marked and can hit hard stops/targets intraday.
    for position in list(state.get('positions') or []):
        frame=frames.get(position.get('symbol'))
        if frame is not None:_process_position(state,position,frame,now)

    market_state=_market_state(scan);seen=set(state.get('seen_signal_keys') or [])
    latest=[]
    for symbol,frame in frames.items():
        completed=frame.iloc[:-1].copy() if _has_incomplete_daily_bar(frame,now) else frame.copy()
        if completed.empty:continue
        signal_day=completed.index[-1].strftime('%Y-%m-%d')
        if signal_day < FORWARD_START_DATE:continue
        for candidate in candidates_for_symbol(symbol,completed,market_state,calibration):
            key=f"{candidate['signal_date']}|{symbol}|{candidate['strategy_id']}"
            candidate['signal_key']=key;latest.append(candidate)
            if key in seen:continue
            seen.add(key)
            decision={'at':now.isoformat(timespec='seconds'),'decision':'SIGNAL_RECORDED','signal_key':key,'signal_date':candidate['signal_date'],'symbol':symbol,'strategy_id':candidate['strategy_id'],'quality_percentile':candidate['quality_percentile'],'current_priority_percentile':candidate['current_priority_percentile'],'challenger_priority':candidate['challenger_priority'],'passes_frozen_quality':candidate['passes_frozen_quality']}
            if candidate['passes_frozen_quality']:
                pending=dict(candidate);pending['recorded_at']=decision['at'];state['pending'].append(pending);decision['decision']='PENDING_NEXT_OPEN'
            else:
                decision['decision']='REJECT_FROZEN_QUALITY'
            state['decisions'].append(decision)

    state['seen_signal_keys']=sorted(seen)[-10000:]
    state['last_candidates']=sorted(latest,key=lambda x:(-x['challenger_priority'],x['symbol']))[:100]
    state['updated_at']=now.isoformat(timespec='seconds')
    state['summary']=_summary(state,frames)
    state['meta']['last_market_state']=market_state
    state['meta']['last_completed_signal_date']=max((str(x.index[-1].date()) for x in frames.values() if x is not None and not x.empty),default=None)
    if len(state['decisions'])>5000:state['decisions']=state['decisions'][-5000:]
    if len(state['closed'])>2000:state['closed']=state['closed'][-2000:]
    STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    return state


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',nargs='?',default='run',choices=('freeze','run','all'));args=parser.parse_args()
    if args.action in {'freeze','all'}:
        c=freeze_calibration();print('frozen',c['challenger_id'],c['freeze_date'],c['reference_counts'],len(c['frozen_symbols']))
    if args.action in {'run','all'}:
        s=run_forward();print(json.dumps({'summary':s.get('summary'),'meta':s.get('meta')},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
