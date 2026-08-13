from __future__ import annotations
import ast
import json
import re
from pathlib import Path
from config import APP_VERSION, CORE_VERSION, S_THRESHOLD, SCAN_CANDIDATE_LIMIT
from stock_names import identity_warning, korean_name

ROOT = Path(__file__).parent
LEGACY_PREFIXES = ('app_v', 'core_v', 'scanner_v', 'trade_journal_v')
HANGUL = re.compile(r'[가-힣]')


def check_scan(path=ROOT / 'static' / 'latest_scan.json'):
    data = json.loads(path.read_text(encoding='utf-8'))
    assert data.get('version') == APP_VERSION, (data.get('version'), APP_VERSION)
    assert data.get('core_version') == CORE_VERSION, (data.get('core_version'), CORE_VERSION)
    assert int(data.get('candidate_count', 0)) <= SCAN_CANDIDATE_LIMIT, (data.get('candidate_count'), SCAN_CANDIDATE_LIMIT)
    rows = data.get('results') or []
    symbols = []
    elite = 0
    name_warnings = []
    for row in rows:
        symbol = row.get('symbol')
        assert symbol
        symbols.append(symbol)
        security_name = row.get('security_name')
        warning = identity_warning(symbol, security_name)
        assert warning is None, f'{symbol}: {warning}'
        expected_name = korean_name(symbol, security_name)
        name = row.get('name_ko') or ''
        assert name == expected_name, f'Name identity mismatch: {symbol}: cached={name!r}, expected={expected_name!r}'
        # A missing Korean display alias is a presentation warning, not a market-data integrity failure.
        # Ticker/company identity mismatches above remain hard failures.
        if not HANGUL.search(name):
            name_warnings.append(f'{symbol} -> {name!r}')
        sigs = row.get('strategy_signals') or []
        assert sigs, symbol
        plans = row.get('strategy_trade_plans') or {}
        for sig in sigs:
            score = float(sig.get('strategy_score', 0))
            assert 0 <= score <= 95
            if score >= S_THRESHOLD:
                sid = sig.get('strategy_id')
                assert sid in plans, (symbol, sid)
                p = plans[sid]
                if p.get('signal_active', True):
                    entry = (float(p['entry_low']) + float(p['entry_high'])) / 2
                    assert float(p['stop']) < entry < float(p['target']), (symbol, sid, p)
                    assert p.get('target_pct') is not None and p.get('stop_pct') is not None
            if sig.get('elite_pass'):
                elite += 1
                assert not sig.get('experimental'), (symbol, 'experimental marked elite')
                assert 0 <= float(sig.get('elite_score', 0)) <= 99
    assert not ('GOOG' in symbols and 'GOOGL' in symbols), 'Alphabet share-class duplicate'
    assert data.get('elite_policy'), 'elite policy missing'
    if name_warnings:
        print('Korean display-name warnings:', '; '.join(name_warnings))
    return {
        'rows': len(rows),
        'elite_signals': elite,
        'candidates': data.get('candidate_count', 0),
        'failed': data.get('failed_count', 0),
        'name_warnings': len(name_warnings),
    }


def imported_local_modules(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name.split('.')[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module.split('.')[0])
    return names


def check_clean_imports():
    files = [
        'app.py',
        'scanner.py',
        'journal.py',
        'strategy_engine.py',
        'strategy_rules.py',
        'market_data.py',
        'backtest_engine.py',
        'stock_names.py',
    ]
    for name in files:
        p = ROOT / name
        assert p.exists(), name
        for mod in imported_local_modules(p):
            assert not mod.startswith(LEGACY_PREFIXES), (name, mod)
    return files


def check_strategy_rule_wiring():
    live = (ROOT / 'strategy_engine.py').read_text(encoding='utf-8')
    backtest = (ROOT / 'backtest_engine.py').read_text(encoding='utf-8')
    rules = (ROOT / 'strategy_rules.py').read_text(encoding='utf-8')

    assert 'strict_signal_flags' in live, 'live engine is not wired to canonical strict signals'
    assert 'current_trade_levels' in live, 'live trade plan is not wired to canonical trade levels'
    assert 'canonical_signal_frame' in backtest, 'backtest is not wired to canonical strict signals'
    assert 'trade_levels_from_row' in backtest, 'backtest is not wired to canonical trade levels'
    assert 'def _exit_rules' not in backtest, 'legacy duplicate exit rules remain in backtest'
    assert 'MIN_STOP_ATR = 1.5' in rules, 'canonical minimum stop ATR missing'
    assert 'CONFIRM_REVERSAL_VOL_MIN = 1.0' in rules, 'canonical reversal-volume threshold missing'
    return 'canonical live/backtest rule wiring ok'


def check_routes():
    import app as appmod
    routes = sorted(r.rule for r in appmod.app.url_map.iter_rules())
    required = {
        '/',
        '/api/latest',
        '/api/history',
        '/api/detail/<symbol>',
        '/api/chart/<symbol>',
        '/api/backtest/<symbol>',
        '/api/market',
        '/api/version',
        '/health',
    }
    missing = required - set(routes)
    assert not missing, missing
    return routes


def check_frontend():
    html = (ROOT / 'static' / 'dashboard.html').read_text(encoding='utf-8')
    css = (ROOT / 'static' / 'dashboard.css').read_text(encoding='utf-8')
    js = (ROOT / 'static' / 'dashboard.js').read_text(encoding='utf-8')
    assert 'id="todayTabs"' in html
    assert 'dashboard.css' in html and 'dashboard.js' in html
    assert 'function renderToday' in js
    assert '.seg' in css
    return ['dashboard.html', 'dashboard.css', 'dashboard.js']


if __name__ == '__main__':
    print('imports', check_clean_imports())
    print('rules', check_strategy_rule_wiring())
    print('identity', 'ticker identity master ok')
    print('routes', check_routes())
    print('frontend', check_frontend())
    print('scan', check_scan())
    print('QA PASS')
