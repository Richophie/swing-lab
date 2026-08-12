from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json

ROOT=Path(__file__).parent
HISTORY=ROOT/'static'/'trade_history.json'
WALK=ROOT/'static'/'walkforward_report.json'
OUT=ROOT/'static'/'calibration_report.json'
MIN_CLOSED=20


def load(path,default):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception:return default


def main():
    journal=load(HISTORY,{'days':[]});walk=load(WALK,{})
    items=[x for d in journal.get('days',[]) for x in d.get('items',[]) if x.get('status_code') not in (None,'OPEN') and not x.get('experimental')]
    by={}
    for x in items:
        sid=x.get('strategy_id');b=by.setdefault(sid,[]);b.append(x)
    wf={x.get('strategy_id'):x for x in walk.get('strategies',[]) if x.get('strategy_id')}
    strategies=[]
    for sid,rows in sorted(by.items()):
        rets=[float(x['outcome_return_pct']) for x in rows if x.get('outcome_return_pct') is not None]
        n=len(rets);avg=sum(rets)/n if n else None;wins=sum(r>0 for r in rets)/n*100 if n else None
        action='WAIT';suggestion='실전 종료 표본이 20건 미만이라 파라미터를 조정하지 않습니다.'
        if n>=MIN_CLOSED:
            w=wf.get(sid,{})
            if avg is not None and avg<0:
                action='TIGHTEN';suggestion='실전 평균수익이 음수입니다. 손실 사례의 RSI/이평선거리/볼린저/ATR 구간을 분석해 하드필터를 좁힌 뒤 OOS 재검증하세요.'
            elif avg is not None and avg>0 and wins is not None and wins>=50 and w.get('passed') is True:
                action='HOLD';suggestion='실전과 OOS가 모두 양호합니다. 현재 파라미터를 유지하고 표본을 더 쌓으세요.'
            else:
                action='REVIEW';suggestion='성과가 혼재합니다. 한 번에 한 파라미터만 ±10~15% 범위에서 후보를 만들고 walk-forward로 비교하세요.'
        strategies.append({'strategy_id':sid,'closed_trades':n,'avg_return_pct':None if avg is None else round(avg,2),'win_rate_pct':None if wins is None else round(wins,1),'walkforward':wf.get(sid),'action':action,'suggestion':suggestion})
    if not strategies:
        strategies=[{'strategy_id':'all','closed_trades':0,'action':'WAIT','suggestion':'아직 종료된 실전 추천이 없습니다. 자동 미세조정을 시작하지 않습니다.'}]
    payload={'generated_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'mode':'suggest-only','minimum_closed_trades':MIN_CLOSED,'safety_rule':'실전 코드는 자동 수정하지 않음; 제안 -> OOS/walk-forward -> QA -> 수동 승격','strategies':strategies}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(payload,ensure_ascii=False))

if __name__=='__main__':main()
