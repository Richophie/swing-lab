from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from config import PUBLIC_STRATEGIES
from market_data import fresh_price_history
from paper_broker import PaperBrokerStore, process_bar, snapshot, submit_order
from risk_observability import snapshot_event_risk

ROOT = Path(__file__).parent
STATIC = ROOT / 'static'
SCAN_FILE = STATIC / 'latest_scan.json'
FX_FILE = STATIC / 'fx_cache.json'
STATE_FILE = Path(os.getenv('PAPER_BROKER_STATE_FILE', ROOT / 'runtime' / 'paper_broker_state.json'))


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def _tag_legacy_origins(state: dict) -> int:
    """Migrate pre-origin Paper orders.

    Before this field existed, every UI/CLI Paper submit path used latest_scan, so
    legacy orders can be classified as LIVE_CANDIDATE without inventing an official
    close-confirmed history.
    """
    changed = 0
    for order in state.get('orders', []):
        if order.get('order_origin'):
            continue
        order['order_origin'] = 'LIVE_CANDIDATE'
        order['signal_origin'] = order.get('signal_origin') or 'legacy_latest_scan'
        order['origin_migrated'] = True
        changed += 1
    return changed


def current_fx_rate() -> float:
    cached = _load_json(FX_FILE, {})
    try:
        fx = float(cached.get('usdkrw'))
        if 500 < fx < 3000:
            return fx
    except Exception:
        pass
    d = fresh_price_history('KRW=X', '5d')
    fx = float(d['Close'].dropna().iloc[-1])
    if not 500 < fx < 3000:
        raise ValueError('USD/KRW 환율을 확인할 수 없습니다')
    return fx


def latest_plan(symbol: str, strategy_id: str | None = None) -> dict:
    symbol = str(symbol or '').upper().strip()
    data = _load_json(SCAN_FILE, {'results': []})
    for row in data.get('results') or []:
        if str(row.get('symbol', '')).upper() != symbol:
            continue
        signals = [s for s in row.get('strategy_signals') or [] if s.get('strategy_id') in PUBLIC_STRATEGIES]
        if strategy_id:
            signal = next((s for s in signals if s.get('strategy_id') == strategy_id), None)
        else:
            signals.sort(
                key=lambda s: (
                    bool(s.get('elite_pass')),
                    float(s.get('elite_score', s.get('strategy_score', 0)) or 0),
                ),
                reverse=True,
            )
            signal = signals[0] if signals else None
        if signal is None:
            raise ValueError(f'{symbol}의 공개 전략 신호를 찾지 못했습니다')
        sid = signal.get('strategy_id')
        plans = row.get('strategy_trade_plans') or {}
        plan = dict(plans.get(sid) or row.get('trade_plan') or {})
        if not plan:
            raise ValueError(f'{symbol} {sid} 매매계획을 찾지 못했습니다')
        return {
            'symbol': symbol,
            'strategy_id': sid,
            'strategy_name': signal.get('strategy_name') or sid,
            'plan': plan,
            'scan_date': str(data.get('market_date') or data.get('scanned_at') or '')[:10],
            'signal_origin': 'LIVE_CANDIDATE',
            'event_risk_snapshot': snapshot_event_risk(row.get('event_risk')),
        }
    raise ValueError(f'{symbol}이 latest_scan.json에 없습니다')


def _latest_market_date(symbol: str) -> str:
    d = fresh_price_history(symbol, '10d')
    if d.empty:
        raise ValueError(f'{symbol} 가격 데이터가 없습니다')
    return d.index[-1].strftime('%Y-%m-%d')


def submit_from_latest(
    symbol: str,
    strategy_id: str | None = None,
    *,
    state_path: str | Path = STATE_FILE,
) -> dict:
    info = latest_plan(symbol, strategy_id)
    fx = current_fx_rate()
    market_date = _latest_market_date(info['symbol'])
    store = PaperBrokerStore(state_path)
    state = store.load()
    _tag_legacy_origins(state)
    order = submit_order(
        state,
        symbol=info['symbol'],
        strategy_id=info['strategy_id'],
        strategy_name=info['strategy_name'],
        plan=info['plan'],
        fx_rate=fx,
        submitted_market_date=market_date,
        signal_date=info.get('scan_date') or market_date,
    )
    # Paper orders created from the live detail screen are research orders. They
    # must never be mistaken for close-confirmed official-paper performance.
    order['order_origin'] = 'LIVE_CANDIDATE'
    order['signal_origin'] = 'intraday_latest_scan'
    order['event_risk_snapshot'] = dict(info.get('event_risk_snapshot') or {})
    order['risk_observability_only'] = True
    saved = store.save(state)
    return {'order': order, 'summary': snapshot(saved)['summary'], 'state_file': str(Path(state_path))}


def refresh_active(*, state_path: str | Path = STATE_FILE) -> dict:
    store = PaperBrokerStore(state_path)
    state = store.load()
    _tag_legacy_origins(state)
    active_symbols = sorted({o.get('symbol') for o in state.get('orders', []) if o.get('status') in {'PENDING', 'FILLED'} and o.get('symbol')})
    if not active_symbols:
        return snapshot(store.save(state))
    fx = current_fx_rate()
    for symbol in active_symbols:
        d = fresh_price_history(symbol, '1mo')
        if d.empty:
            continue
        for idx, bar in d.iterrows():
            date = idx.strftime('%Y-%m-%d')
            process_bar(
                state,
                symbol=symbol,
                date=date,
                open_px=float(bar['Open']),
                high_px=float(bar['High']),
                low_px=float(bar['Low']),
                close_px=float(bar['Close']),
                fx_rate=fx,
            )
    return snapshot(store.save(state))


def status(*, state_path: str | Path = STATE_FILE) -> dict:
    store = PaperBrokerStore(state_path)
    state = store.load()
    _tag_legacy_origins(state)
    return snapshot(store.save(state))


def reset(*, state_path: str | Path = STATE_FILE) -> dict:
    store = PaperBrokerStore(state_path)
    return snapshot(store.reset())


def main():
    parser = argparse.ArgumentParser(description='Swing Lab paper broker')
    parser.add_argument('--state', default=str(STATE_FILE), help='paper state JSON path')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status')
    submit = sub.add_parser('submit')
    submit.add_argument('symbol')
    submit.add_argument('--strategy', choices=list(PUBLIC_STRATEGIES))
    sub.add_parser('refresh')
    sub.add_parser('reset')
    args = parser.parse_args()
    state_path = Path(args.state)
    if args.command == 'status':
        result = status(state_path=state_path)
    elif args.command == 'submit':
        result = submit_from_latest(args.symbol, args.strategy, state_path=state_path)
    elif args.command == 'refresh':
        result = refresh_active(state_path=state_path)
    else:
        result = reset(state_path=state_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()