from datetime import datetime, timezone
from pathlib import Path
import json
import yfinance as yf

from scanner_v6 import load_universe, prefilter
from app_v6 import trade_plan, historical_stats, market_live, history
from core_v3 import playbooks, _series

OUT = Path(__file__).parent / 'static' / 'latest_scan.json'


def grade_for(ens):
    if not ens.get('recommend'):
        return 'B' if float(ens.get('ensemble_score', 0)) >= 58 else 'C'
    return 'S' if float(ens.get('ensemble_score', 0)) >= 82 else 'A'


def batch_score(symbols, market):
    results = []
    failed = 0
    state = market.get('state') if isinstance(market, dict) else None
    for start in range(0, len(symbols), 100):
        chunk = symbols[start:start+100]
        try:
            bulk = yf.download(' '.join(chunk), period='14mo', interval='1d', auto_adjust=False,
                               group_by='ticker', threads=True, progress=False, timeout=25)
        except Exception:
            failed += len(chunk)
            continue
        for symbol in chunk:
            try:
                d = bulk.copy() if len(chunk) == 1 else bulk[symbol].copy()
                d = d.dropna(subset=['Open', 'High', 'Low', 'Close'])
                if len(d) < 205:
                    failed += 1
                    continue
                ens = playbooks(d, state)
                best = ens['best_strategy']
                grade = grade_for(ens)
                z = _series(d)
                results.append({
                    'symbol': symbol,
                    'score': ens['ensemble_score'],
                    'grade': grade,
                    'eligible': bool(ens.get('recommend')),
                    'strategy_name': best['name'],
                    'strategy_id': best['id'],
                    'strategy_reason': ens['reason'],
                    'strategy_agreement': ens['agreement'],
                    'confidence': ens['confidence'],
                    'ensemble': ens,
                    'rsi': round(float(z['rsi']), 1),
                    'd120': round((float(d['Close'].iloc[-1]) / float(z['s120']) - 1) * 100, 2),
                    'bb_pos': round(float(z['bb']) * 100, 1),
                    'sparkline': [round(float(x), 2) for x in d['Close'].tail(35).tolist()],
                })
            except Exception:
                failed += 1
    results.sort(key=lambda x: (1 if x['grade'] == 'S' else 0, x['score']), reverse=True)
    return results, failed


def main():
    universe = load_universe()
    candidates = prefilter(universe)
    market = market_live()
    base, failed = batch_score(candidates, market)

    promoted = [r for r in base if r.get('grade') in {'S', 'A'} and r.get('eligible')]
    final = []
    for r in promoted[:30]:
        try:
            d = history(r['symbol'], '10y')
            r['trade_plan'] = trade_plan(d)
            r['history_stats'] = historical_stats(d)
            final.append(r)
        except Exception as exc:
            r['detail_error'] = str(exc)
            final.append(r)

    final.sort(key=lambda x: (1 if x.get('grade') == 'S' else 0, x.get('score', 0)), reverse=True)
    payload = {
        'status': 'ready',
        'version': '11.0',
        'core_version': '3.1',
        'scanned_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'universe_count': len(universe),
        'candidate_count': len(candidates),
        'failed_count': failed,
        'market': market,
        'results': final,
        'ranking_note': 'A/S 등급만 공개합니다. 각 전략을 독립 판정한 뒤 현재 가장 강한 전략으로 순위를 냅니다.'
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print('saved', OUT, len(final))


if __name__ == '__main__':
    main()
