from __future__ import annotations
import json
from pathlib import Path
from config import APP_VERSION, CORE_VERSION, PUBLIC_STRATEGIES, S_THRESHOLD

ROOT=Path(__file__).parent


def check_scan(path=ROOT/'static'/'latest_scan.json'):
    data=json.loads(path.read_text(encoding='utf-8'))
    assert data.get('version')==APP_VERSION,(data.get('version'),APP_VERSION)
    assert data.get('core_version')==CORE_VERSION,(data.get('core_version'),CORE_VERSION)
    rows=data.get('results') or []
    symbols=[]
    for row in rows:
        assert row.get('symbol');symbols.append(row['symbol'])
        assert row.get('name_ko') or row.get('security_name')
        sigs=row.get('strategy_signals') or []
        assert sigs,row['symbol']
        plans=row.get('strategy_trade_plans') or {}
        for sig in sigs:
            assert 0<=float(sig.get('strategy_score',0))<=95
            if float(sig.get('strategy_score',0))>=S_THRESHOLD:
                assert sig.get('strategy_id') in plans,(row['symbol'],sig.get('strategy_id'))
                p=plans[sig['strategy_id']];entry=(float(p['entry_low'])+float(p['entry_high']))/2
                assert float(p['stop'])<entry<float(p['target']),(row['symbol'],sig['strategy_id'],p)
    assert not ('GOOG' in symbols and 'GOOGL' in symbols),'Alphabet share-class duplicate'
    return {'rows':len(rows),'failed':data.get('failed_count',0)}


def check_imports():
    import app,scanner,journal,strategy_engine,market_data,backtest_engine
    rules=[('app',app),('scanner',scanner),('journal',journal),('strategy_engine',strategy_engine),('market_data',market_data),('backtest_engine',backtest_engine)]
    for name,module in rules:
        src=Path(module.__file__).read_text(encoding='utf-8')
        assert 'app_v' not in src and 'core_v' not in src and 'scanner_v' not in src,f'legacy import remains in {name}'
    return [x[0] for x in rules]


def check_routes():
    from app import app
    routes={r.rule for r in app.url_map.iter_rules()}
    required={'/','/health','/api/version','/api/latest','/api/history','/api/market','/api/detail/<symbol>','/api/chart/<symbol>','/api/backtest/<symbol>'}
    assert required<=routes,required-routes
    return sorted(required)


if __name__=='__main__':
    print('imports',check_imports());print('routes',check_routes());print('scan',check_scan())
