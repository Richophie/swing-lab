from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path

from backtest_engine import exit_fill_for_bar, market_buy_fill, market_sell_fill
from baseline_rules import (
    BASELINE_VERSION,
    FULL_FORWARD_REVIEW_TRADES,
    MIN_FORWARD_REVIEW_TRADES,
    baseline_snapshot,
)
from config import APP_VERSION, CORE_VERSION, PUBLIC_STRATEGIES
from intraday_execution import bars_for_date, first_buy_touch, first_exit_touch, fresh_intraday_history
from market_data import fresh_price_history
from paper_broker import PaperBrokerStore, _cancel_order, _close_order, _event, snapshot, submit_order
from paper_broker_service import current_fx_rate
from paper_plan import execution_plan_with_atr
from risk_observability import snapshot_event_risk

ROOT = Path(__file__).parent
STATIC = ROOT / 'static'
HISTORY_FILE = STATIC / 'trade_history.json'
SCAN_FILE = STATIC / 'latest_scan.json'
STATE_FILE_A = STATIC / 'shadow_portfolio.json'
STATE_FILE_B = STATIC / 'shadow_portfolio_touch.json'
STATE_FILE = STATE_FILE_A  # backward-compatible alias
LAB_START_DATE = '2026-08-13'
LAB_VERSION = 2
TRACK_A = 'A_NEXT_OPEN'
TRACK_B = 'B_BUY_TOUCH'
TRACKS = {
    TRACK_A: {
        'label': 'A · 다음 시가형',
        'entry_mode': 'NEXT_OPEN_GAP_GUARD',
        'state_file': STATE_FILE_A,
    },
    TRACK_B: {
        'label': 'B · BUY 터치형',
        'entry_mode': 'NEXT_SESSION_BUY_TOUCH',
        'state_file': STATE_FILE_B,
    },
}


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def _number(value, default=0.0):
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _scan_plan_index(scan: dict) -> dict[str, dict]:
    out = {}
    for row in scan.get('results') or []:
        symbol = str(row.get('symbol') or '').upper().strip()
        plans = row.get('strategy_trade_plans') or {}
        for sid, plan in plans.items():
            if symbol and sid in PUBLIC_STRATEGIES and isinstance(plan, dict):
                out[f'{symbol}|{sid}'] = plan
    return out


def _plan_from_item(item: dict, current_plan: dict | None = None) -> dict:
    frozen = {
        'entry_low': item.get('entry_low'),
        'entry_high': item.get('entry_high'),
        'target': item.get('target'),
        'stop': item.get('stop'),
        'atr': item.get('atr'),
        'stop_atr_multiple': item.get('stop_atr_multiple'),
    }
    recovered = execution_plan_with_atr(frozen)
    if not recovered.get('atr') and current_plan:
        current = execution_plan_with_atr(current_plan)
        recovered['atr'] = current.get('atr')
        recovered['atr_source'] = current.get('atr_source') or ('current_scan' if current.get('atr') else None)
    atr = _number(recovered.get('atr'), 0.0)
    if atr <= 0:
        raise ValueError('공식 추천 ATR 실행값을 복원할 수 없어 canonical gap guard를 계산할 수 없습니다')
    return {
        'entry_low': item.get('entry_low'),
        'entry_high': item.get('entry_high'),
        'target': item.get('target'),
        'stop': item.get('stop'),
        'atr': atr,
        'atr_source': recovered.get('atr_source') or 'stored',
        'days_min': item.get('target_days_low'),
        'days_max': item.get('target_days_high'),
        'target_days': {
            'days_low': item.get('target_days_low'),
            'days_high': item.get('target_days_high'),
        },
    }


def _signal_key(item: dict) -> str:
    day = str(item.get('market_date') or item.get('date') or '')[:10]
    symbol = str(item.get('symbol') or '').upper().strip()
    strategy = str(item.get('strategy_id') or '').strip()
    return f'{day}|{symbol}|{strategy}'


def _eligible_items(history: dict) -> list[dict]:
    rows = []
    for day in history.get('days') or []:
        for item in day.get('items') or []:
            market_date = str(item.get('market_date') or day.get('date') or '')[:10]
            if not market_date or market_date < LAB_START_DATE:
                continue
            if item.get('strategy_id') not in PUBLIC_STRATEGIES:
                continue
            if bool(item.get('experimental')):
                continue
            if item.get('performance_bucket') not in {None, 'official_public'}:
                continue
            if not item.get('entry_low') or not item.get('entry_high') or not item.get('target') or not item.get('stop'):
                continue
            row = dict(item)
            row['market_date'] = market_date
            rows.append(row)
    rows.sort(
        key=lambda x: (
            x.get('market_date') or '',
            -_number(x.get('risk_reward'), 0.0),
            -_number(x.get('score'), 0.0),
            str(x.get('symbol') or ''),
        )
    )
    return rows


def _ensure_meta(state: dict, track_id: str) -> None:
    track = TRACKS[track_id]
    state['live_trading_enabled'] = False
    state.setdefault('shadow_decisions', [])
    state.setdefault('lab_meta', {})
    state['lab_meta'].update(
        {
            'version': LAB_VERSION,
            'lab_start_date': LAB_START_DATE,
            'mode': 'AUTO_CONFIRMED_CLOSE_AB',
            'track_id': track_id,
            'track_label': track['label'],
            'entry_mode': track['entry_mode'],
            'allocator': 'risk_reward_priority',
            'human_intervention': False,
            'live_trading_enabled': False,
            'baseline_version': BASELINE_VERSION,
            'baseline': baseline_snapshot(),
        }
    )


def _seen_keys(state: dict) -> set[str]:
    out = set()
    for order in state.get('orders') or []:
        if order.get('shadow_signal_key'):
            out.add(str(order['shadow_signal_key']))
    for row in state.get('shadow_decisions') or []:
        if row.get('signal_key'):
            out.add(str(row['signal_key']))
    return out


def _market_state_for_item(item: dict, live_scan: dict | None) -> str:
    if item.get('market_state'):
        return str(item['market_state'])
    scan = live_scan or {}
    scan_day = str(scan.get('market_date') or scan.get('scanned_at') or '')[:10]
    if scan_day == str(item.get('market_date') or '')[:10]:
        return str((scan.get('market') or {}).get('state') or 'UNTRACKED')
    return 'UNTRACKED'


def ingest_confirmed_signals(
    state: dict,
    history: dict,
    *,
    fx_rate: float,
    live_scan: dict | None = None,
    track_id: str = TRACK_A,
) -> dict:
    _ensure_meta(state, track_id)
    seen = _seen_keys(state)
    scan_plans = _scan_plan_index(live_scan or {})
    submitted = 0
    skipped = 0

    for item in _eligible_items(history):
        key = _signal_key(item)
        if key in seen:
            continue
        decision = {
            'signal_key': key,
            'market_date': item.get('market_date'),
            'symbol': item.get('symbol'),
            'strategy_id': item.get('strategy_id'),
            'strategy_name': item.get('strategy_name'),
            'score': item.get('score'),
            'risk_reward': item.get('risk_reward'),
            'baseline_version': BASELINE_VERSION,
            'track_id': track_id,
            'at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        }
        try:
            symbol = str(item.get('symbol') or '').upper().strip()
            sid = str(item.get('strategy_id') or '')
            plan = _plan_from_item(item, scan_plans.get(f'{symbol}|{sid}'))
            order = submit_order(
                state,
                symbol=symbol,
                strategy_id=sid,
                strategy_name=item.get('strategy_name') or sid,
                plan=plan,
                fx_rate=float(fx_rate),
                submitted_market_date=item.get('market_date'),
                signal_date=item.get('market_date'),
            )
            order.update(
                {
                    'order_origin': 'AUTO_CONFIRMED_CLOSE',
                    'signal_origin': 'official_close_confirmed',
                    'shadow_signal_key': key,
                    'track_id': track_id,
                    'entry_mode': TRACKS[track_id]['entry_mode'],
                    'baseline_version': BASELINE_VERSION,
                    'app_version_at_signal': item.get('app_version') or APP_VERSION,
                    'core_version_at_signal': item.get('core_version') or CORE_VERSION,
                    'market_state': _market_state_for_item(item, live_scan),
                    'official_score': item.get('score'),
                    'raw_strategy_score': item.get('raw_strategy_score'),
                    'official_risk_reward': item.get('risk_reward'),
                    'official_selection_reason': item.get('selection_reason'),
                    'event_risk_snapshot': snapshot_event_risk(item.get('event_risk_snapshot') or item.get('event_risk')),
                    'atr_source': plan.get('atr_source') or 'stored',
                    'risk_observability_only': True,
                }
            )
            if track_id == TRACK_B:
                for event in reversed(state.get('events', [])):
                    if event.get('order_id') == order.get('id') and event.get('event') == 'SUBMITTED':
                        event['detail'] = f"다음 거래일 BUY 구간 터치 대기 · {order['qty']}주 · BUY {order['buy_low']:.2f}~{order['buy_high']:.2f}"
                        break
            decision.update(
                {
                    'decision': 'SUBMITTED',
                    'order_id': order.get('id'),
                    'atr': order.get('atr'),
                    'atr_source': order.get('atr_source'),
                    'gap_guard': order.get('gap_guard'),
                }
            )
            submitted += 1
        except Exception as exc:
            decision.update({'decision': 'SKIPPED', 'reason': str(exc)})
            skipped += 1
        state['shadow_decisions'].append(decision)
        seen.add(key)

    if len(state['shadow_decisions']) > 2000:
        state['shadow_decisions'] = state['shadow_decisions'][-2000:]
    return {'submitted': submitted, 'skipped': skipped}


def _fill_order(state: dict, order: dict, *, date: str, raw_entry: float, fx: float, entry_time: str | None, quality: str) -> bool:
    fill = market_buy_fill(raw_entry, float(order['slippage_bps']), float(order['half_spread_bps']))
    if not float(order['stop']) < fill < float(order['target']):
        _cancel_order(state, order, date, '체결비용 반영 후 STOP < 체결가 < TARGET 구조가 깨짐')
        return False
    commission = max(0.0, float(order['commission_pct_per_side'])) / 100.0
    per_share_cost = fill * fx * (1.0 + commission)
    affordable = math.floor(float(state.get('cash_krw') or 0.0) / per_share_cost)
    actual_risk_per_share = max((fill - float(order['stop'])) * fx, 0.0)
    by_risk = math.floor(float(order.get('risk_budget_krw') or 0.0) / actual_risk_per_share) if actual_risk_per_share > 0 else 0
    qty = min(int(order.get('qty') or 0), int(affordable), int(by_risk or 0))
    if qty < 1:
        _cancel_order(state, order, date, '실제 가상 체결시점 현금/리스크 한도에서 1주도 체결 불가')
        return False
    order['qty'] = qty
    gross = fill * qty * fx
    entry_commission = gross * commission
    entry_cost = gross + entry_commission
    state['cash_krw'] = round(float(state.get('cash_krw') or 0.0) - entry_cost, 2)
    order.update(
        {
            'status': 'FILLED',
            'entry_date': date,
            'entry_fill_usd': round(fill, 6),
            'entry_raw_open_usd': round(raw_entry, 6),
            'entry_timestamp': entry_time,
            'entry_resolution_quality': quality,
            'entry_commission_krw': round(entry_commission, 2),
            'entry_cost_krw': round(entry_cost, 2),
            'fx_at_entry': round(fx, 4),
            'reserved_cash_krw': 0.0,
            'held_bars': 0,
            'last_fx': round(fx, 4),
            'last_processed_date': date,
            'filled_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        }
    )
    _event(state, order, 'FILLED', f"{qty}주 · ${fill:.4f} · {entry_cost:,.0f}원 · {quality}")
    return True


def _exit_order_from_bar(
    state: dict,
    order: dict,
    *,
    date: str,
    o: float,
    h: float,
    l: float,
    fx: float,
    minute_bars=None,
    after_timestamp: str | None = None,
) -> bool:
    target, stop = float(order['target']), float(order['stop'])
    hit_target = o >= target or h >= target
    hit_stop = o <= stop or l <= stop
    if not (hit_target or hit_stop):
        return False

    resolution = None
    if minute_bars is not None and not minute_bars.empty:
        resolution = first_exit_touch(minute_bars, target=target, stop=stop, after_timestamp=after_timestamp)
    if resolution:
        quality = resolution['quality']
        order['exit_resolution_quality'] = quality
        order['exit_timestamp'] = resolution['timestamp']
        if resolution['side'] == 'TARGET':
            fill = target
        else:
            fill = market_sell_fill(
                float(resolution['raw_price']),
                float(order['slippage_bps']),
                float(order['half_spread_bps']),
            )
        _close_order(
            state,
            order,
            date=date,
            exit_fill_usd=fill,
            reason=resolution['reason'],
            fx_rate=fx,
            raw_trigger_usd=float(resolution['raw_price']),
        )
        return True

    outcome = exit_fill_for_bar(
        o, h, l, target, stop,
        float(order['slippage_bps']),
        float(order['half_spread_bps']),
    )
    if outcome is None:
        return False
    fill, reason, raw_trigger = outcome
    order['exit_resolution_quality'] = 'daily_fallback' if not (hit_target and hit_stop) else 'daily_ambiguous_stop_fallback'
    _close_order(state, order, date=date, exit_fill_usd=fill, reason=reason, fx_rate=fx, raw_trigger_usd=raw_trigger)
    return True


def _process_order_day(state: dict, order: dict, *, date: str, bar, fx: float, intraday) -> bool:
    o, h, l, c = map(float, (bar['Open'], bar['High'], bar['Low'], bar['Close']))
    day_minutes = bars_for_date(intraday, date) if intraday is not None and not intraday.empty else None
    status = order.get('status')

    if status == 'PENDING':
        if date <= str(order.get('last_processed_date') or '')[:10]:
            return False
        if order.get('track_id') == TRACK_B:
            touch = first_buy_touch(day_minutes, float(order['buy_low']), float(order['buy_high'])) if day_minutes is not None else None
            if touch is None:
                _cancel_order(state, order, date, '다음 거래일 장중 BUY 구간 미도달')
                return True
            if not _fill_order(
                state,
                order,
                date=date,
                raw_entry=float(touch['raw_price']),
                fx=fx,
                entry_time=touch['timestamp'],
                quality=touch['quality'],
            ):
                return True
            order['last_close_usd'] = round(c, 6)
            _exit_order_from_bar(
                state, order, date=date, o=o, h=h, l=l, fx=fx,
                minute_bars=day_minutes, after_timestamp=touch['timestamp'],
            )
            return True

        lower = float(order['buy_low']) - float(order.get('gap_guard') or 0.0)
        upper = float(order['buy_high']) + float(order.get('gap_guard') or 0.0)
        if o < lower or o > upper:
            _cancel_order(state, order, date, f"다음 시가 {o:.2f}가 허용 진입범위 {lower:.2f}~{upper:.2f} 이탈")
            return True
        if not _fill_order(
            state,
            order,
            date=date,
            raw_entry=o,
            fx=fx,
            entry_time=(day_minutes.index[0].isoformat() if day_minutes is not None and not day_minutes.empty else None),
            quality='next_open',
        ):
            return True
        order['last_close_usd'] = round(c, 6)
        _exit_order_from_bar(state, order, date=date, o=o, h=h, l=l, fx=fx, minute_bars=day_minutes)
        return True

    if status != 'FILLED' or date <= str(order.get('last_processed_date') or '')[:10]:
        return False
    if _exit_order_from_bar(state, order, date=date, o=o, h=h, l=l, fx=fx, minute_bars=day_minutes):
        return True
    order['held_bars'] = int(order.get('held_bars') or 0) + 1
    order['last_close_usd'] = round(c, 6)
    order['last_fx'] = round(fx, 4)
    order['last_processed_date'] = date
    if int(order['held_bars']) >= int(order.get('max_hold_bars') or 1):
        fill = market_sell_fill(c, float(order['slippage_bps']), float(order['half_spread_bps']))
        order['exit_resolution_quality'] = 'time_exit_close'
        _close_order(state, order, date=date, exit_fill_usd=fill, reason='기간종료', fx_rate=fx, raw_trigger_usd=c)
    return True


def refresh_active(state: dict) -> int:
    active_symbols = sorted(
        {
            o.get('symbol')
            for o in state.get('orders', [])
            if o.get('status') in {'PENDING', 'FILLED'} and o.get('symbol')
        }
    )
    if not active_symbols:
        return 0
    fx = current_fx_rate()
    touched = 0
    for symbol in active_symbols:
        try:
            daily = fresh_price_history(symbol, '1mo')
        except Exception:
            continue
        try:
            intraday = fresh_intraday_history(symbol, '7d')
        except Exception:
            intraday = None
        if daily is None or daily.empty:
            continue
        for idx, bar in daily.iterrows():
            date = idx.strftime('%Y-%m-%d')
            for order in state.get('orders', []):
                if order.get('symbol') != symbol or order.get('status') not in {'PENDING', 'FILLED'}:
                    continue
                if _process_order_day(state, order, date=date, bar=bar, fx=fx, intraday=intraday):
                    touched += 1
    state['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    return touched


def _bucket_stats(rows: list[dict], key_fn) -> dict:
    out = {}
    for order in rows:
        key = str(key_fn(order) or 'UNKNOWN')
        bucket = out.setdefault(key, {'closed': 0, 'wins': 0, 'pnl_krw': 0.0, 'returns': []})
        bucket['closed'] += 1
        pnl = _number(order.get('pnl_krw'), 0.0)
        ret = _number(order.get('return_pct'), 0.0)
        bucket['pnl_krw'] += pnl
        bucket['returns'].append(ret)
        if pnl > 0:
            bucket['wins'] += 1
    for bucket in out.values():
        n = bucket['closed']
        bucket['win_rate_pct'] = round(bucket['wins'] / n * 100.0, 1) if n else 0.0
        bucket['avg_return_pct'] = round(sum(bucket['returns']) / n, 3) if n else None
        bucket['pnl_krw'] = round(bucket['pnl_krw'], 2)
        del bucket['returns']
    return out


def _rr_bucket(order: dict) -> str:
    rr = _number(order.get('official_risk_reward'), 0.0)
    if rr < 1.4:
        return '1.20~1.39'
    if rr < 1.7:
        return '1.40~1.69'
    return '1.70+'


def _hold_bucket(order: dict) -> str:
    bars = int(order.get('held_bars') or 0) + 1
    return '1~2일' if bars <= 2 else '3~5일' if bars <= 5 else '6일+'


def _equity_curve(state: dict, closed: list[dict]) -> tuple[list[dict], float]:
    equity = float(state.get('starting_cash_krw') or 0.0)
    peak = equity
    max_dd = 0.0
    curve = [{'label': 'START', 'equity_krw': round(equity, 2)}]
    ordered = sorted(closed, key=lambda o: (str(o.get('exit_date') or ''), str(o.get('closed_at') or ''), str(o.get('id') or '')))
    for o in ordered:
        equity += _number(o.get('pnl_krw'), 0.0)
        peak = max(peak, equity)
        dd = (equity / peak - 1.0) * 100.0 if peak > 0 else 0.0
        max_dd = min(max_dd, dd)
        curve.append({'label': str(o.get('exit_date') or ''), 'symbol': o.get('symbol'), 'equity_krw': round(equity, 2)})
    return curve, round(max_dd, 2)


def _sample_gate(closed_count: int) -> dict:
    n = int(closed_count)
    if n < MIN_FORWARD_REVIEW_TRADES:
        return {
            'stage': '표본 축적중',
            'production_tuning_locked': True,
            'next_milestone': MIN_FORWARD_REVIEW_TRADES,
            'remaining': MIN_FORWARD_REVIEW_TRADES - n,
            'message': f'종료거래 {MIN_FORWARD_REVIEW_TRADES}건 전에는 전략 수치 튜닝을 잠급니다.',
        }
    if n < FULL_FORWARD_REVIEW_TRADES:
        return {
            'stage': '1차 가설검토',
            'production_tuning_locked': True,
            'next_milestone': FULL_FORWARD_REVIEW_TRADES,
            'remaining': FULL_FORWARD_REVIEW_TRADES - n,
            'message': f'{FULL_FORWARD_REVIEW_TRADES}건 전까지는 가설만 기록하고 production 승격은 보류합니다.',
        }
    return {
        'stage': '정식 Forward Review 가능',
        'production_tuning_locked': False,
        'next_milestone': None,
        'remaining': 0,
        'message': '충분한 forward 표본이 쌓여 A/B와 조건별 성과를 정식 검토할 수 있습니다.',
    }


def lab_snapshot(state: dict, track_id: str | None = None) -> dict:
    track_id = track_id or str((state.get('lab_meta') or {}).get('track_id') or TRACK_A)
    if track_id not in TRACKS:
        track_id = TRACK_A
    _ensure_meta(state, track_id)
    base = snapshot(state)
    closed = [o for o in base.get('orders', []) if o.get('status') == 'CLOSED']
    curve, realized_mdd = _equity_curve(base, closed)
    base['lab_summary'] = {
        'track_id': track_id,
        'track_label': TRACKS[track_id]['label'],
        'total_orders': len(base.get('orders') or []),
        'closed_orders': len(closed),
        'submitted_decisions': sum(1 for x in base.get('shadow_decisions', []) if x.get('decision') == 'SUBMITTED'),
        'skipped_decisions': sum(1 for x in base.get('shadow_decisions', []) if x.get('decision') == 'SKIPPED'),
        'realized_curve_max_drawdown_pct': realized_mdd,
        'equity_curve': curve,
        'sample_gate': _sample_gate(len(closed)),
        'by_strategy': _bucket_stats(closed, lambda o: o.get('strategy_id')),
        'by_event_risk': _bucket_stats(closed, lambda o: (o.get('event_risk_snapshot') or {}).get('risk_code')),
        'by_market_state': _bucket_stats(closed, lambda o: o.get('market_state')),
        'by_exit_reason': _bucket_stats(closed, lambda o: o.get('exit_reason')),
        'by_rr': _bucket_stats(closed, _rr_bucket),
        'by_hold': _bucket_stats(closed, _hold_bucket),
        'by_resolution_quality': _bucket_stats(closed, lambda o: o.get('exit_resolution_quality')),
    }
    return base


def status(*, state_path: str | Path = STATE_FILE_A, track_id: str = TRACK_A) -> dict:
    store = PaperBrokerStore(state_path)
    state = store.load()
    _ensure_meta(state, track_id)
    return lab_snapshot(state, track_id)


def _run_track(*, state_path: str | Path, track_id: str, history: dict, scan: dict, fx: float) -> dict:
    store = PaperBrokerStore(state_path)
    state = store.load()
    _ensure_meta(state, track_id)
    refresh_active(state)
    result = ingest_confirmed_signals(state, history, fx_rate=fx, live_scan=scan, track_id=track_id)
    state['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    state['lab_meta']['last_run_at'] = state['updated_at']
    state['lab_meta']['last_ingest'] = result
    saved = store.save(state)
    return lab_snapshot(saved, track_id)


def combined_snapshot(a: dict, b: dict) -> dict:
    return {
        'version': LAB_VERSION,
        'baseline': baseline_snapshot(),
        'tracks': {TRACK_A: a, TRACK_B: b},
        'comparison': {
            'closed_a': int((a.get('lab_summary') or {}).get('closed_orders') or 0),
            'closed_b': int((b.get('lab_summary') or {}).get('closed_orders') or 0),
            'equity_a_krw': (a.get('summary') or {}).get('equity_krw'),
            'equity_b_krw': (b.get('summary') or {}).get('equity_krw'),
            'realized_pnl_a_krw': (a.get('summary') or {}).get('realized_pnl_krw'),
            'realized_pnl_b_krw': (b.get('summary') or {}).get('realized_pnl_krw'),
            'win_rate_a_pct': (a.get('summary') or {}).get('win_rate_pct'),
            'win_rate_b_pct': (b.get('summary') or {}).get('win_rate_pct'),
            'production_tuning_locked': bool(
                ((a.get('lab_summary') or {}).get('sample_gate') or {}).get('production_tuning_locked', True)
                or ((b.get('lab_summary') or {}).get('sample_gate') or {}).get('production_tuning_locked', True)
            ),
        },
        # backward-compatible A-track fields for older UI callers
        'summary': a.get('summary'),
        'lab_summary': a.get('lab_summary'),
        'lab_meta': a.get('lab_meta'),
        'orders': a.get('orders'),
    }


def status_all() -> dict:
    a = status(state_path=STATE_FILE_A, track_id=TRACK_A)
    b = status(state_path=STATE_FILE_B, track_id=TRACK_B)
    return combined_snapshot(a, b)


def run_all() -> dict:
    history = _load_json(HISTORY_FILE, {'days': []})
    scan = _load_json(SCAN_FILE, {'results': []})
    fx = current_fx_rate()
    a = _run_track(state_path=STATE_FILE_A, track_id=TRACK_A, history=history, scan=scan, fx=fx)
    b = _run_track(state_path=STATE_FILE_B, track_id=TRACK_B, history=history, scan=scan, fx=fx)
    return combined_snapshot(a, b)


def run(*, state_path: str | Path = STATE_FILE_A) -> dict:
    # Compatibility helper: explicit custom path runs the A track; default runs both.
    if Path(state_path) == STATE_FILE_A:
        return run_all()
    history = _load_json(HISTORY_FILE, {'days': []})
    scan = _load_json(SCAN_FILE, {'results': []})
    fx = current_fx_rate()
    return _run_track(state_path=state_path, track_id=TRACK_A, history=history, scan=scan, fx=fx)


def main():
    result = run_all()
    print(json.dumps({'comparison': result.get('comparison'), 'baseline': result.get('baseline')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
