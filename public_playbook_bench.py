"""Published swing setups, replayed as written on our data.

The rules come from public sources (Connors' books, Quantified Strategies' free posts, the
Minervini / Qullamaggie style scanners on GitHub, the academic short-term reversal). They are
coded once from the published description and never tuned here, so every period in our data
is out-of-sample for them. The only thing we impose is our own execution: buy at the next
open (a person in Korea cannot buy the US close they just saw), sell by each setup's own exit,
all costs included.

Twenty setups are tested at once, so the bar for "this one is real" is raised accordingly.
Research only: nothing here changes a frozen rule or a recommendation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from config import BACKTEST_COMMISSION_PCT, BACKTEST_HALF_SPREAD_BPS, BACKTEST_SLIPPAGE_BPS
import strategy_evolution as se
from washout_refine_research import account
from washout_risk_research import SEGMENTS, base_signals

OUT = Path('static/public_playbook_bench.json')
SLOTS = 5

# name: (label, source, family, exit kind, exit parameter, last day, stop in ATR)
SETUPS = {
    'connors_rsi2': ('코너스 RSI(2) 과매도', "Larry Connors, 'Short Term Trading Strategies That Work'", 'reversion', 'rsi2_above', 70, 5, None),
    'connors_double_7s': ('코너스 더블 세븐', "Larry Connors, 'Short Term Trading Strategies That Work'", 'reversion', 'close_7d_high', None, 10, None),
    'three_down_days': ('사흘 연속 하락', 'Connors-style streak reversion (many public backtests)', 'reversion', 'above_sma5', None, 7, None),
    'ibs_low': ('IBS 저점 마감', 'Internal Bar Strength reversion (Quantified Strategies, TradingView scripts)', 'reversion', 'above_prev_high', None, 5, None),
    'qs_band_ibs': ('밴드 이탈 + IBS', "Quantified Strategies, '5 swing trading strategies' #1", 'reversion', 'above_prev_high', None, 7, None),
    'five_day_low': ('5일 저가 이탈', "Quantified Strategies, '5 swing trading strategies' #3", 'reversion', 'above_prev_high', None, 7, None),
    'turnaround_tuesday': ('턴어라운드 화요일', "Quantified Strategies, '5 swing trading strategies' #2", 'reversion', 'above_prev_high', None, 5, None),
    'bollinger_below_band': ('볼린저 하단 이탈', 'Bollinger %b reversion in an uptrend (Connors / public backtests)', 'reversion', 'above_sma5', None, 7, None),
    'weekly_losers': ('주간 낙폭 하위 10%', 'Short-term reversal, Lehmann (1990) / Jegadeesh (1990)', 'reversion', 'time', None, 5, None),
    'new_high_low_ibs': ('신고가 날 약한 마감', "Quantified Strategies, '5 swing trading strategies' #5", 'reversion', 'above_prev_high', None, 5, None),
    'nr7_strong_trend': ('강한 추세 속 좁은 하루', "Quantified Strategies, '5 swing trading strategies' #4 (ADX + NR)", 'breakout', 'above_prev_high', None, 5, None),
    'donchian_20': ('20일 신고가 돌파', 'Turtle / Donchian channel breakout', 'breakout', 'time', None, 10, 2.0),
    'donchian_55': ('55일 신고가 돌파', 'Turtle / Donchian channel breakout', 'breakout', 'time', None, 10, 2.0),
    'trend_template': ('추세 템플릿 첫 통과', "Mark Minervini, 'Trade Like a Stock Market Wizard'", 'momentum', 'time', None, 10, 2.0),
    'vcp_breakout': ('변동성 수축 뒤 돌파(VCP)', 'Minervini VCP screeners on GitHub', 'breakout', 'time', None, 10, 2.0),
    'qullamaggie_breakout': ('급등 뒤 좁은 횡보 돌파', 'Qullamaggie breakout scanners (public blog rules)', 'breakout', 'time', None, 10, 2.0),
    'power_gap': ('거래량 실린 갭 상승', 'Episodic pivot / power earnings gap', 'momentum', 'time', None, 10, 2.0),
    'ema20_pullback': ('상승 추세 20일선 눌림', 'Trend pullback to EMA20 (swing-trading-strategies reference)', 'momentum', 'time', None, 7, 2.0),
    'adx_trend': ('ADX 추세 시작', 'ADX trend momentum (Wilder)', 'momentum', 'time', None, 10, 2.0),
    'ma_stack': ('이동평균 정배열', 'MA stack confluence (swing-trading-strategies reference)', 'momentum', 'time', None, 10, 2.0),
}


def rolling(a: np.ndarray, window: int, how: str) -> np.ndarray:
    frame = pd.DataFrame(a).rolling(window)
    return getattr(frame, how)().to_numpy()


def shifted(a: np.ndarray, k: int = 1) -> np.ndarray:
    out = np.full(a.shape, np.nan)
    out[k:] = a[:-k]
    return out


def conditions(ctx: se.Context) -> dict[str, np.ndarray]:
    """Signal-day condition of every setup, from the published wording."""
    f, p = ctx.features, ctx.panel
    o, h, l, c = (p[k].astype(np.float64) for k in ('open', 'high', 'low', 'close'))
    uptrend = f['dist_sma200'] > 0
    ibs = f['close_in_range']
    prior_high = lambda n: shifted(rolling(h, n, 'max'))
    weekday = np.array([pd.Timestamp(str(d)).dayofweek for d in ctx.dates])[:, None]
    template = (uptrend & (f['sma50_vs_sma200'] > 0) & (f['dist_sma50'] > 0) & (f['drawdown_252d'] >= -0.25)
                & (f['dist_low_252d'] >= 0.30) & (f['rank_ret60'] >= 0.75))
    with np.errstate(invalid='ignore'):
        out = {
            'connors_rsi2': uptrend & (f['rsi2'] < 10),
            'connors_double_7s': uptrend & (c <= rolling(c, 7, 'min')),
            'three_down_days': uptrend & (f['down_streak'] >= 3),
            'ibs_low': uptrend & (ibs < 0.2),
            'qs_band_ibs': (c < rolling(h, 10, 'max') - 2.5 * rolling(h - l, 25, 'mean')) & (ibs < 0.3),
            'five_day_low': c < shifted(rolling(l, 5, 'min')),
            'turnaround_tuesday': (weekday == 0) & (c < shifted(c)) & (shifted(c) < shifted(c, 2)),
            'bollinger_below_band': uptrend & (f['bb_pos'] < 0),
            'weekly_losers': f['rank_ret5'] <= 0.10,
            'new_high_low_ibs': (h > prior_high(10)) & (ibs < 0.15),
            'nr7_strong_trend': (f['adx14'] > 30) & (f['range_vs_min7'] <= 1.0) & uptrend,
            'donchian_20': uptrend & (c > prior_high(20)),
            'donchian_55': uptrend & (c > prior_high(55)),
            'trend_template': template,
            'vcp_breakout': template & (shifted(f['bb_width_rank120']) <= 0.25) & (c > prior_high(20)) & (f['rel_volume'] >= 1.4),
            'qullamaggie_breakout': (f['ret60'] >= 0.30) & (shifted(f['volatility_ratio']) <= 0.8) & (c > prior_high(10)) & (f['rel_volume'] >= 1.5),
            'power_gap': (f['gap_pct'] >= 0.05) & (f['rel_volume'] >= 2.0) & (c >= o),
            'ema20_pullback': (f['dist_sma50'] > 0) & (f['ema10_vs_ema50'] > 0) & (f['rank_ret60'] >= 0.8) & (np.abs(f['keltner_pos']) <= 0.5) & (f['body_atr'] > 0) & (f['ret5'] < 0),
            'adx_trend': (f['adx14'] > 25) & (f['adx14'] > shifted(f['adx14'], 5)) & (f['di_spread'] > 0) & (f['dist_sma50'] > 0),
            'ma_stack': (f['ema10_vs_ema50'] > 0) & (f['sma50_vs_sma200'] > 0) & (f['dist_ema10'] >= 0) & (f['dist_ema10'] <= 0.02) & (f['slope_sma120'] > 0),
        }
    return {k: np.nan_to_num(v, nan=0).astype(bool) for k, v in out.items()}


def fresh(mask: np.ndarray, quiet: int) -> np.ndarray:
    """Count a setup once: it must have been off for the whole previous holding window."""
    counts = np.cumsum(mask, axis=0, dtype=np.int32)
    before = np.zeros_like(counts); before[1:] = counts[:-1]
    start = np.zeros_like(counts); start[quiet + 1:] = counts[:-(quiet + 1)]
    return mask & ((before - start) == 0)


def simulate(ctx: se.Context, signals: np.ndarray, setup: str, extras: dict, at_close: bool = False) -> list[dict]:
    """at_close=True buys the signal day's close, as most of the sources do. Shown for reference only."""
    _, _, _, kind, parameter, last_day, stop_atr = SETUPS[setup]
    p = ctx.panel
    o, h, l, c, atr = (p[k] for k in ('open', 'high', 'low', 'close', 'atr'))
    commission = BACKTEST_COMMISSION_PCT / 100.0
    friction = (BACKTEST_SLIPPAGE_BPS + BACKTEST_HALF_SPREAD_BPS) / 10000.0
    rows = []
    for i, j in zip(*np.nonzero(signals)):
        e, final = i + 1, i + last_day
        if final >= len(c) or not np.isfinite(c[e:final + 1, j]).all() or not np.isfinite(o[e, j]) or not atr[i, j] > 0:
            continue
        entry = float(c[i, j]) if at_close else float(o[e, j])
        stop = entry - stop_atr * float(atr[i, j]) if stop_atr else None
        exit_day, exit_price = final, float(c[final, j])
        for d in range(e, final + 1):
            if stop is not None:
                if d > e and o[d, j] <= stop:
                    exit_day, exit_price = d, float(o[d, j]); break
                if l[d, j] <= stop:
                    exit_day, exit_price = d, stop; break
            done = ((kind == 'above_prev_high' and c[d, j] > h[d - 1, j]) or (kind == 'above_sma5' and c[d, j] > extras['sma5'][d, j])
                    or (kind == 'rsi2_above' and extras['rsi2'][d, j] > parameter) or (kind == 'close_7d_high' and c[d, j] >= extras['close_max7'][d, j]))
            if done:
                exit_day, exit_price = d, float(c[d, j]); break
        paid = entry * (1 + friction) * (1 + commission)
        received = exit_price * (1 - friction) * (1 - commission)
        rows.append({'day': int(i), 'col': int(j), 'entry_day': int(e), 'exit_day': int(exit_day), 'return_pct': (received / paid - 1) * 100.0})
    return rows


def summary(trades: list[dict]) -> dict:
    if not trades:
        return {'trades': 0}
    values = np.array([t['return_pct'] for t in trades])
    by_day: dict[int, list[float]] = {}
    for t in trades:
        by_day.setdefault(t['day'], []).append(t['return_pct'])
    daily = np.array([np.mean(v) for v in by_day.values()])
    spread = float(daily.std(ddof=1)) if len(daily) > 1 else 0.0
    return {
        'trades': len(trades), 'avg_return_pct': round(float(values.mean()), 3), 'win_rate_pct': round(float((values > 0).mean() * 100), 1),
        'big_loss_share_pct': round(float((values <= -10).mean() * 100), 1), 'signal_days': len(daily),
        't_stat': round(float(daily.mean() / spread * math.sqrt(len(daily))), 2) if spread > 0 else 0.0,
        'avg_days_held': round(float(np.mean([t['exit_day'] - t['entry_day'] + 1 for t in trades])), 1),
    }


def build(ctx: se.Context, ledger: dict) -> dict:
    extras = {'sma5': rolling(ctx.panel['close'].astype(np.float64), 5, 'mean'), 'rsi2': ctx.features['rsi2'],
              'close_max7': rolling(ctx.panel['close'].astype(np.float64), 7, 'max')}
    washout = se.footprint(base_signals(ctx, ledger))
    liquidity = ctx.features['dollar_volume_log']
    priority = lambda t: float(np.nan_to_num(liquidity[t['day'], t['col']], nan=-1e9))
    bar = se.required_t(len(SETUPS))
    rows_by = {name: ctx.rows(*span) for name, span in SEGMENTS.items()}
    results = {}
    for setup, mask in conditions(ctx).items():
        label, source, family, kind, parameter, last_day, stop_atr = SETUPS[setup]
        signals = fresh(mask & ctx.tradable, last_day)
        trades = simulate(ctx, signals, setup, extras)
        segments = {name: summary([t for t in trades if rows[t['day']]]) for name, rows in rows_by.items()}
        whole = summary(trades)
        positive_everywhere = all((segments[s].get('avg_return_pct') or -1) > 0 for s in SEGMENTS)
        results[setup] = {
            'label': label, 'source': source, 'family': family,
            'exit': {'kind': kind, 'parameter': parameter, 'last_day': last_day, 'stop_atr': stop_atr},
            'all_years': whole, 'segments': segments,
            'all_years_if_bought_at_signal_close': summary(simulate(ctx, signals, setup, extras, at_close=True)),
            'accounts': {name: account([t for t in trades if rows[t['day']]], priority, None, SLOTS) for name, rows in rows_by.items()},
            'overlap_with_washout_rules': round(se.overlap(se.footprint(signals), washout), 2),
            'positive_in_every_period': positive_everywhere,
            'holds_up': bool(positive_everywhere and whole.get('t_stat', 0) >= bar),
        }
    return {
        'version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'status': 'RESEARCH_ONLY', 'production_rules_mutated': False, 'frozen_rules_mutated': False,
        'universe': '신호일에 S&P 500 구성종목이던 회사(가격이 남아 있는 회사만)', 'execution': '다음 날 시가 매수, 각 전략의 청산 규칙, 비용 포함',
        'setups_tested': len(SETUPS), 't_required': round(bar, 2), 'slots': SLOTS,
        'results': results, 'holding_up': [k for k, v in results.items() if v['holds_up']],
        'limitations': [
            '공개된 설명을 일봉 지표로 옮긴 것이라 원작자의 재량 판단(차트 모양, 뉴스, 실적)은 빠져 있습니다.',
            '원래 규칙은 대개 신호일 종가에 삽니다. 여기서는 다음 날 시가에 사므로 원문 성적보다 낮게 나올 수 있습니다.',
            '실적 발표일 자료가 없어 실적 갭은 "거래량이 실린 큰 갭"으로 대신했습니다.',
            '가격이 남아 있지 않은 상장폐지 회사는 빠져 있습니다.',
        ],
    }


def main():
    ctx = se.Context(se.load_panel() if se.PANEL_CACHE.exists() else se.build_panel())
    report = build(ctx, json.loads(se.OUT.read_text(encoding='utf-8')))
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print('t needed', report['t_required'])
    for name, r in sorted(report['results'].items(), key=lambda kv: -kv[1]['all_years'].get('t_stat', -99)):
        w = r['all_years']
        k = r['all_years_if_bought_at_signal_close']
        print(f"{name:22s} n={w['trades']:6d} avg={w['avg_return_pct']:+.2f} (close {k['avg_return_pct']:+.2f} t{k['t_stat']:+.1f}) win={w['win_rate_pct']:.0f} t={w['t_stat']:+.2f} days={w['avg_days_held']} ov={r['overlap_with_washout_rules']}",
              '| seg avg', [r['segments'][s].get('avg_return_pct') for s in SEGMENTS], '| acct', [r['accounts'][s]['total_return_pct'] for s in SEGMENTS], '| OK' if r['holds_up'] else '')
    print('HOLDING UP', report['holding_up'])


if __name__ == '__main__':
    main()
