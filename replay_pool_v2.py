from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from gap_guard_research import _signal_candidates
from market_data import load_price_history
from rsi2_broad_regime_research import MIN_HISTORY_ROWS, research_universe
from structural_stop_research import STRATEGIES, STRATEGY_NAMES
from config import BACKTEST_COMMISSION_PCT, BACKTEST_SLIPPAGE_BPS, BACKTEST_HALF_SPREAD_BPS

OUT = Path('static/replay_backtest_pool_v2.json')
TARGET_SYMBOLS = 80
PATH_BARS = 12


def build():
    requested, source = research_universe()
    requested = requested[:TARGET_SYMBOLS]
    candidates, eligible, errors = [], [], []
    for symbol in requested:
        try:
            d = load_price_history(symbol, '10y').dropna()
            if len(d) < MIN_HISTORY_ROWS:
                raise ValueError(f'history rows {len(d)} < {MIN_HISTORY_ROWS}')
            frame, by_strategy = _signal_candidates(d, symbol)
            eligible.append(symbol)
        except Exception as exc:
            errors.append({'symbol': symbol, 'error': str(exc)})
            continue
        for sid in STRATEGIES:
            for signal_i, info in sorted(by_strategy[sid].items()):
                entry_i = int(signal_i) + 1
                if entry_i >= len(d):
                    continue
                plan = info['plan']
                path = []
                for j in range(entry_i, min(len(d), entry_i + PATH_BARS)):
                    bar = d.iloc[j]
                    path.append([
                        d.index[j].strftime('%Y-%m-%d'),
                        round(float(bar['Open']), 6), round(float(bar['High']), 6),
                        round(float(bar['Low']), 6), round(float(bar['Close']), 6),
                    ])
                if not path:
                    continue
                candidates.append({
                    'symbol': symbol, 'strategy_id': sid,
                    'strategy_name': STRATEGY_NAMES.get(sid, sid),
                    'signal_date': d.index[signal_i].strftime('%Y-%m-%d'),
                    'entry_date': d.index[entry_i].strftime('%Y-%m-%d'),
                    'signal_close': round(float(frame['close'].iloc[signal_i]), 6),
                    'buy_low': round(float(plan['buy_low']), 6),
                    'buy_high': round(float(plan['buy_high']), 6),
                    'atr': round(float(plan['atr']), 6),
                    'target': round(float(plan['target']), 6),
                    'stop': round(float(plan['stop']), 6),
                    'max_hold': int(plan['days'][1]),
                    'elite_score': round(float(info['elite_score']), 4),
                    'net_risk_reward': round(float(info['net_risk_reward']), 6),
                    'market_state': info['market_state'], 'path': path,
                })
    candidates.sort(key=lambda x: (x['entry_date'], -x['net_risk_reward'], -x['elite_score'], x['symbol']))
    dates = [x['entry_date'] for x in candidates]
    payload = {
        'version': 2, 'ready': True,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'selection_source': source, 'requested_symbol_count': len(requested),
        'eligible_symbol_count': len(eligible),
        'available_start': min(dates) if dates else None,
        'available_end': max(dates) if dates else None,
        'strategies': list(STRATEGIES), 'strategy_names': STRATEGY_NAMES,
        'candidate_count': len(candidates), 'path_bars': PATH_BARS,
        'costs': {'commission_pct_per_side': BACKTEST_COMMISSION_PCT,
                  'slippage_bps': BACKTEST_SLIPPAGE_BPS,
                  'half_spread_bps': BACKTEST_HALF_SPREAD_BPS},
        'errors': errors, 'trades': candidates,
        'limitations': [
            '현재 유동성 종목을 과거로 되감는 연구용 후보풀이라 survivorship bias가 있습니다.',
            '모든 엄선 신호일을 저장해 짧은 익절 후 다음 신호를 다시 잡을 수 있게 했습니다.',
            '일봉에서 같은 날 목표와 손절을 모두 터치하면 보수적으로 손절 우선 처리합니다.',
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print('eligible', len(eligible), 'candidates', len(candidates), 'errors', len(errors))


if __name__ == '__main__':
    build()
