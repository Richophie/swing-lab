from datetime import datetime, timezone
from pathlib import Path
import json
import yfinance as yf

from scanner_v6 import load_universe, prefilter
from app_v6 import historical_stats, market_live, history
from core_v4 import playbooks, _series, trade_plan_for

OUT = Path(__file__).parent / 'static' / 'latest_scan.json'
S_THRESHOLD = 85


def grade_for(ens):
    if not ens.get('recommend'):
        return 'B' if float(ens.get('ensemble_score', 0)) >= 58 else 'C'
    return 'S' if float(ens.get('ensemble_score', 0)) >= S_THRESHOLD else 'A'


def dedupe_share_classes(rows):
    prefer_groups = [({'GOOG','GOOGL'}, 'GOOGL')]
    out=list(rows)
    for group, preferred in prefer_groups:
        present=[r for r in out if r.get('symbol') in group]
        if len(present)>1:
            keep=next((r for r in present if r.get('symbol')==preferred), max(present,key=lambda r:r.get('score',0)))
            out=[r for r in out if r.get('symbol') not in group or r is keep]
    return out


def batch_score(symbols, market):
    results=[]; failed=0
    state=market.get('state') if isinstance(market,dict) else None
    for start in range(0,len(symbols),100):
        chunk=symbols[start:start+100]
        try:
            bulk=yf.download(' '.join(chunk),period='14mo',interval='1d',auto_adjust=False,group_by='ticker',threads=True,progress=False,timeout=25)
        except Exception:
            failed+=len(chunk); continue
        for symbol in chunk:
            try:
                d=bulk.copy() if len(chunk)==1 else bulk[symbol].copy(); d=d.dropna(subset=['Open','High','Low','Close'])
                if len(d)<205: failed+=1; continue
                ens=playbooks(d,state); best=ens['best_strategy']; grade=grade_for(ens); z=_series(d)
                s_signals=[{'strategy_id':q['id'],'strategy_name':q['name'],'strategy_score':q['score'],'why':q['why'],'evidence':q['evidence']} for q in ens['strategies'] if q.get('active') and float(q.get('score',0))>=S_THRESHOLD]
                results.append({'symbol':symbol,'score':ens['ensemble_score'],'grade':grade,'eligible':bool(ens.get('recommend')),'strategy_name':best['name'],'strategy_id':best['id'],'strategy_reason':ens['reason'],'strategy_agreement':ens['agreement'],'confidence':ens['confidence'],'strategy_signals':s_signals,'ensemble':ens,'rsi':round(float(z['rsi']),1),'d120':round((float(d['Close'].iloc[-1])/float(z['s120'])-1)*100,2),'bb_pos':round(float(z['bb'])*100,1),'sparkline':[round(float(x),2) for x in d['Close'].tail(35).tolist()]})
            except Exception:
                failed+=1
    results.sort(key=lambda x:(1 if x['grade']=='S' else 0,x['score']),reverse=True)
    return results,failed


def main():
    universe=load_universe(); candidates=prefilter(universe); market=market_live(); base,failed=batch_score(candidates,market)
    # Public recommendation feed now contains S only. A remains measurable as shadow statistics.
    s_rows=dedupe_share_classes([r for r in base if r.get('grade')=='S' and r.get('eligible') and r.get('strategy_signals')])
    shadow_a_count=sum(1 for r in base if r.get('grade')=='A' and r.get('eligible'))
    final=[]
    for r in s_rows[:60]:
        try:
            d=history(r['symbol'],'10y')
            # Default card uses the best S strategy. Each strategy tab can override presentation using strategy_signals.
            r['trade_plan']=trade_plan_for(d,r['strategy_id'])
            r['strategy_trade_plans']={sig['strategy_id']:trade_plan_for(d,sig['strategy_id']) for sig in r.get('strategy_signals',[])}
            r['history_stats']=historical_stats(d)
            final.append(r)
        except Exception as exc:
            r['detail_error']=str(exc); final.append(r)
    final.sort(key=lambda x:x.get('score',0),reverse=True)
    payload={'status':'ready','version':'13.0','core_version':'4.0','scanned_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'universe_count':len(universe),'candidate_count':len(candidates),'failed_count':failed,'market':market,'results':final,'shadow_a_count':shadow_a_count,'display_filter':'S only','strategy_tabs':['all','confirmed_pullback','rsi2_trend_reversion','momentum_pullback','volatility_breakout'],'ranking_note':'종합은 4개 전략의 S 신호를 통합해 최고 품질순으로 정렬하며 동일 종목은 1회만 노출합니다.','journal_quality':'experimental_until_strategy_backtests_pass'}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8'); print('saved',OUT,len(final))

if __name__=='__main__': main()
