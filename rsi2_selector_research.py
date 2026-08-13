from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

import numpy as np
import pandas as pd

from audit_matrix import SYMBOLS
from backtest_engine import (
    _historical_market_state,
    exit_fill_for_bar,
    market_buy_fill,
    market_sell_fill,
    net_trade_return,
)
from config import BACKTEST_COMMISSION_PCT, BACKTEST_HALF_SPREAD_BPS, BACKTEST_SLIPPAGE_BPS, S_THRESHOLD
from market_data import indicators, load_price_history, wilder_rsi
from net_rr_research import pooled_stats
from scanner import _current_selection
from strategy_rules import ENTRY_GAP_ATR, ENTRY_GAP_PCT, MIN_STOP_ATR, canonical_signal_frame, trade_levels_from_row

OUT = Path('artifacts/rsi2_live_selector_research.json')
STRATEGY_ID = 'rsi2_trend_reversion'

VARIANTS = {
    'baseline_live_like': '현재 S+elite 재구성',
    'price_reversal': '종가>전일종가 또는 종가>시가',
    'macd_improving': 'MACD histogram > 전일',
    'rsi14_up1': 'RSI14 > 전일 RSI14',
    'rsi14_up3': 'RSI14 >= 3거래일 전',
    'price_and_macd': '가격반전 AND MACD 개선',
    'two_of_three': '가격반전/MACD개선/RSI14상승 중 2개 이상',
    'market_good_only': '시장상태 좋음만',
    'price_reversal_market_good': '가격반전 AND 시장 좋음',
    'close_above_120': '현재가가 120일선 위',
}


def _rsi2_strategy_score(active: pd.Series, ind: pd.DataFrame) -> pd.Series:
    close = ind['close'].astype(float)
    s50 = ind['sma50'].astype(float)
    s120 = ind['sma120'].astype(float)
    s200 = ind['sma200'].astype(float)
    rsi = ind['rsi'].astype(float)
    bb = ind['bb_pos'].astype(float)
    atrp = ind['atr14'].astype(float) / close
    rsi2 = wilder_rsi(close, 2)
    d120 = close / s120 - 1
    trend_ok = (close > s200) & (s50 >= s120)

    points = (
        np.select([rsi2 < 2, rsi2 < 3], [3, 2], default=0)
        + np.select([rsi < 42, rsi <= 50], [2, 1], default=0)
        + np.select([bb <= .25, bb <= .45], [2, 1], default=0)
        + (d120.abs() <= .06).astype(int)
        + trend_ok.astype(int)
        + (atrp <= .04).astype(int)
    )
    score = 55.0 + 40.0 * np.clip(points / 10.0, 0, 1)
    score = pd.Series(score, index=ind.index).round(1)
    score.loc[~active.fillna(False)] = np.minimum(score.loc[~active.fillna(False)], 69.0)
    return score


def _historical_flow_frame(d: pd.DataFrame, ind: pd.DataFrame) -> pd.DataFrame:
    c = d['Close'].astype(float)
    o = d['Open'].astype(float)
    v = d['Volume'].astype(float)
    vol20 = v.rolling(20).mean().replace(0, np.nan)
    vr = v / vol20
    vol5 = v.rolling(5).mean() / vol20
    price_reversal = (c > c.shift(1)) | (c > o)
    reversal_volume = vr.where(price_reversal, 0.0).fillna(0.0)
    up = c > c.shift(1)
    down = c < c.shift(1)
    up_mean = v.where(up).rolling(10, min_periods=1).mean()
    down_mean = v.where(down).rolling(10, min_periods=1).mean()
    up_down = up_mean / down_mean.replace(0, np.nan)
    dollar20 = (c * v).rolling(20).mean()
    return pd.DataFrame({
        'relative_volume': vr,
        'volume_5d_vs_20d': vol5,
        'reversal_volume': reversal_volume,
        'up_down_volume_ratio': up_down,
        'avg_dollar_volume_20d': dollar20,
    }, index=d.index)


def _plan_for_signal(frame: pd.DataFrame, i: int) -> dict:
    levels = trade_levels_from_row(frame.iloc[i], STRATEGY_ID)
    entry = float(levels['entry'])
    stop = float(levels['stop'])
    atr = float(levels['atr'])
    rr = (float(levels['target']) - entry) / (entry - stop)
    return {
        'entry_low': round(float(levels['buy_low']), 2),
        'entry_high': round(float(levels['buy_high']), 2),
        'target': round(float(levels['target']), 2),
        'stop': round(stop, 2),
        'risk_reward': round(rr, 2),
        'stop_atr_multiple': round((entry - stop) / atr, 2),
        'min_stop_atr': MIN_STOP_ATR,
        'entry_viable': True,
        'entry_status': '진입 적정',
        'atr': atr,
        'days_max': int(levels['days'][1]),
    }


def _variant_pass(name: str, features: dict) -> bool:
    if name == 'baseline_live_like': return True
    if name == 'price_reversal': return bool(features['price_reversal'])
    if name == 'macd_improving': return bool(features['macd_improving'])
    if name == 'rsi14_up1': return bool(features['rsi14_up1'])
    if name == 'rsi14_up3': return bool(features['rsi14_up3'])
    if name == 'price_and_macd': return bool(features['price_reversal'] and features['macd_improving'])
    if name == 'two_of_three': return int(features['price_reversal']) + int(features['macd_improving']) + int(features['rsi14_up1']) >= 2
    if name == 'market_good_only': return features['market_state'] == '좋음'
    if name == 'price_reversal_market_good': return bool(features['price_reversal'] and features['market_state'] == '좋음')
    if name == 'close_above_120': return bool(features['close_above_120'])
    raise ValueError(name)


def build_live_like_candidates(d: pd.DataFrame) -> tuple[pd.DataFrame, dict[int, dict]]:
    state = _historical_market_state(d.index)
    frame = canonical_signal_frame(d, state)
    ind = indicators(d)
    active = frame[STRATEGY_ID].fillna(False)
    score = _rsi2_strategy_score(active, ind)
    flows = _historical_flow_frame(d, ind)

    c = d['Close'].astype(float)
    o = d['Open'].astype(float)
    rsi = ind['rsi'].astype(float)
    mh = ind['macd_hist'].astype(float)
    s120 = ind['sma120'].astype(float)
    features_by_i = {}

    for i in range(205, len(d)-2):
        if not bool(active.iloc[i]) or float(score.iloc[i]) < S_THRESHOLD:
            continue
        flow_row = flows.iloc[i]
        flow = {k:(None if pd.isna(v) else float(v)) for k,v in flow_row.items()}
        plan = _plan_for_signal(frame, i)
        assessment = _current_selection(float(score.iloc[i]), plan, flow, overlay=False, market_state=str(state.iloc[i]), strategy_id=STRATEGY_ID)
        if not assessment['elite_pass']:
            continue
        features_by_i[i] = {
            'plan': plan,
            'strategy_score': float(score.iloc[i]),
            'elite_score': float(assessment['elite_score']),
            'flow_score': float(assessment['flow_score']),
            'gross_rr': float(assessment['gross_risk_reward_gate']),
            'net_rr': assessment.get('net_risk_reward'),
            'price_reversal': bool(c.iloc[i] > c.iloc[i-1] or c.iloc[i] > o.iloc[i]),
            'macd_improving': bool(mh.iloc[i] > mh.iloc[i-1]),
            'rsi14_up1': bool(rsi.iloc[i] > rsi.iloc[i-1]),
            'rsi14_up3': bool(rsi.iloc[i] >= rsi.iloc[i-3]),
            'market_state': str(state.iloc[i]),
            'close_above_120': bool(c.iloc[i] >= s120.iloc[i]),
        }
    return frame, features_by_i


def simulate_variant(d: pd.DataFrame, frame: pd.DataFrame, candidates: dict[int,dict], variant: str, *, symbol: str) -> list[dict]:
    commission = BACKTEST_COMMISSION_PCT / 100.0
    trades = []
    i = 205
    n = len(d)
    while i < n-2:
        info = candidates.get(i)
        if info is None or not _variant_pass(variant, info):
            i += 1
            continue
        plan = info['plan']
        entry_i = i+1
        raw_entry = float(d['Open'].iloc[entry_i])
        close_signal = float(frame['close'].iloc[i])
        gap_guard = max(ENTRY_GAP_ATR * float(plan['atr']), ENTRY_GAP_PCT * close_signal)
        if raw_entry < float(plan['entry_low']) - gap_guard or raw_entry > float(plan['entry_high']) + gap_guard:
            i += 1
            continue
        entry_fill = market_buy_fill(raw_entry, BACKTEST_SLIPPAGE_BPS, BACKTEST_HALF_SPREAD_BPS)
        target = float(plan['target']);stop = float(plan['stop'])
        if not stop < entry_fill < target:
            i += 1
            continue
        exit_i = min(entry_i + int(plan['days_max']), n-1)
        raw_exit = float(d['Close'].iloc[exit_i])
        exit_fill = market_sell_fill(raw_exit, BACKTEST_SLIPPAGE_BPS, BACKTEST_HALF_SPREAD_BPS)
        reason='기간종료'
        for j in range(entry_i, exit_i+1):
            bar=d.iloc[j]
            outcome=exit_fill_for_bar(bar['Open'],bar['High'],bar['Low'],target,stop,BACKTEST_SLIPPAGE_BPS,BACKTEST_HALF_SPREAD_BPS)
            if outcome is not None:
                exit_fill,reason,raw_exit=outcome;exit_i=j;break
        ret=net_trade_return(entry_fill,exit_fill,commission)
        trades.append({
            'symbol':symbol,'strategy_id':STRATEGY_ID,'variant':variant,
            'signal_i':i,'signal_date':d.index[i].strftime('%Y-%m-%d'),
            'entry_date':d.index[entry_i].strftime('%Y-%m-%d'),'exit_date':d.index[exit_i].strftime('%Y-%m-%d'),
            'ret':float(ret),'reason':reason,
            'gross_risk_reward':info['gross_rr'],'net_risk_reward':float(info.get('net_rr') or 0),
            'cost_rr_drag':float(info['gross_rr'])-float(info.get('net_rr') or 0),
            'strategy_score':info['strategy_score'],'elite_score':info['elite_score'],'flow_score':info['flow_score'],
            'market_state':info['market_state'],
        })
        i=exit_i+1
    return trades


def _bucket(trades, split_i, recent_i):
    return {
        'all':trades,
        'is_first_70pct':[t for t in trades if t['signal_i'] < split_i],
        'oos_last_30pct':[t for t in trades if t['signal_i'] >= split_i],
        'recent_2y':[t for t in trades if t['signal_i'] >= recent_i],
    }


def run_research() -> dict:
    pooled={name:defaultdict(list) for name in VARIANTS}
    symbol_results=[];errors=[];candidate_counts={}
    for symbol in SYMBOLS:
        try:d=load_price_history(symbol,'10y').dropna()
        except Exception as exc:errors.append({'symbol':symbol,'error':str(exc)});continue
        try:frame,candidates=build_live_like_candidates(d)
        except Exception as exc:errors.append({'symbol':symbol,'error':f'candidate build: {exc}'});continue
        candidate_counts[symbol]=len(candidates)
        split_i=max(205,int(len(d)*.70));recent_i=max(205,len(d)-504)
        row={'symbol':symbol,'live_like_candidates':len(candidates),'variants':{}}
        for name in VARIANTS:
            try:
                trades=simulate_variant(d,frame,candidates,name,symbol=symbol);grouped=_bucket(trades,split_i,recent_i)
                row['variants'][name]={k:pooled_stats(v) for k,v in grouped.items()}
                for k,v in grouped.items():pooled[name][k].extend(v)
            except Exception as exc:row['variants'][name]={'error':str(exc)}
        symbol_results.append(row)

    baseline={k:max(1,len(v)) for k,v in pooled['baseline_live_like'].items()}
    summary={}
    for name in VARIANTS:
        summary[name]={}
        for bucket in ('all','is_first_70pct','oos_last_30pct','recent_2y'):
            trades=pooled[name][bucket];s=pooled_stats(trades);s['coverage_vs_baseline_pct']=round(len(trades)/baseline.get(bucket,1)*100,2);summary[name][bucket]=s

    payload={
        'study':'RSI2 live-like selector and falling-knife confirmation variants',
        'status':'RESEARCH_ONLY',
        'symbols':SYMBOLS,
        'variants':VARIANTS,
        'live_like_reconstruction':[
            'canonical RSI2 strict signal',
            'strategy score >= S_THRESHOLD',
            'historical completed-day flow quality',
            'precise gross RR >= 1.20',
            'market != 조심',
            'elite score >= 72',
            'existing next-open gap guard and Backtest V2 execution costs',
        ],
        'oos_method':'Per symbol first 70% rows IS, last 30% OOS; recent ~504 trading rows reported separately.',
        'variant_summary':summary,
        'candidate_counts':candidate_counts,
        'symbol_results':symbol_results,
        'errors':errors,
        'scope_note':'Exploratory fixed-current-name universe. Multiple variants are compared, so no rule should be promoted solely from the best number in this report.',
    }
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'variant_summary':summary,'candidate_counts':candidate_counts,'errors':errors},ensure_ascii=False,indent=2))
    return payload


if __name__=='__main__':run_research()
