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
        return {**base,'version':'10.2','core_version':'3.0','market':market,'results':out,'live_failed':failed,'live_refreshed_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'message':'4개 독립 스윙 전략을 각각 판정하고 오늘 가장 강한 전략으로 순위를 냈습니다.'}
    except Exception as e:
        return {'status':'error','error':str(e),'results':[]}

app.view_functions['detail']=detail_v10
if 'live_refresh' in app.view_functions: app.view_functions['live_refresh']=live_refresh_v10


def index_v10():
    html=open(app.static_folder+'/v8.html',encoding='utf-8').read()
    html=html.replace('오늘의 스윙자리 v8','오늘의 스윙자리 v10').replace('PRO LIVE v8.0','PRO LIVE v10.2').replace('TECH CHART + BACKTEST','MULTI-STRATEGY ROUTER')

    # Keep the original recommendation cards/ranking/grade presentation.
    # Add only an easy-to-read explanation block inside each existing card.
    html=html.replace(
        "<div style=\"margin-top:8px\"><b>${Math.round(r.score)}점 · ${gt(r.grade)}</b></div>",
        "<div style=\"margin-top:8px\"><b>${Math.round(r.score)}점 · ${gt(r.grade)}</b></div><div class=\"result\" style=\"margin-top:8px;padding:9px 10px\"><b>추천 방식 · ${r.strategy_name||'분석 중'}</b><br><span class=\"mut\">${friendlyReason(r)}</span></div>"
    )

    # Detail: replace engine jargon with a service-style interpretation.
    html=html.replace(
        "$('detailMetrics').textContent=`RSI ${q.rsi} · 120일선 ${q.d120}% · 볼린저 ${q.bb_pos}% · ATR ${q.atr_pct}% · 손익비 ${p.risk_reward}:1`;",
        "let en=d.ensemble; $('detailMetrics').innerHTML=`<b>지금 자리를 쉽게 보면</b><br>• RSI ${q.rsi} → ${rsiText(q.rsi)}<br>• 120일선 ${q.d120}% → ${maText(q.d120)}<br>• 볼린저 ${q.bb_pos}% → ${bbText(q.bb_pos)}<br>• 하루 변동성 약 ${q.atr_pct}% · 손익비 1:${p.risk_reward}`+(en?`<br><br><b>왜 추천했나요?</b><br><b>${en.best_strategy.name}</b> 방식이 지금 이 종목에 가장 잘 맞습니다.<br>${friendlyEnsemble(en)}<br><span class=\"mut\">4개 전략 중 ${en.agreement}개가 현재 매수 신호 · 확신도 ${en.confidence}</span>`:'');"
    )

    # KRW inputs: formatted text inputs; calculations strip commas internally.
    html=html.replace('id="capital" type="number" value="3000000" step="100000"','id="capital" type="text" inputmode="numeric" value="3,000,000"')
    html=html.replace('id="want" type="number" value="50000" step="10000"','id="want" type="text" inputmode="numeric" value="50,000"')
    html=html.replace("cap=+$('capital').value||0,want=+$('want').value||0", "cap=numInput($('capital').value),want=numInput($('want').value)")
    html=html.replace("$('capital').oninput=calc;$('want').oninput=calc;", "$('capital').oninput=e=>{formatMoneyInput(e.target);calc()};$('want').oninput=e=>{formatMoneyInput(e.target);calc()};")

    html=html.replace(
        "<script>const $=id=>document.getElementById(id);",
        "<script>const $=id=>document.getElementById(id);const numInput=v=>Number(String(v||'').replace(/[^0-9]/g,''))||0;function formatMoneyInput(el){let n=String(el.value||'').replace(/[^0-9]/g,'');el.value=n?Number(n).toLocaleString('ko-KR'):''}function rsiText(v){v=Number(v);return v<30?'많이 눌린 구간':v<40?'꽤 눌려 반등을 볼 만한 구간':v<55?'과열도 과매도도 아닌 중간 구간':'이미 많이 오른 편'}function maText(v){v=Number(v);let a=Math.abs(v);return a<1?'120일선에 거의 닿아 있는 자리':v<0?'120일선 아래라 지지 회복 확인이 필요한 자리':'120일선 위에서 지지를 시험하는 자리'}function bbText(v){v=Number(v);return v<15?'볼린저 하단에 아주 가까운 눌림':v<35?'볼린저 하단 쪽의 눌림':v<70?'밴드 중간 구간':'볼린저 상단 쪽이라 추격 주의'}function friendlyEnsemble(en){let b=en.best_strategy||{};if(b.id==='confirmed_pullback')return '가격이 충분히 눌린 뒤 실제 반전 신호가 나타나기 시작한 자리예요.';if(b.id==='rsi2_trend_reversion')return '큰 상승추세는 살아 있는데 단기적으로 너무 빠르게 빠진 반등 후보예요.';if(b.id==='momentum_pullback')return '원래 강했던 종목이 잠깐 쉬었다가 다시 힘을 받는 흐름이에요.';if(b.id==='volatility_breakout')return '움직임이 조용해진 뒤 고점을 뚫기 시작한 돌파형 자리예요.';return en.reason||''}function friendlyReason(r){let en=r.ensemble,b=en&&en.best_strategy;if(b){let t=friendlyEnsemble(en);return t+' '+(r.strategy_agreement>=2?'다른 전략도 일부 같은 방향을 보고 있어요.':'현재는 이 전략 신호가 가장 뚜렷해요.')}return r.strategy_reason||'현재 자리를 분석했습니다.'}"
    )

    html=html.replace('현재 엔진 규칙을 과거 봉에 그대로 적용합니다.','현재 코어 전략은 동일 규칙으로 백테스트합니다. 멀티전략 각각의 OOS 검증은 별도 검증표로 확장합니다.')
    return Response(html,mimetype='text/html')
app.view_functions['index']=index_v10

@app.route('/api/version-v10')
def version_v10():
    return {'version':'10.2','core':'3.0','architecture':'independent playbooks + regime routing, not indicator soup','playbooks':['confirmed_pullback','rsi2_trend_reversion','momentum_pullback','volatility_breakout'],'ux':['original recommendation cards preserved','plain-language strategy explanation on each dashboard card','formatted KRW inputs']}
