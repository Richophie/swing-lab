from __future__ import annotations

from flask import jsonify, request

import app as app_module
import paper_broker_service as paper_service
from app import (
    HISTORY_FILE,
    SCAN_FILE,
    SIGNAL_EVENTS_FILE,
    _decorate_paper_snapshot,
    _paper_state_path,
    app,
)
from config import (
    APP_VERSION,
    BACKTEST_INITIAL_CAPITAL_KRW,
    BACKTEST_MAX_POSITION_PCT,
    BACKTEST_MAX_POSITIONS,
    BACKTEST_RISK_PER_TRADE_PCT,
    CORE_VERSION,
    PUBLIC_STRATEGIES,
    SCAN_CANDIDATE_LIMIT,
    S_THRESHOLD,
)
from paper_manual import close_or_cancel_manual, preview_manual, submit_manual
from paper_marks import current_marks
from paper_restore import restore_browser_backup
from repo_data import load_json
from shadow_lab import STATE_FILE as SHADOW_STATE_FILE, lab_snapshot

# Production data commits intentionally use [skip render]. Patch the imported app
# module's JSON loader so all existing /api/latest, /api/history and signal-event
# handlers resolve the newest repo-backed static data on Render while retaining an
# immediate local fallback when GitHub is unavailable.
app_module.load_json = load_json
paper_service._load_json = load_json


def _shadow_snapshot():
    state = load_json(
        SHADOW_STATE_FILE,
        {
            'version': 1,
            'starting_cash_krw': BACKTEST_INITIAL_CAPITAL_KRW,
            'cash_krw': BACKTEST_INITIAL_CAPITAL_KRW,
            'orders': [],
            'events': [],
            'shadow_decisions': [],
            'live_trading_enabled': False,
        },
    )
    return lab_snapshot(state)


@app.route('/api/paper/restore', methods=['POST'])
def paper_restore_api():
    body = request.get_json(silent=True) or {}
    try:
        restored = restore_browser_backup(body.get('state') or {}, state_path=_paper_state_path())
        return jsonify(_decorate_paper_snapshot(restored))
    except Exception as exc:
        return jsonify({'error': str(exc)}), 400


@app.route('/api/paper/marks', methods=['GET'])
def paper_marks_api():
    try:
        return jsonify(current_marks(_paper_state_path()))
    except Exception as exc:
        return jsonify({'error': str(exc)}), 400


@app.route('/api/paper/manual-preview', methods=['GET'])
def paper_manual_preview_api():
    symbol = str(request.args.get('symbol') or '').upper().strip()
    strategy = request.args.get('strategy') or None
    if not symbol:
        return jsonify({'error': 'symbol이 필요합니다'}), 400
    try:
        return jsonify(preview_manual(symbol, strategy, state_path=_paper_state_path()))
    except Exception as exc:
        return jsonify({'error': str(exc)}), 400


@app.route('/api/paper/manual-submit', methods=['POST'])
def paper_manual_submit_api():
    body = request.get_json(silent=True) or {}
    symbol = str(body.get('symbol') or '').upper().strip()
    strategy = body.get('strategy') or None
    qty = body.get('qty')
    if not symbol:
        return jsonify({'error': 'symbol이 필요합니다'}), 400
    try:
        requested_qty = None if qty in (None, '', 0, '0') else int(qty)
        data = submit_manual(
            symbol,
            strategy,
            requested_qty=requested_qty,
            state_path=_paper_state_path(),
        )
        return jsonify(_decorate_paper_snapshot(data))
    except Exception as exc:
        return jsonify({'error': str(exc)}), 400


@app.route('/api/paper/close', methods=['POST'])
def paper_close_api():
    body = request.get_json(silent=True) or {}
    try:
        data = close_or_cancel_manual(body.get('order_id'), state_path=_paper_state_path())
        return jsonify(_decorate_paper_snapshot(data))
    except Exception as exc:
        return jsonify({'error': str(exc)}), 400


@app.route('/api/shadow', methods=['GET'])
def shadow_status_api():
    try:
        return jsonify(_shadow_snapshot())
    except Exception as exc:
        return jsonify({'error': str(exc)}), 400


@app.route('/api/engine-status', methods=['GET'])
def engine_status_api():
    scan = load_json(SCAN_FILE, {'status': 'pending', 'results': []})
    history = load_json(HISTORY_FILE, {'summary': {}, 'days': []})
    events = load_json(SIGNAL_EVENTS_FILE, {'active': {}, 'elite_active': {}, 'events': []})
    shadow = _shadow_snapshot()
    rows = scan.get('results') or []
    raw_s = 0
    elite = 0
    for row in rows:
        for sig in row.get('strategy_signals') or []:
            if sig.get('strategy_id') not in PUBLIC_STRATEGIES:
                continue
            if float(sig.get('strategy_score') or 0) >= S_THRESHOLD:
                raw_s += 1
            if bool(sig.get('elite_pass')):
                elite += 1
    return jsonify(
        {
            'app_version': APP_VERSION,
            'core_version': CORE_VERSION,
            'architecture': 'clean / paper_entry / repo-data-fallback',
            'scan': {
                'status': scan.get('status'),
                'scanned_at': scan.get('scanned_at'),
                'universe_count': scan.get('universe_count'),
                'candidate_limit': SCAN_CANDIDATE_LIMIT,
                'candidate_count': scan.get('candidate_count'),
                'failed_count': scan.get('failed_count'),
                'market_state': (scan.get('market') or {}).get('state'),
                'market_brief': (scan.get('market') or {}).get('brief'),
                'raw_s_signals': raw_s,
                'elite_signals': elite,
            },
            'rules': {
                'public_strategies': list(PUBLIC_STRATEGIES),
                's_threshold': S_THRESHOLD,
                'paper_initial_capital_krw': BACKTEST_INITIAL_CAPITAL_KRW,
                'max_positions': BACKTEST_MAX_POSITIONS,
                'risk_per_trade_pct': BACKTEST_RISK_PER_TRADE_PCT,
                'max_position_pct': BACKTEST_MAX_POSITION_PCT,
                'live_trading_enabled': False,
            },
            'official_history': history.get('summary') or {},
            'intraday_log': {
                'active_s': len(events.get('active') or {}),
                'active_elite': len(events.get('elite_active') or {}),
                'event_count': len(events.get('events') or []),
                'updated_at': events.get('updated_at'),
            },
            'shadow_lab': shadow.get('lab_summary') or {},
        }
    )
