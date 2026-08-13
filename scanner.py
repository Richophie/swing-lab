from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import pandas as pd
import yfinance as yf

from config import APP_VERSION, CORE_VERSION, S_THRESHOLD, SCAN_CANDIDATE_LIMIT
from execution_quality import plan_execution_quality
from market_data import load_us_universe, prefilter_symbols, market_snapshot, indicators, load_price_history
from strategy_engine import evaluate_strategies, trade_plan, public_s_signals, experimental_s_signals
from backtest_engine import run_backtest_on_frame
from stock_names import korean_name

OUT=Path(__file__).parent/'static'/'latest_scan.json'
NY=ZoneInfo('America/New_York')


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


def _first_20d_pullback_overlay(d):
    if d is None or len(d)<260:return {'active':False,'reason':'표본 부족'}
    c=d['Close'].astype(float);low=d['Low'].astype(float);ma5=c.rolling(5).mean();ma20=c.rolling(20).mean();ma50=c.rolling(50).mean();ma200=c.rolling(200).mean();i=-1
    aligned=bool(ma5.iloc[i]>ma20.iloc[i]>ma50.iloc[i]>ma200.iloc[i]);high52=d['High'].astype(float).rolling(252).max();recent_high=bool((d['High'].astype(float).tail(30)>=high52.tail(30)*.997).any());prev_low=low.iloc[-21:-1];prev_ma=ma20.iloc[-21:-1];stayed_above=bool(len(prev_low)==20 and (prev_low>prev_ma).all());touched=bool(low.iloc[-1]<=ma20.iloc[-1]*1.003 and c.iloc[-1]>=ma20.iloc[-1]*.985);active=aligned and recent_high and stayed_above and touched
    return {'active':active,'aligned':aligned,'recent_52w_high':recent_high,'first_touch':stayed_above and touched,'reason':'52주 신고가 주도주 · 정배열 · 20일선 첫 눌림' if active else '20일선 첫 눌림 교집합 미완성'}


def _flow_quality(flow):
    flow=flow or {};rv=float(flow.get('relative_volume') or 1);v5=float(flow.get('volume_5d_vs_20d') or 1);rev=float(flow.get('reversal_volume') or 0);ud=flow.get('up_down_volume_ratio');ud=float(ud) if ud is not None else 1;dv=float(flow.get('avg_dollar_volume_20d') or 0)
    score=50
    if .65<=v5<=1.05:score+=10
    elif v5>1.6:score-=8
    if .8<=rv<=1.8:score+=8
    elif rv>2.8:score-=10
    if rev>=1.05:score+=12
    elif rev>0:score+=4
    if ud>=1.15:score+=10
    elif ud<.75:score-=8
    if dv>=50_000_000:score+=10
    elif dv<5_000_000:score-=15
    return max(0,min(100,score))


def _has_incomplete_daily_bar(d, now_utc=None):
    """True only when the last Yahoo daily row is today's still-forming US session."""
    if d is None or d.empty:return False
    now=now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:now=now.replace(tzinfo=timezone.utc)
    ny=now.astimezone(NY)
    try:last_day=pd.Timestamp(d.index[-1]).date()
    except Exception:return False
    return last_day==ny.date() and (ny.hour,ny.minute)<(16,5)


def _selection_flow(d,current_flow,market_state,now_utc=None):
    """Use completed-session flow for elite ranking while today's daily bar is incomplete.

    Price/RSI/BB remain live. Only the aggregate flow-quality layer is prevented from
    comparing a partial day's volume against completed full-day averages. The strict
    confirmed-pullback reversal-volume requirement remains a true live confirmation
    and is intentionally not relaxed here.
    """
    live=dict(current_flow or {})
    if not _has_incomplete_daily_bar(d,now_utc):return live,'current_completed_session'
    if len(d)<206:return live,'current_partial_fallback'
    try:
        previous=evaluate_strategies(d.iloc[:-1].copy(),market_state)
        completed=dict(previous.get('flow') or {})
        if completed:return completed,'previous_completed_session'
    except Exception:pass
    return live,'current_partial_fallback'


def _current_selection(signal_score,plan,flow,overlay=False,market_state=None,strategy_id=None):
    # Never make threshold decisions from a display-rounded 2-decimal RR. Rebuild
    # gross RR from the stored price levels at cent precision and also retain net RR
    # as a diagnostic. The live gate remains the existing gross >= 1.20 baseline.
    try:
        quality=plan_execution_quality(plan)
        rr=float(quality['gross_risk_reward']);net_rr=float(quality['net_risk_reward'])
    except Exception:
        rr=float(plan.get('risk_reward') or 0);net_rr=None
    plan['risk_reward_gate']=round(rr,4)
    plan['net_risk_reward']=None if net_rr is None else round(net_rr,2)
    plan['net_risk_reward_raw']=net_rr
    fq=_flow_quality(flow);score=float(signal_score)*.68+fq*.22+min(100,rr/3*100)*.10
    if overlay:score+=6
    if market_state=='중립':score-=2
    if market_state=='조심':score-=8
    entry_ok=bool(plan.get('entry_viable',True))
    stop_ok=float(plan.get('stop_atr_multiple') or 0)>=float(plan.get('min_stop_atr') or 1.5)
    if not entry_ok:score-=18
    if not stop_ok:score-=12
    hard_ok=rr>=1.20 and fq>=42 and market_state!='조심' and entry_ok and stop_ok
    score=round(max(0,min(99,score)),1)
    reason=f"현재 자리 {float(signal_score):.0f} · 수급 {fq:.0f} · 손익비 {rr:.2f}:1"
    if net_rr is not None:reason+=f" · 비용후 {net_rr:.2f}:1"
    if not entry_ok:reason+=f" · {plan.get('entry_status','진입구간 이탈')}"
    if not stop_ok:reason+=' · ATR 손절여유 부족'
    if overlay:reason+=' · 20일선 첫 눌림 교집합 ✓'
    return {'elite_pass':bool(hard_ok and score>=72),'elite_score':score,'selection_reason':reason,'flow_score':round(fq,1),'gross_risk_reward_gate':round(rr,4),'net_risk_reward':None if net_rr is None else round(net_rr,4),'checks':{'current_signal':float(signal_score)>=S_THRESHOLD,'flow':fq>=42,'risk_reward':rr>=1.20,'market':market_state!='조심','entry_viable':entry_ok,'atr_stop_margin':stop_ok,'first_20d_overlay':bool(overlay)}}


def scan_candidates(symbols,market,security_names,now_utc=None):
    rows=[];failed=[];state=market.get('state');scan_now=now_utc or datetime.now(timezone.utc)
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
                flow,flow_basis=_selection_flow(d,ev.get('flow') or {},state,scan_now)
                ind=indicators(d);tail=ind.tail(35);close_tail=d['Close'].tail(35);all_s=pub+exp;all_s.sort(key=lambda x:x['score'],reverse=True);best=all_s[0]
                row={'symbol':symbol,'name_ko':korean_name(symbol,security_names.get(symbol)),'security_name':security_names.get(symbol),'score':best['score'],'grade':'S','eligible':True,'strategy_id':best['id'],'strategy_name':best['name'],'strategy_reason':best['evidence'],'strategy_signals':[{'strategy_id':s['id'],'strategy_name':s['name'],'strategy_score':s['score'],'why':s['why'],'evidence':s['evidence'],'experimental':s['id']=='volatility_breakout','strict':bool(s.get('strict',False))} for s in all_s],'rsi':ev['metrics']['rsi'],'d120':ev['metrics']['d120'],'bb_pos':ev['metrics']['bb_pos'],'atr_pct':ev['metrics']['atr_pct'],'flow':flow,'live_flow':ev.get('flow') or {},'flow_basis':flow_basis,'sparkline':[round(float(x),2) for x in close_tail.tolist()],'bb_high_spark':[None if pd.isna(x) else round(float(x),2) for x in tail['bb_high'].tolist()],'bb_low_spark':[None if pd.isna(x) else round(float(x),2) for x in tail['bb_low'].tolist()]};rows.append(row)
            except Exception as exc:failed.append({'symbol':symbol,'reason':str(exc)})
    return rows,failed


def enrich_plans(rows,market_state=None):
    out=[]
    for row in rows:
        try:
            d=load_price_history(row['symbol'],'10y');plans={};elite=[];overlay=_first_20d_pullback_overlay(d);row['first_20d_pullback']=overlay
            for sig in row['strategy_signals']:
                sid=sig['strategy_id'];plan=trade_plan(d,sid);plans[sid]=plan
                if sig.get('experimental'):
                    sig.update({'elite_pass':False,'elite_score':sig['strategy_score'],'selection_reason':'실험 전략 · 엄선에서 제외'});continue
                overlay_bonus=bool(overlay['active'] and sid in {'confirmed_pullback','momentum_pullback'})
                assessment=_current_selection(sig['strategy_score'],plan,row.get('flow'),overlay_bonus,market_state,sid);sig.update(assessment);sig['first_20d_overlay']=overlay_bonus
                try:sig['backtest']=run_backtest_on_frame(d,sid)
                except Exception as exc:sig['backtest_error']=str(exc)
                if assessment['elite_pass']:elite.append(sig)
            row['strategy_trade_plans']=plans
            if elite:
                elite.sort(key=lambda s:s['elite_score'],reverse=True);best=elite[0];row.update({'strategy_id':best['strategy_id'],'strategy_name':best['strategy_name'],'strategy_reason':best['evidence'],'score':best['elite_score'],'elite_pass':True,'elite_score':best['elite_score'],'trade_plan':plans[best['strategy_id']]})
            else:row['elite_pass']=False;row['trade_plan']=plans.get(row['strategy_id'])
            out.append(row)
        except Exception as exc:row['detail_error']=str(exc);row['elite_pass']=False;out.append(row)
    return out


def main():
    scan_now=datetime.now(timezone.utc);universe=load_us_universe();names={x['symbol']:x['security_name'] for x in universe};symbols=prefilter_symbols(universe,SCAN_CANDIDATE_LIMIT);market=market_snapshot();rows,failed=scan_candidates(symbols,market,names,scan_now);rows=_dedupe_share_classes(rows);rows=enrich_plans(rows,market.get('state'));rows.sort(key=lambda r:(bool(r.get('elite_pass')),float(r.get('elite_score') or r.get('score') or 0)),reverse=True)
    public_count=sum(any(not s.get('experimental') and float(s.get('strategy_score',0))>=S_THRESHOLD for s in r['strategy_signals']) for r in rows);aggregate_count=sum(any(not s.get('experimental') and s.get('elite_pass') for s in r['strategy_signals']) for r in rows);experimental_count=sum(any(s.get('experimental') for s in r['strategy_signals']) for r in rows);completed_flow_count=sum(r.get('flow_basis')=='previous_completed_session' for r in rows)
    payload={'status':'ready','version':APP_VERSION,'core_version':CORE_VERSION,'scanned_at':scan_now.isoformat(timespec='seconds'),'universe_count':len(universe),'candidate_count':len(symbols),'failed_count':len(failed),'failed':failed[:100],'market':market,'results':rows,'public_s_count':public_count,'aggregate_eligible_count':aggregate_count,'experimental_s_count':experimental_count,'flow_completed_session_count':completed_flow_count,'flow_policy':'during an incomplete US daily bar, elite flow/liquidity scoring uses the previous completed session; live partial flow is stored separately','rr_policy':'gross RR >= 1.20 is evaluated from price-level precision; 2-decimal RR is display only; net RR is diagnostic only','display_filter':'strategy tabs show raw public S; aggregate ranks current signal + completed-session flow/liquidity + precise gross risk/reward + entry viability + ATR stop margin; no count cap','s_threshold':S_THRESHOLD,'elite_policy':'backtest is informational only; aggregate uses current setup, completed-session flow/liquidity during intraday scans, precise gross risk-reward, market regime, entry viability, ATR stop margin and first-20DMA overlay'}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');print('saved',OUT,len(rows),'rows','public S',public_count,'aggregate eligible',aggregate_count,'completed-session flow',completed_flow_count)

if __name__=='__main__':main()
