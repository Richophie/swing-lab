from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import pandas as pd
import yfinance as yf

from config import APP_VERSION, CORE_VERSION, S_THRESHOLD, SCAN_CANDIDATE_LIMIT
from market_data import load_us_universe, prefilter_symbols, market_snapshot, indicators, load_price_history
from strategy_engine import evaluate_strategies, trade_plan, public_s_signals, experimental_s_signals
from backtest_engine import run_backtest_on_frame
from stock_names import korean_name

OUT=Path(__file__).parent/'static'/'latest_scan.json'


def _extract_frame(bulk,symbol,count):
    try:
        d=bulk.copy() if count==1 else bulk[symbol].copy();return d.dropna(subset=['Open','High','Low','Close']).copy()
    except Exception:return pd.DataFrame()


def _dedupe_share_classes(rows):
    groups=[({'GOOG','GOOGL'},'GOOGL')];out=list(rows)
    for group,preferred in groups:
        present=[r for r in out if r['symbol'] in group]
        if len(present)>1:
            keep=next((r for r in present if r['symbol']==preferred),max(present,key=lambda r:r['score']));out=[r for r in out if r['symbol'] not in group or r is keep]
    return out


def _pf(value):
    try:return 9.0 if value is None else float(value)
    except Exception:return 0.0


def _first_20d_pullback_overlay(d):
    """High-conviction overlay, not a standalone strategy or hard gate.
    Requires strong MA alignment, a recent 52-week high, and today's first 20DMA touch
    after at least 20 sessions staying above the 20DMA.
    """
    if d is None or len(d)<260:return {'active':False,'reason':'표본 부족'}
    c=d['Close'].astype(float);low=d['Low'].astype(float)
    ma5=c.rolling(5).mean();ma20=c.rolling(20).mean();ma50=c.rolling(50).mean();ma200=c.rolling(200).mean()
    i=-1
    aligned=bool(ma5.iloc[i]>ma20.iloc[i]>ma50.iloc[i]>ma200.iloc[i])
    high52=d['High'].astype(float).rolling(252).max()
    recent_high=bool((d['High'].astype(float).tail(30)>=high52.tail(30)*.997).any())
    prev_low=low.iloc[-21:-1];prev_ma=ma20.iloc[-21:-1]
    stayed_above=bool(len(prev_low)==20 and (prev_low>prev_ma).all())
    touched=bool(low.iloc[-1]<=ma20.iloc[-1]*1.003 and c.iloc[-1]>=ma20.iloc[-1]*.985)
    active=aligned and recent_high and stayed_above and touched
    return {'active':active,'aligned':aligned,'recent_52w_high':recent_high,'first_touch':stayed_above and touched,'reason':'52주 신고가 주도주 · 정배열 · 20일선 첫 눌림' if active else '20일선 첫 눌림 교집합 미완성'}


def _elite_assessment(signal_score,plan,bt,overlay=False):
    full=bt.get('full_10y') or {};recent=bt.get('recent_2y') or {};ft=int(full.get('trades') or 0);rt=int(recent.get('trades') or 0);favg=float(full.get('avg_trade') or 0);ravg=float(recent.get('avg_trade') or 0);fpf=_pf(full.get('profit_factor'));rpf=_pf(recent.get('profit_factor'));fwin=float(full.get('win_rate') or 0);rwin=float(recent.get('win_rate') or 0);mdd=float(full.get('max_drawdown') or 0);rr=float(plan.get('risk_reward') or 0)
    # Aggregate-only gate: strategy tabs keep their raw S signals. Low sample is neutral, not a rejection.
    clearly_bad_history=ft>=5 and favg<=-.18 and fpf<.88
    clearly_bad_recent=rt>=4 and ravg<=-.40 and rpf<.78
    risk_bad=rr<1.15
    drawdown_bad=ft>=8 and mdd<-50
    passed=bool(not clearly_bad_history and not clearly_bad_recent and not risk_bad and not drawdown_bad)
    score=float(signal_score)
    if ft>=5:
        score+=max(-5,min(4,favg*5))+max(-4,min(3,(fpf-1)*6))
        if fwin>=50:score+=1
    if rt>=3:
        score+=max(-3,min(3,ravg*3))+max(-2,min(2,(rpf-1)*2.5))
        if rwin>=50:score+=1
    score+=max(-2,min(2,(rr-1.15)*2))
    if overlay:score+=6
    score=round(max(0,min(99,score)),1)
    reason=f"10년 {ft}회 · 평균 {favg:+.2f}% · PF {full.get('profit_factor') if full.get('profit_factor') is not None else '∞'} · 최근2년 {rt}회/{ravg:+.2f}% · 손익비 {rr:.2f}:1"
    if overlay:reason+=' · 20일선 첫 눌림 교집합 ✓'
    checks={'history_not_bad':not clearly_bad_history,'recent_not_bad':not clearly_bad_recent,'risk_reward':not risk_bad,'drawdown':not drawdown_bad,'first_20d_overlay':bool(overlay)}
    return {'elite_pass':passed,'elite_score':score,'selection_reason':reason,'checks':checks}


def scan_candidates(symbols,market,security_names):
    rows=[];failed=[];state=market.get('state')
    for start in range(0,len(symbols),100):
        chunk=symbols[start:start+100]
        try:bulk=yf.download(' '.join(chunk),period='14mo',interval='1d',auto_adjust=False,group_by='ticker',threads=True,progress=False,timeout=25)
        except Exception as exc:failed.extend({'symbol':s,'reason':str(exc)} for s in chunk);continue
        for symbol in chunk:
            try:
                d=_extract_frame(bulk,symbol,len(chunk))
                if len(d)<205:raise ValueError('일봉 205개 미만')
                ev=evaluate_strategies(d,state);pub=public_s_signals(ev);exp=experimental_s_signals(ev)
                if not pub and not exp:continue
                ind=indicators(d);tail=ind.tail(35);close_tail=d['Close'].tail(35);all_s=pub+exp;all_s.sort(key=lambda x:x['score'],reverse=True);best=all_s[0]
                row={'symbol':symbol,'name_ko':korean_name(symbol,security_names.get(symbol)),'security_name':security_names.get(symbol),'score':best['score'],'grade':'S','eligible':True,'strategy_id':best['id'],'strategy_name':best['name'],'strategy_reason':best['evidence'],'strategy_signals':[{'strategy_id':s['id'],'strategy_name':s['name'],'strategy_score':s['score'],'why':s['why'],'evidence':s['evidence'],'experimental':s['id']=='volatility_breakout','strict':bool(s.get('strict',False))} for s in all_s],'rsi':ev['metrics']['rsi'],'d120':ev['metrics']['d120'],'bb_pos':ev['metrics']['bb_pos'],'atr_pct':ev['metrics']['atr_pct'],'sparkline':[round(float(x),2) for x in close_tail.tolist()],'bb_high_spark':[None if pd.isna(x) else round(float(x),2) for x in tail['bb_high'].tolist()],'bb_low_spark':[None if pd.isna(x) else round(float(x),2) for x in tail['bb_low'].tolist()]};rows.append(row)
            except Exception as exc:failed.append({'symbol':symbol,'reason':str(exc)})
    return rows,failed


def enrich_plans(rows):
    out=[]
    for row in rows:
        try:
            d=load_price_history(row['symbol'],'10y');plans={};elite=[];overlay=_first_20d_pullback_overlay(d);row['first_20d_pullback']=overlay
            for sig in row['strategy_signals']:
                sid=sig['strategy_id'];plan=trade_plan(d,sid);plans[sid]=plan
                if sig.get('experimental'):
                    sig.update({'elite_pass':False,'elite_score':sig['strategy_score'],'selection_reason':'실험 전략 · 종합 추천에서 제외'});continue
                bt=run_backtest_on_frame(d,sid)
                overlay_bonus=bool(overlay['active'] and sid in {'confirmed_pullback','momentum_pullback'})
                assessment=_elite_assessment(sig['strategy_score'],plan,bt,overlay_bonus);sig.update(assessment);sig['backtest']=bt;sig['first_20d_overlay']=overlay_bonus
                if assessment['elite_pass']:elite.append(sig)
            row['strategy_trade_plans']=plans
            if elite:
                elite.sort(key=lambda s:s['elite_score'],reverse=True);best=elite[0];row.update({'strategy_id':best['strategy_id'],'strategy_name':best['strategy_name'],'strategy_reason':best['evidence'],'score':best['elite_score'],'elite_pass':True,'elite_score':best['elite_score'],'trade_plan':plans[best['strategy_id']]})
            else:row['elite_pass']=False;row['trade_plan']=plans.get(row['strategy_id'])
            out.append(row)
        except Exception as exc:row['detail_error']=str(exc);row['elite_pass']=False;out.append(row)
    return out


def main():
    universe=load_us_universe();names={x['symbol']:x['security_name'] for x in universe};symbols=prefilter_symbols(universe,SCAN_CANDIDATE_LIMIT);market=market_snapshot();rows,failed=scan_candidates(symbols,market,names);rows=_dedupe_share_classes(rows);rows=enrich_plans(rows);rows.sort(key=lambda r:(bool(r.get('elite_pass')),float(r.get('elite_score') or r.get('score') or 0)),reverse=True)
    public_count=sum(any(not s.get('experimental') and float(s.get('strategy_score',0))>=S_THRESHOLD for s in r['strategy_signals']) for r in rows);aggregate_count=sum(any(not s.get('experimental') and s.get('elite_pass') for s in r['strategy_signals']) for r in rows);experimental_count=sum(any(s.get('experimental') for s in r['strategy_signals']) for r in rows)
    payload={'status':'ready','version':APP_VERSION,'core_version':CORE_VERSION,'scanned_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'universe_count':len(universe),'candidate_count':len(symbols),'failed_count':len(failed),'failed':failed[:100],'market':market,'results':rows,'public_s_count':public_count,'aggregate_eligible_count':aggregate_count,'experimental_s_count':experimental_count,'display_filter':'strategy tabs show raw public S; aggregate applies conservative ranking and max 5','s_threshold':S_THRESHOLD,'elite_policy':'aggregate only: reject clearly poor backtest/risk, then rank; first-20DMA pullback is a bonus overlay'}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');print('saved',OUT,len(rows),'rows','public S',public_count,'aggregate eligible',aggregate_count)

if __name__=='__main__':main()
