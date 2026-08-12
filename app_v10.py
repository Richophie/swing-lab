from datetime import datetime, timezone
import json
import yfinance as yf
from flask import Response

from app_v9 import app, detail_v2, backtest_v2
from app_v6 import CACHE_FILE, market_live, trade_plan
from core_v3 import playbooks


def detail_v10(symbol):
    base=detail_v2(symbol)
    if isinstance(base,tuple): return base
    try:
        from app_v8 import load_df
        d=load_df(symbol.upper().strip(),'10y'); state=(base.get('market') or {}).get('state')
        ens=playbooks(d,state); base['ensemble']=ens; base['core_version']='3.0'
        base['note']=ens['reason']
        return base
    except Exception as e:
        base['ensemble_error']=str(e); return base


def live_refresh_v10():
    try:
        if not CACHE_FILE.exists(): return {'status':'pending','results':[]}
        base=json.loads(CACHE_FILE.read_text(encoding='utf-8')); rows=base.get('results') or []; symbols=[r.get('symbol') for r in rows if r.get('symbol')][:40]
        if not symbols:return base
        market=market_live(); state=market.get('state'); bulk=yf.download(' '.join(symbols),period='14mo',interval='1d',auto_adjust=False,group_by='ticker',threads=True,progress=False,timeout=20)
        old={r.get('symbol'):r for r in rows}; out=[]; failed=[]
        for s in symbols:
            try:
                d=bulk.copy() if len(symbols)==1 else bulk[s].copy(); d=d.dropna(subset=['Open','High','Low','Close'])
                ens=playbooks(d,state); best=ens['best_strategy']; p=trade_plan(d); prev=old.get(s,{})
                out.append({'symbol':s,'score':ens['ensemble_score'],'grade':'S' if ens['recommend'] and ens['ensemble_score']>=82 else 'A' if ens['recommend'] else 'B' if ens['ensemble_score']>=58 else 'C',
                            'eligible':ens['recommend'],'strategy_name':best['name'],'strategy_reason':ens['reason'],'strategy_agreement':ens['agreement'],'confidence':ens['confidence'],'ensemble':ens,
                            'rsi':prev.get('rsi'), 'd120':prev.get('d120'), 'bb_pos':prev.get('bb_pos'),
                            'sparkline':[round(float(x),2) for x in d['Close'].tail(35)],'trade_plan':p,'history_stats':prev.get('history_stats',{})})
            except Exception as e:
                failed.append({'symbol':s,'reason':str(e)})
        out.sort(key=lambda x:(1 if x['eligible'] else 0,x['score']),reverse=True)
        return {**base,'version':'10.0','core_version':'3.0','market':market,'results':out,'live_failed':failed,'live_refreshed_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'message':'4개 독립 스윙 전략을 각각 판정하고 오늘 가장 강한 전략으로 순위를 냈습니다.'}
    except Exception as e:
        return {'status':'error','error':str(e),'results':[]}

app.view_functions['detail']=detail_v10
if 'live_refresh' in app.view_functions: app.view_functions['live_refresh']=live_refresh_v10


def index_v10():
    html=open(app.static_folder+'/v8.html',encoding='utf-8').read()
    html=html.replace('오늘의 스윙자리 v8','오늘의 스윙자리 v10').replace('PRO LIVE v8.0','PRO LIVE v10.0').replace('TECH CHART + BACKTEST','MULTI-STRATEGY ROUTER')
    html=html.replace("<div style=\"margin-top:8px\"><b>${Math.round(r.score)}점 · ${gt(r.grade)}</b></div>","<div style=\"margin-top:8px\"><b>${Math.round(r.score)}점 · ${gt(r.grade)}</b></div><div class=\"mut\" style=\"margin-top:5px\">${r.strategy_name||''}${r.strategy_agreement!=null?' · 전략합의 '+r.strategy_agreement+'/4':''}</div><div class=\"e\">${r.strategy_reason||''}</div>")
    html=html.replace("$('detailMetrics').textContent=`RSI ${q.rsi} · 120일선 ${q.d120}% · 볼린저 ${q.bb_pos}% · ATR ${q.atr_pct}% · 손익비 ${p.risk_reward}:1`;", "let en=d.ensemble; $('detailMetrics').innerHTML=`RSI ${q.rsi} · 120일선 ${q.d120}% · 볼린저 ${q.bb_pos}% · ATR ${q.atr_pct}% · 손익비 ${p.risk_reward}:1`+(en?`<br><br><b>오늘 최우선 전략: ${en.best_strategy.name}</b><br>${en.reason}<br>독립 전략 합의 ${en.agreement}/4 · 신뢰 ${en.confidence}`:'');")
    html=html.replace('현재 엔진 규칙을 과거 봉에 그대로 적용합니다.','현재 코어 전략은 동일 규칙으로 백테스트합니다. 멀티전략 각각의 OOS 검증은 별도 검증표로 확장합니다.')
    return Response(html,mimetype='text/html')
app.view_functions['index']=index_v10

@app.route('/api/version-v10')
def version_v10():
    return {'version':'10.0','core':'3.0','architecture':'independent playbooks + regime routing, not indicator soup','playbooks':['confirmed_pullback','rsi2_trend_reversion','momentum_pullback','volatility_breakout']}
