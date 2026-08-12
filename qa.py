from __future__ import annotations
import ast
import json
import re
from pathlib import Path
from config import APP_VERSION, CORE_VERSION, S_THRESHOLD

ROOT=Path(__file__).parent
LEGACY_PREFIXES=('app_v','core_v','scanner_v','trade_journal_v')
HANGUL=re.compile(r'[가-힣]')


def check_scan(path=ROOT/'static'/'latest_scan.json'):
    data=json.loads(path.read_text(encoding='utf-8'))
    assert data.get('version')==APP_VERSION,(data.get('version'),APP_VERSION)
    assert data.get('core_version')==CORE_VERSION,(data.get('core_version'),CORE_VERSION)
    rows=data.get('results') or []
    symbols=[];elite=0
    for row in rows:
        symbol=row.get('symbol');assert symbol
        symbols.append(symbol)
        name=row.get('name_ko') or ''
        assert HANGUL.search(name),f'Korean display name missing: {symbol} -> {name!r}'
        sigs=row.get('strategy_signals') or [];assert sigs,symbol
        plans=row.get('strategy_trade_plans') or {}
        for sig in sigs:
            score=float(sig.get('strategy_score',0));assert 0<=score<=95
            if score>=S_THRESHOLD:
                sid=sig.get('strategy_id');assert sid in plans,(symbol,sid)
                p=plans[sid]
                entry=(float(p['entry_low'])+float(p['entry_high']))/2
                assert float(p['stop'])<entry<float(p['target']),(symbol,sid,p)
                assert p.get('target_pct') is not None and p.get('stop_pct') is not None
            if sig.get('elite_pass'):
                elite+=1
                assert not sig.get('experimental'),(symbol,'experimental marked elite')
                assert 0<=float(sig.get('elite_score',0))<=99
    assert not ('GOOG' in symbols and 'GOOGL' in symbols),'Alphabet share-class duplicate'
    assert data.get('elite_policy'),'elite policy missing'
    return {'rows':len(rows),'elite_signals':elite,'failed':data.get('failed_count',0)}


def imports_in(path):
    tree=ast.parse(path.read_text(encoding='utf-8'));mods=[]
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):mods.extend(a.name for a in node.names)
        elif isinstance(node,ast.ImportFrom) and node.module:mods.append(node.module)
    return mods


def check_imports():
    files=['app.py','scanner.py','journal.py','strategy_engine.py','market_data.py','backtest_engine.py','stock_names.py']
    for f in files:
        mods=imports_in(ROOT/f);bad=[m for m in mods if m.startswith(LEGACY_PREFIXES)]
        assert not bad,f'legacy imports in {f}: {bad}'
    return files


def check_routes():
    from app import app
    routes={r.rule for r in app.url_map.iter_rules()}
    required={'/','/health','/api/version','/api/latest','/api/history','/api/market','/api/detail/<symbol>','/api/chart/<symbol>','/api/backtest/<symbol>'}
    assert required<=routes,required-routes
    return sorted(required)


def check_frontend():
    html=(ROOT/'static'/'dashboard.html').read_text(encoding='utf-8')
    css=ROOT/'static'/'dashboard.css';js=ROOT/'static'/'dashboard.js';src=js.read_text(encoding='utf-8')
    assert css.exists() and js.exists(),'dashboard css/js missing'
    assert '<style' not in html.lower();assert '<script>' not in html.lower()
    assert '/static/dashboard.css' in html and '/static/dashboard.js' in html
    assert 'app_v' not in html and 'PRO LIVE v' not in html
    assert 'todayTabs' in html
    for token in ('rangePrice','fxRate','target_pct','엄선'):
        assert token in src,f'frontend token missing: {token}'
    return ['dashboard.html','dashboard.css','dashboard.js']


if __name__=='__main__':
    print('imports',check_imports())
    print('routes',check_routes())
    print('frontend',check_frontend())
    print('scan',check_scan())
