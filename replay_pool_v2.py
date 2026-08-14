from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from config import BACKTEST_COMMISSION_PCT, BACKTEST_HALF_SPREAD_BPS, BACKTEST_SLIPPAGE_BPS
from gap_guard_research import _signal_candidates
from market_data import indicators, load_price_history
from rsi2_broad_regime_research import MIN_HISTORY_ROWS, research_universe
from structural_stop_research import STRATEGIES, STRATEGY_NAMES

OUT = Path('static/replay_backtest_pool_v2.json')
TARGET_SYMBOLS = 80
PATH_BARS = 45

SMA_ID = 'sma200_20_squeeze'
BREAKOUT20_ID = 'breakout_20d'
VOLUME_BREAKOUT_ID = 'volume_breakout'
DONCHIAN55_ID = 'donchian_55'
LARRY_ID = 'larry_williams_vb'

EXPERIMENT_NAMES = {
    SMA_ID: 'SMA200·20 스퀴즈',
    BREAKOUT20_ID: '20일 신고가 돌파',
    VOLUME_BREAKOUT_ID: '거래량 동반 돌파',
    DONCHIAN55_ID: 'Donchian 55일 돌파',
    LARRY_ID: 'Larry Williams식 변동성 돌파',
}


def _num(v, default=None):
    try:
        x = float(v)
        return x if np.isfinite(x) else default
    except Exception:
        return default


def _clean_features(values: dict | None) -> dict:
    out = {}
    for key, value in (values or {}).items():
        x = _num(value)
        if x is not None:
            out[str(key)] = round(float(x), 6)
    return out


def _path(d: pd.DataFrame, ind: dict, entry_i: int, bars: int) -> list[list]:
    out = []
    s20, s200 = ind['sma20'], ind['sma200']
    low20 = d['Low'].astype(float).rolling(20).min().shift(1)
    for j in range(entry_i, min(len(d), entry_i + bars)):
        bar = d.iloc[j]
        out.append([
            d.index[j].strftime('%Y-%m-%d'),
            round(float(bar['Open']), 6), round(float(bar['High']), 6),
            round(float(bar['Low']), 6), round(float(bar['Close']), 6),
            None if pd.isna(s20.iloc[j]) else round(float(s20.iloc[j]), 6),
            None if pd.isna(s200.iloc[j]) else round(float(s200.iloc[j]), 6),
            None if pd.isna(low20.iloc[j]) else round(float(low20.iloc[j]), 6),
        ])
    return out


def _candidate(symbol, sid, name, d, ind, i, *, stop, target, max_hold,
               score=75.0, rr=1.5, exit_mode='price_plan', entry_mode='next_open',
               trigger=None, bars=None, quality_features=None):
    entry_i = i + 1
    if entry_i >= len(d):
        return None
    a = _num(ind['atr14'].iloc[i])
    close = _num(d['Close'].iloc[i])
    if not a or not close or a <= 0:
        return None
    path = _path(d, ind, entry_i, bars or max(PATH_BARS, max_hold + 1))
    if not path:
        return None
    payload = {
        'symbol': symbol, 'strategy_id': sid, 'strategy_name': name,
        'signal_date': d.index[i].strftime('%Y-%m-%d'),
        'entry_date': d.index[entry_i].strftime('%Y-%m-%d'),
        'signal_close': round(close, 6),
        'buy_low': round(close - .18 * a, 6),
        'buy_high': round(close + .18 * a, 6),
        'atr': round(a, 6),
        'target': None if target is None else round(float(target), 6),
        'stop': round(float(stop), 6),
        'max_hold': int(max_hold),
        'elite_score': round(float(score), 4),
        'net_risk_reward': round(float(rr), 6),
        'market_state': 'strategy_only',
        'quality_features': _clean_features(quality_features),
        'exit_mode': exit_mode, 'entry_mode': entry_mode, 'path': path,
    }
    if trigger is not None:
        payload['trigger'] = round(float(trigger), 6)
        payload['buy_low'] = payload['trigger']
        payload['buy_high'] = payload['trigger']
    return payload


def _sma_candidates(d: pd.DataFrame, ind: dict, symbol: str) -> list[dict]:
    c = d['Close'].astype(float); o = d['Open'].astype(float); l = d['Low'].astype(float); v = d['Volume'].astype(float)
    s20 = ind['sma20'].astype(float); s200 = ind['sma200'].astype(float); atr = ind['atr14'].astype(float)
    vol20 = v.rolling(20).mean().replace(0, np.nan)
    spread = (s20 / s200 - 1).abs()
    side = np.sign(s20 - s200)
    crosses = side.ne(side.shift(1)).rolling(30, min_periods=10).sum()
    strong = (c > o) & ((c - o) >= atr * .70)
    ma_top = pd.concat([s20, s200], axis=1).max(axis=1)
    clean = l > ma_top
    fresh = c.shift(1) <= pd.concat([s20.shift(1), s200.shift(1)], axis=1).max(axis=1) * 1.015
    vol_ratio = v / vol20
    liquid = vol_ratio >= .75
    signal = (c > s200) & (s200 > s200.shift(20)) & (spread <= .035) & (crosses <= 2) & strong & clean & fresh & liquid
    rows = []
    for i in np.flatnonzero(signal.fillna(False).to_numpy()):
        if i < 205 or i + 1 >= len(d): continue
        a = _num(atr.iloc[i]); close = _num(c.iloc[i]); ma20 = _num(s20.iloc[i]); ma200 = _num(s200.iloc[i])
        if not all(x is not None for x in (a, close, ma20, ma200)) or a <= 0: continue
        body_atr = max(0.0, (float(c.iloc[i]) - float(o.iloc[i])) / a)
        slope20 = _num(s200.iloc[i] / s200.iloc[i-20] - 1.0, 0.0)
        clearance = _num((l.iloc[i] - ma_top.iloc[i]) / a, 0.0)
        q = {
            'body_atr': body_atr,
            'ma_spread_pct': _num(spread.iloc[i], 0.0),
            'crosses_30': _num(crosses.iloc[i], 0.0),
            'volume_ratio': _num(vol_ratio.iloc[i], 0.0),
            'ma_clearance_atr': clearance,
            'sma200_slope_20d_pct': slope20,
            'atr_pct': a / close,
        }
        row = _candidate(symbol, SMA_ID, EXPERIMENT_NAMES[SMA_ID], d, ind, i,
                         stop=min(ma20, ma200) - .15*a, target=None, max_hold=20,
                         score=min(95.0, 72.0 + body_atr*8.0 + max(0.0, .035-float(spread.iloc[i]))*200),
                         rr=1.0 + min(1.0, body_atr/2.0), exit_mode='sma20_close',
                         quality_features=q)
        if row: rows.append(row)
    return rows


def _breakout_candidates(d: pd.DataFrame, ind: dict, symbol: str) -> list[dict]:
    c=d['Close'].astype(float); o=d['Open'].astype(float); h=d['High'].astype(float); l=d['Low'].astype(float); v=d['Volume'].astype(float)
    atr=ind['atr14'].astype(float); s200=ind['sma200'].astype(float)
    hh20=h.rolling(20).max().shift(1); hh55=h.rolling(55).max().shift(1)
    vol20=v.rolling(20).mean().shift(1).replace(0,np.nan)
    vol_ratio=v/vol20
    rng=(h-l).replace(0,np.nan); body=c-o
    close_pos=(c-l)/rng
    trend=(c>s200)&(s200>s200.shift(20))
    rows=[]
    sig20=trend&(c>hh20*1.001)&(vol_ratio>=1.15)&(body>=atr*.35)
    sigvol=trend&(c>hh20)&(vol_ratio>=1.8)&(body>=atr*.60)&(close_pos>=.75)
    sig55=trend&(c>hh55)
    for i in np.flatnonzero(sig20.fillna(False).to_numpy()):
        if i<205: continue
        a=_num(atr.iloc[i]); close=_num(c.iloc[i]); level=_num(hh20.iloc[i])
        if not a or not close or not level: continue
        q={
            'breakout_atr': (close-level)/a,
            'volume_ratio': _num(vol_ratio.iloc[i],0.0),
            'close_position': _num(close_pos.iloc[i],0.0),
            'body_atr': _num(body.iloc[i]/a,0.0),
            'sma200_slope_20d_pct': _num(s200.iloc[i]/s200.iloc[i-20]-1.0,0.0),
            'atr_pct': a/close,
        }
        row=_candidate(symbol,BREAKOUT20_ID,EXPERIMENT_NAMES[BREAKOUT20_ID],d,ind,i,
                       stop=min(close-1.2*a,level-.20*a),target=close+2.4*a,max_hold=10,
                       score=76+min(14,max(0,(float(vol_ratio.iloc[i])-1)*10)),rr=2.0,
                       quality_features=q)
        if row: rows.append(row)
    for i in np.flatnonzero(sigvol.fillna(False).to_numpy()):
        if i<205: continue
        a=_num(atr.iloc[i]); close=_num(c.iloc[i]); low=_num(l.iloc[i]); level=_num(hh20.iloc[i])
        if not a or not close or low is None or not level: continue
        q={
            'breakout_atr': (close-level)/a,
            'volume_ratio': _num(vol_ratio.iloc[i],0.0),
            'close_position': _num(close_pos.iloc[i],0.0),
            'body_atr': _num(body.iloc[i]/a,0.0),
            'sma200_slope_20d_pct': _num(s200.iloc[i]/s200.iloc[i-20]-1.0,0.0),
            'atr_pct': a/close,
        }
        row=_candidate(symbol,VOLUME_BREAKOUT_ID,EXPERIMENT_NAMES[VOLUME_BREAKOUT_ID],d,ind,i,
                       stop=low-.20*a,target=close+2.2*a,max_hold=8,
                       score=80+min(12,max(0,(float(vol_ratio.iloc[i])-1.8)*6)),rr=1.8,
                       quality_features=q)
        if row: rows.append(row)
    for i in np.flatnonzero(sig55.fillna(False).to_numpy()):
        if i<205: continue
        a=_num(atr.iloc[i]); close=_num(c.iloc[i]); level=_num(hh55.iloc[i])
        if not a or not close or not level: continue
        q={
            'breakout_atr': (close-level)/a,
            'volume_ratio': _num(vol_ratio.iloc[i],0.0),
            'close_position': _num(close_pos.iloc[i],0.0),
            'body_atr': _num(body.iloc[i]/a,0.0),
            'sma200_slope_20d_pct': _num(s200.iloc[i]/s200.iloc[i-20]-1.0,0.0),
            'distance_sma200_pct': _num(close/s200.iloc[i]-1.0,0.0),
            'atr_pct': a/close,
        }
        row=_candidate(symbol,DONCHIAN55_ID,EXPERIMENT_NAMES[DONCHIAN55_ID],d,ind,i,
                       stop=close-2.0*a,target=None,max_hold=40,score=78,rr=2.0,
                       exit_mode='donchian20_close',bars=45,quality_features=q)
        if row: rows.append(row)
    return rows


def _larry_candidates(d: pd.DataFrame, ind: dict, symbol: str, k: float=.50) -> list[dict]:
    c=d['Close'].astype(float); h=d['High'].astype(float); l=d['Low'].astype(float); o=d['Open'].astype(float); v=d['Volume'].astype(float)
    atr=ind['atr14'].astype(float); s20=ind['sma20'].astype(float); s200=ind['sma200'].astype(float)
    vol20=v.rolling(20).mean().replace(0,np.nan)
    rows=[]
    for i in range(205,len(d)-1):
        close=_num(c.iloc[i]); ma20=_num(s20.iloc[i]); ma200=_num(s200.iloc[i]); a=_num(atr.iloc[i])
        prev_range=_num(h.iloc[i]-l.iloc[i]); nxt_open=_num(o.iloc[i+1]); nxt_high=_num(h.iloc[i+1])
        if not all(x is not None for x in (close,ma20,ma200,a,prev_range,nxt_open,nxt_high)) or prev_range<=0 or a<=0: continue
        if not (close>ma20 and close>ma200 and ma200>_num(s200.iloc[i-20],ma200)): continue
        range_pct=prev_range/close
        vr=_num(v.iloc[i]/vol20.iloc[i],0)
        if not (.012<=range_pct<=.08 and vr>=.70): continue
        trigger=nxt_open+k*prev_range
        if nxt_high<trigger: continue
        stop=trigger-max(.75*prev_range,.75*a)
        row=_candidate(symbol,LARRY_ID,EXPERIMENT_NAMES[LARRY_ID],d,ind,i,
                       stop=stop,target=None,max_hold=1,score=76+min(14,range_pct*180),
                       rr=1.4,exit_mode='day_close',entry_mode='intraday_trigger',
                       trigger=trigger,bars=1,quality_features={
                           'prior_range_pct': range_pct,
                           'volume_ratio': vr,
                           'sma200_slope_20d_pct': _num(s200.iloc[i]/s200.iloc[i-20]-1.0,0.0),
                           'atr_pct': a/close,
                       })
        if row: rows.append(row)
    return rows


def build():
    requested, source = research_universe(); requested = requested[:TARGET_SYMBOLS]
    candidates, eligible, errors = [], [], []
    names = {**STRATEGY_NAMES, **EXPERIMENT_NAMES}
    all_strategies = [*STRATEGIES, *EXPERIMENT_NAMES.keys()]
    for symbol in requested:
        try:
            d = load_price_history(symbol, '10y').dropna()
            if len(d) < MIN_HISTORY_ROWS:
                raise ValueError(f'history rows {len(d)} < {MIN_HISTORY_ROWS}')
            ind = indicators(d)
            frame, by_strategy = _signal_candidates(d, symbol)
            eligible.append(symbol)
        except Exception as exc:
            errors.append({'symbol': symbol, 'error': str(exc)}); continue
        for sid in STRATEGIES:
            for signal_i, info in sorted(by_strategy[sid].items()):
                entry_i = int(signal_i) + 1
                if entry_i >= len(d): continue
                plan = info['plan']; path = _path(d, ind, entry_i, PATH_BARS)
                if not path: continue
                candidates.append({
                    'symbol': symbol, 'strategy_id': sid, 'strategy_name': names.get(sid, sid),
                    'signal_date': d.index[signal_i].strftime('%Y-%m-%d'), 'entry_date': d.index[entry_i].strftime('%Y-%m-%d'),
                    'signal_close': round(float(frame['close'].iloc[signal_i]), 6),
                    'buy_low': round(float(plan['buy_low']), 6), 'buy_high': round(float(plan['buy_high']), 6),
                    'atr': round(float(plan['atr']), 6), 'target': round(float(plan['target']), 6),
                    'stop': round(float(plan['stop']), 6), 'max_hold': int(plan['days'][1]),
                    'elite_score': round(float(info['elite_score']), 4), 'net_risk_reward': round(float(info['net_risk_reward']), 6),
                    'market_state': info['market_state'],
                    'quality_features': {
                        'elite_score': round(float(info['elite_score']), 4),
                        'net_risk_reward': round(float(info['net_risk_reward']), 6),
                    },
                    'exit_mode': 'price_plan', 'entry_mode': 'next_open', 'path': path,
                })
        candidates.extend(_sma_candidates(d, ind, symbol))
        candidates.extend(_breakout_candidates(d, ind, symbol))
        candidates.extend(_larry_candidates(d, ind, symbol))
    candidates.sort(key=lambda x:(x['entry_date'],-float(x.get('net_risk_reward') or 0),-float(x.get('elite_score') or 0),x['symbol'],x['strategy_id']))
    dates=[x['entry_date'] for x in candidates]
    payload={
        'version':4,'ready':True,'generated_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'selection_source':source,'requested_symbol_count':len(requested),'eligible_symbol_count':len(eligible),
        'available_start':min(dates) if dates else None,'available_end':max(dates) if dates else None,
        'strategies':all_strategies,'strategy_names':names,'candidate_count':len(candidates),'trade_count':len(candidates),
        'path_bars':PATH_BARS,'larry_k':.50,'quality_features_version':1,
        'costs':{'commission_pct_per_side':BACKTEST_COMMISSION_PCT,'slippage_bps':BACKTEST_SLIPPAGE_BPS,'half_spread_bps':BACKTEST_HALF_SPREAD_BPS},
        'errors':errors,'trades':candidates,
        'limitations':[
            '현재 유동성 종목을 과거로 되감는 연구용 후보풀이라 survivorship bias가 있습니다.',
            '같은 일봉에서 목표와 손절을 모두 터치하면 보수적으로 손절 우선 처리합니다.',
            'quality_features는 신호일 종가까지 알려진 데이터만 저장하며 미래 수익률은 포함하지 않습니다.',
            '실험전략은 백테스트 전용이며 생산 추천에는 자동 반영되지 않습니다.',
            'Larry Williams식 변동성 돌파는 공개된 변동성 확장 아이디어를 K=0.50으로 수치화한 연구형 구현이며 저자의 전체 시스템을 그대로 복제한다고 주장하지 않습니다.',
            'Larry 연구형은 일봉 OHLC만으로 장중 순서를 알 수 없는 경우 자동 최적화 랭킹에서 제외합니다.',
        ],
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print('eligible',len(eligible),'candidates',len(candidates),'errors',len(errors))


if __name__=='__main__':
    build()
