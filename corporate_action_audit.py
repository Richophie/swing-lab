from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yfinance as yf

OUT = Path(__file__).parent / 'artifacts' / 'corporate_action_audit.json'
SYMBOLS = ('AAPL','NVDA','TSLA','AMZN','GOOGL')


def _safe_float(value):
    try:return float(value)
    except Exception:return None


def audit_symbol(symbol: str) -> dict:
    raw = yf.Ticker(symbol).history(period='10y', auto_adjust=False, actions=True, repair=True)
    adj = yf.Ticker(symbol).history(period='10y', auto_adjust=True, actions=True, repair=True)
    result = {'symbol':symbol,'rows_raw':len(raw),'rows_adjusted':len(adj),'splits':[]}
    if raw.empty:return {**result,'error':'raw history empty'}
    splits = raw.get('Stock Splits')
    if splits is None:return result
    for idx,value in splits[splits.fillna(0)!=0].items():
        pos = raw.index.get_loc(idx)
        if not isinstance(pos,int) or pos<1:continue
        prev_idx = raw.index[pos-1]
        prev_close = _safe_float(raw.loc[prev_idx,'Close'])
        split_close = _safe_float(raw.loc[idx,'Close'])
        adj_prev = _safe_float(adj.loc[prev_idx,'Close']) if prev_idx in adj.index else None
        adj_now = _safe_float(adj.loc[idx,'Close']) if idx in adj.index else None
        raw_jump = None if not prev_close or split_close is None else split_close/prev_close-1
        adj_jump = None if not adj_prev or adj_now is None else adj_now/adj_prev-1
        result['splits'].append({
            'date':pd.Timestamp(idx).date().isoformat(),
            'ratio':_safe_float(value),
            'raw_prev_close':prev_close,
            'raw_split_close':split_close,
            'raw_overnight_return_pct':None if raw_jump is None else round(raw_jump*100,4),
            'adjusted_overnight_return_pct':None if adj_jump is None else round(adj_jump*100,4),
        })
    return result


def main():
    rows=[]
    for symbol in SYMBOLS:
        try:rows.append(audit_symbol(symbol))
        except Exception as exc:rows.append({'symbol':symbol,'error':str(exc)})
    payload={
        'purpose':'Verify whether current raw Yahoo OHLC is continuous enough around stock splits before changing strategy/backtest price basis.',
        'note':'Informational audit only. Do not change canonical price basis from this file alone.',
        'symbols':rows,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(payload,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
