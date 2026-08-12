from __future__ import annotations

"""One-time/idempotent historical journal rebuild using the CURRENT strategy logic.

The historical day is evaluated only with bars available on that day.  This prevents
old, looser strategy revisions from polluting the live validation journal.
"""

from datetime import datetime, timezone
from pathlib import Path
import json
import pandas as pd
import yfinance as yf

from config import SCAN_CANDIDATE_LIMIT
from market_data import load_us_universe, prefilter_symbols
from strategy_engine import evaluate_strategies, trade_plan, public_s_signals, experimental_s_signals
from scanner import _current_selection, _first_20d_pullback_overlay, _dedupe_share_classes
from stock_names import korean_name
from journal import freeze_signal, load, save, JOURNAL_FILE

TARGET_DAY = '2026-08-12'
REVISION = 'current-core-rebuild-2026-08-12-v1'


def _frame(bulk, symbol, count):
    try:
        d = bulk.copy() if count == 1 else bulk[symbol].copy()
        d = d.dropna(subset=['Open','High','Low','Close']).copy()
        idx = pd.to_datetime(d.index)
        d.index = idx.tz_localize(None) if getattr(idx, 'tz', None) is not None else idx
        return d[d.index.date <= pd.Timestamp(TARGET_DAY).date()]
    except Exception:
        return pd.DataFrame()


def _market_state():
    try:
        bulk = yf.download('SPY QQQ', period='14mo', interval='1d', auto_adjust=False,
                           group_by='ticker', threads=True, progress=False, timeout=25)
        good = 0
        for sym in ('SPY','QQQ'):
            d = _frame(bulk, sym, 2)
            c = d['Close'].astype(float)
            if len(c) >= 200 and c.iloc[-1] > c.rolling(120).mean().iloc[-1] and c.iloc[-1] > c.rolling(200).mean().iloc[-1]:
                good += 1
        return '좋음' if good == 2 else '중립' if good == 1 else '조심'
    except Exception:
        return '중립'


def rebuild():
    journal = load(JOURNAL_FILE, {'version':'4.1','days':[]})
    migrations = journal.setdefault('historical_rebuilds', {})
    if migrations.get(TARGET_DAY) == REVISION:
        print('historical day already rebuilt', TARGET_DAY, REVISION)
        return

    universe = load_us_universe()
    names = {x['symbol']:x.get('security_name') for x in universe}
    symbols = prefilter_symbols(universe, SCAN_CANDIDATE_LIMIT)
    state = _market_state()
    rows = []

    for start in range(0, len(symbols), 100):
        chunk = symbols[start:start+100]
        try:
            bulk = yf.download(' '.join(chunk), period='14mo', interval='1d', auto_adjust=False,
                               group_by='ticker', threads=True, progress=False, timeout=25)
        except Exception:
            continue
        for symbol in chunk:
            d = _frame(bulk, symbol, len(chunk))
            if len(d) < 205:
                continue
            try:
                ev = evaluate_strategies(d, state)
                sigs = public_s_signals(ev) + experimental_s_signals(ev)
                if not sigs:
                    continue
                overlay = _first_20d_pullback_overlay(d)
                frozen_sigs = []
                plans = {}
                for s in sigs:
                    sid = s['id']
                    plan = trade_plan(d, sid)
                    plans[sid] = plan
                    experimental = sid == 'volatility_breakout'
                    if experimental:
                        assessment = {'elite_pass':False,'elite_score':s['score'],'selection_reason':'실험 전략 · 엄선에서 제외'}
                    else:
                        overlay_bonus = bool(overlay.get('active') and sid in {'confirmed_pullback','momentum_pullback'})
                        assessment = _current_selection(s['score'], plan, ev.get('flow'), overlay_bonus, state)
                    frozen_sigs.append({
                        'strategy_id':sid,'strategy_name':s['name'],'strategy_score':s['score'],
                        'why':s.get('why'),'evidence':s.get('evidence'),'experimental':experimental,
                        **assessment
                    })
                rows.append({
                    'symbol':symbol,'name_ko':korean_name(symbol,names.get(symbol)),
                    'security_name':names.get(symbol),'rsi':ev['metrics']['rsi'],'d120':ev['metrics']['d120'],
                    'bb_pos':ev['metrics']['bb_pos'],'flow':ev.get('flow') or {},
                    'sparkline':[round(float(x),2) for x in d['Close'].tail(35).tolist()],
                    'strategy_signals':frozen_sigs,'strategy_trade_plans':plans
                })
            except Exception:
                continue

    rows = _dedupe_share_classes(rows)
    items = []
    at = TARGET_DAY + 'T20:00:00+00:00'
    for row in rows:
        for sig in row['strategy_signals']:
            # Journal keeps public S signals; experimental signals remain labelled as research.
            if not sig.get('experimental') and float(sig.get('strategy_score') or 0) < 90:
                continue
            plan = row['strategy_trade_plans'].get(sig['strategy_id'])
            if not plan or not plan.get('signal_active'):
                continue
            item = freeze_signal(row, sig, plan, at, TARGET_DAY)
            item['historical_rebuild'] = True
            item['historical_rebuild_revision'] = REVISION
            items.append(item)

    days = journal.setdefault('days', [])
    old = next((d for d in days if d.get('date') == TARGET_DAY), None)
    if old is None:
        old = {'date':TARGET_DAY,'created_at':at,'updated_at':at,'items':[]}
        days.append(old)
    old['items'] = items
    old['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    old['rebuild_note'] = '2026-08-12 데이터를 현재 전략 로직으로 재평가한 기록'
    migrations[TARGET_DAY] = REVISION
    days.sort(key=lambda x:x.get('date',''), reverse=True)
    save(JOURNAL_FILE, journal)
    print('rebuilt', TARGET_DAY, 'with', len(items), 'current-logic S signals; market', state)


if __name__ == '__main__':
    rebuild()
