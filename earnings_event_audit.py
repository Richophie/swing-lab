from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd
import yfinance as yf

from rsi2_broad_regime_research import research_universe

OUT=Path('artifacts/earnings_event_audit.json')
# Cross-source confirmation pass: a representative liquid subset is enough to
# verify that the two yfinance surfaces agree before any production feature is added.
TARGET_SYMBOLS=20


def _date_text(value):
    try:
        ts=pd.Timestamp(value)
        if ts.tzinfo is not None:ts=ts.tz_convert('UTC').tz_localize(None)
        return ts.date().isoformat()
    except Exception:return None


def _future_from_earnings_dates(ticker,today):
    try:
        d=ticker.get_earnings_dates(limit=12)
        if d is None or d.empty:return None,'empty'
        dates=[]
        for idx in d.index:
            text=_date_text(idx)
            if text and text>=today:dates.append(text)
        return (min(dates) if dates else None),'ok'
    except Exception as exc:return None,f'error:{exc}'


def _future_from_calendar(ticker,today):
    try:
        cal=ticker.calendar
        if not cal:return None,'empty'
        value=None
        if isinstance(cal,dict):
            value=cal.get('Earnings Date') or cal.get('EarningsDate')
        elif hasattr(cal,'loc'):
            for key in ('Earnings Date','EarningsDate'):
                try:
                    value=cal.loc[key].iloc[0] if hasattr(cal.loc[key],'iloc') else cal.loc[key]
                    break
                except Exception:pass
        vals=value if isinstance(value,(list,tuple)) else [value]
        dates=[]
        for v in vals:
            text=_date_text(v)
            if text and text>=today:dates.append(text)
        return (min(dates) if dates else None),'ok' if dates else 'empty'
    except Exception as exc:return None,f'error:{exc}'


def audit_symbol(symbol,today):
    t=yf.Ticker(symbol)
    earnings_date,earnings_status=_future_from_earnings_dates(t,today)
    calendar_date,calendar_status=_future_from_calendar(t,today)
    chosen=earnings_date or calendar_date
    agreement=None
    day_diff=None
    if earnings_date and calendar_date:
        a=pd.Timestamp(earnings_date);b=pd.Timestamp(calendar_date);day_diff=abs((a-b).days);agreement=day_diff<=1
    days_until=None
    if chosen:days_until=(pd.Timestamp(chosen)-pd.Timestamp(today)).days
    return {
        'symbol':symbol,'get_earnings_dates':earnings_date,'get_earnings_dates_status':earnings_status,
        'calendar':calendar_date,'calendar_status':calendar_status,'chosen_next_earnings':chosen,
        'days_until':days_until,'sources_agree_within_1d':agreement,'source_day_diff':day_diff,
    }


def main():
    symbols,source=research_universe();symbols=symbols[:TARGET_SYMBOLS];today=datetime.now(timezone.utc).date().isoformat();rows=[]
    for symbol in symbols:
        try:rows.append(audit_symbol(symbol,today))
        except Exception as exc:rows.append({'symbol':symbol,'error':str(exc)})
    usable=[r for r in rows if r.get('chosen_next_earnings')]
    dual=[r for r in rows if r.get('get_earnings_dates') and r.get('calendar')]
    agree=[r for r in dual if r.get('sources_agree_within_1d')]
    payload={
        'study':'Upcoming earnings-date data availability and cross-source agreement inside yfinance',
        'status':'RESEARCH_ONLY_DATA_QUALITY_CONFIRMATION','as_of':today,'selection_source':source,
        'requested_symbols':len(symbols),'symbols_with_any_upcoming_date':len(usable),
        'coverage_pct':round(len(usable)/len(symbols)*100,2) if symbols else 0.0,
        'symbols_with_both_sources':len(dual),'both_sources_agree_within_1d':len(agree),
        'agreement_pct':round(len(agree)/len(dual)*100,2) if dual else None,
        'upcoming_within_10d':sum(r.get('days_until') is not None and 0<=r['days_until']<=10 for r in rows),
        'upcoming_within_30d':sum(r.get('days_until') is not None and 0<=r['days_until']<=30 for r in rows),
        'rows':rows,
        'decision_rule':'Use as an informational event-risk flag only if coverage is high and source disagreement is manageable. Do not hard-exclude trades from a single unverified earnings date feed.',
        'production_note':'If promoted, query only elite/confirmed candidates and cache results; never synchronously query the full universe during page render.',
    }
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(payload,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
