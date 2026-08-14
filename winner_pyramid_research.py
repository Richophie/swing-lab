from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
from statistics import mean, median

import portfolio_candidate_capital_v2 as v2
import portfolio_walkforward_research as wf
import strategy_optimizer_runner as mtm
import strategy_optimizer_v2 as opt
import strategy_selection_research as selection

POOL = Path('static/replay_backtest_pool_v2.json')
OUT = Path('static/winner_pyramid_research.json')

BASE_RISK_PCT = .75
BASE_CAPACITY = 10
ADD_RISK_PCT = .25
ADD_MAX_SHARE = .15
TOTAL_SYMBOL_MAX_SHARE = .40
TRIGGER_R = 1.0

POLICIES = {
    'no_add': {
        'label':'기준 · 추가매수 없음','eligible':set(),'fresh_first':True,
    },
    'donchian_fresh_first': {
        'label':'Donchian만 +1R 불타기 · 새 후보 우선','eligible':{'donchian_55'},'fresh_first':True,
    },
    'trend_fresh_first': {
        'label':'SMA+Donchian +1R 불타기 · 새 후보 우선','eligible':{'sma200_20_squeeze','donchian_55'},'fresh_first':True,
    },
    'all_fresh_first': {
        'label':'세 전략 모두 +1R 불타기 · 새 후보 우선','eligible':{'confirmed_pullback','sma200_20_squeeze','donchian_55'},'fresh_first':True,
    },
    'trend_add_first': {
        'label':'SMA+Donchian +1R 불타기 · 추가매수 우선','eligible':{'sma200_20_squeeze','donchian_55'},'fresh_first':False,
    },
}


def _costs(pool: dict):
    costs=pool.get('costs') or {}
    commission=opt.num(costs.get('commission_pct_per_side'),.10)/100.0
    friction=(opt.num(costs.get('slippage_bps'),5.0)+opt.num(costs.get('half_spread_bps'),2.5))/10000.0
    return commission,friction


def build_addon(candidate: dict, base_row: dict, pool: dict) -> dict | None:
    path=candidate.get('path') or []
    if len(path)<2:
        return None
    commission,friction=_costs(pool)
    entry_mode=candidate.get('entry_mode') or 'next_open'
    raw_entry=opt.num(candidate.get('trigger')) if entry_mode=='intraday_trigger' else opt.num(path[0][1])
    stop=opt.num(candidate.get('stop'))
    if raw_entry<=0 or stop<=0 or raw_entry<=stop:
        return None
    one_r=raw_entry-stop
    trigger=raw_entry+TRIGGER_R*one_r
    base_end=str(base_row.get('end_date') or '')
    trigger_index=None
    for i,bar in enumerate(path[:-1]):
        day=str(bar[0])
        if base_end and day>=base_end:
            break
        close=opt.num(bar[4])
        if close>=trigger:
            trigger_index=i
            break
    if trigger_index is None:
        return None
    add_idx=trigger_index+1
    if add_idx>=len(path):
        return None
    first=path[add_idx]
    add_day=str(first[0])
    if base_end and add_day>base_end:
        return None
    raw_add=opt.num(first[1])
    add_stop=raw_entry
    entry_fill=raw_add*(1.0+friction)
    paid=entry_fill*(1.0+commission)
    if entry_fill<=add_stop:
        return None
    risk_fraction=max(.001,(entry_fill-add_stop)/entry_fill)
    exit_mode=candidate.get('exit_mode') or 'price_plan'
    target=opt.num(candidate.get('target'),float('nan'))
    raw_exit=opt.num(first[4])
    exit_day=add_day
    reason='기존 포지션 종료 동행'
    exit_idx=add_idx
    for i in range(add_idx,len(path)):
        bar=path[i]
        day=str(bar[0]);o,h,l,cl=map(opt.num,bar[1:5])
        if base_end and day>base_end:
            break
        s20=opt.num(bar[5],float('nan')) if len(bar)>5 else float('nan')
        dc20=opt.num(bar[7],float('nan')) if len(bar)>7 else float('nan')
        if o<=add_stop:
            raw_exit,exit_day,reason,exit_idx=o,day,'추가분 보호스탑 · 갭',i;break
        if l<=add_stop:
            raw_exit,exit_day,reason,exit_idx=add_stop,day,'추가분 보호스탑',i;break
        if math.isfinite(target) and target>entry_fill and (o>=target or h>=target):
            raw_exit,exit_day,reason,exit_idx=target,day,'기존 목표가 동행',i;break
        if exit_mode=='sma20_close' and math.isfinite(s20) and cl<s20:
            raw_exit,exit_day,reason,exit_idx=cl,day,'20일선 종가 이탈 동행',i;break
        if exit_mode=='donchian20_close' and math.isfinite(dc20) and cl<dc20:
            raw_exit,exit_day,reason,exit_idx=cl,day,'Donchian 20일 하단 이탈 동행',i;break
        if base_end and day==base_end:
            raw_exit,exit_day,reason,exit_idx=cl,day,'기존 포지션 종료 동행',i;break
        raw_exit,exit_day,exit_idx=cl,day,i
    received=raw_exit*(1.0-friction)*(1.0-commission)
    change=received/paid-1.0
    marks=[]
    for bar in path[add_idx:exit_idx+1]:
        close=opt.num(bar[4],float('nan'))
        if math.isfinite(close) and close>0:
            factor=close*(1.0-friction)*(1.0-commission)/paid
            marks.append((str(bar[0]),max(0.0,factor)))
    return {
        'start_date':add_day,'end_date':exit_day,'change':change,'risk_fraction':risk_fraction,
        'marks':marks,'reason':reason,'trigger_date':str(path[trigger_index][0]),
        'trigger_r':TRIGGER_R,'add_stop':add_stop,'raw_add_open':raw_add,
    }


def enriched_execute(candidate: dict, pool: dict):
    row=mtm.execute_candidate_mtm(candidate,pool,None,None)
    if not row:
        return None
    out=dict(row)
    out['_addon']=build_addon(candidate,row,pool)
    return out


def pyramid_portfolio(rows: list[dict], start: date, end: date, policy: dict) -> dict:
    selected=[dict(r) for r in rows if start<=opt.parse_day(r['start_date'])<=end and opt.parse_day(r['end_date'])<=end]
    selected.sort(key=lambda r:(r['start_date'],-opt.num(r.get('priority')),str(r.get('key') or '')))
    starts,ends,marks=defaultdict(list),defaultdict(list),defaultdict(list)
    add_starts,add_ends,add_marks=defaultdict(list),defaultdict(list),defaultdict(list)
    for seq,row in enumerate(selected):
        row['_seq']=seq
        starts[row['start_date']].append(row);ends[row['end_date']].append(row)
        for mark in row.get('marks') or ():
            if len(mark)>=2: marks[str(mark[0])].append((seq,opt.num(mark[1],1.0)))
        addon=row.get('_addon')
        if addon and row.get('strategy_id') in policy['eligible']:
            add_starts[addon['start_date']].append((seq,addon))
            add_ends[addon['end_date']].append((seq,addon))
            for mark in addon.get('marks') or ():
                if len(mark)>=2:add_marks[str(mark[0])].append((seq,opt.num(mark[1],1.0)))
    days=sorted(set(starts)|set(ends)|set(marks)|set(add_starts)|set(add_ends)|set(add_marks))
    cash=opt.INITIAL_CAPITAL;peak=cash;mdd=0.0
    bases={};addons={};open_symbols=set()
    base_changes=[];addon_changes=[]
    reject_cash=reject_capacity=reject_duplicate=reject_add_cash=0
    avg_cash=[];avg_exposure=[];open_samples=[]
    base_alloc=addon_alloc=0.0

    def exposure():
        return sum(p['size']*opt.num(p.get('mark'),1.0) for p in bases.values())+sum(p['size']*opt.num(p.get('mark'),1.0) for p in addons.values())
    def equity():return cash+exposure()

    def fresh(day):
        nonlocal cash,reject_cash,reject_capacity,reject_duplicate,base_alloc
        for row in sorted(starts.get(day,[]),key=lambda r:(-opt.num(r.get('priority')),str(r.get('key') or ''),r['_seq'])):
            symbol=row.get('symbol')
            if symbol and symbol in open_symbols:reject_duplicate+=1;continue
            if len(bases)>=BASE_CAPACITY:reject_capacity+=1;continue
            total=equity();rf=max(opt.num(row.get('risk_fraction')),.001)
            desired=min(total*(BASE_RISK_PCT/100.0)/rf,total*opt.MAX_SHARE)
            actual=min(cash,desired)
            if actual<1:
                reject_cash+=1;continue
            bases[row['_seq']]={'row':row,'size':actual,'mark':1.0}
            if symbol:open_symbols.add(symbol)
            cash-=actual;base_alloc+=actual;base_changes.append(opt.num(row.get('change')))

    def add(day):
        nonlocal cash,reject_add_cash,addon_alloc
        for seq,addon in add_starts.get(day,[]):
            base=bases.get(seq)
            if not base or seq in addons:continue
            total=equity();rf=max(opt.num(addon.get('risk_fraction')),.001)
            base_value=base['size']*opt.num(base.get('mark'),1.0)
            symbol_room=max(0.0,total*TOTAL_SYMBOL_MAX_SHARE-base_value)
            desired=min(total*(ADD_RISK_PCT/100.0)/rf,total*ADD_MAX_SHARE,symbol_room)
            actual=min(cash,desired)
            if actual<1:
                reject_add_cash+=1;continue
            addons[seq]={'data':addon,'size':actual,'mark':1.0}
            cash-=actual;addon_alloc+=actual;addon_changes.append(opt.num(addon.get('change')))

    for day in days:
        if policy['fresh_first']:
            fresh(day);add(day)
        else:
            add(day);fresh(day)
        for seq,addon in add_ends.get(day,[]):
            pos=addons.get(seq)
            if pos:
                cash+=pos['size']*(1.0+opt.num(addon.get('change')));del addons[seq]
        for row in sorted(ends.get(day,[]),key=lambda r:r['_seq']):
            pos=bases.get(row['_seq'])
            if not pos:continue
            cash+=pos['size']*(1.0+opt.num(row.get('change')))
            symbol=pos['row'].get('symbol')
            if symbol:open_symbols.discard(symbol)
            del bases[row['_seq']]
        for seq,factor in marks.get(day,()):
            if seq in bases:bases[seq]['mark']=factor
        for seq,factor in add_marks.get(day,()):
            if seq in addons:addons[seq]['mark']=factor
        total=equity();expo=exposure()
        if total>0:
            avg_cash.append(cash/total);avg_exposure.append(expo/total)
        open_samples.append(len(bases))
        peak=max(peak,total)
        if peak>0:mdd=min(mdd,total/peak-1.0)
    for pos in addons.values():cash+=pos['size']*(1.0+opt.num(pos['data'].get('change')))
    for pos in bases.values():cash+=pos['size']*(1.0+opt.num(pos['row'].get('change')))
    years=max((end-start).days/365.25,.25)
    all_changes=base_changes+addon_changes
    return {
        'ending':cash,'return':cash/opt.INITIAL_CAPITAL-1.0,
        'cagr':(cash/opt.INITIAL_CAPITAL)**(1.0/years)-1.0 if cash>0 else -1.0,
        'mdd':mdd,'trades':len(base_changes),'win_rate':sum(x>0 for x in base_changes)/len(base_changes) if base_changes else 0.0,
        'avg_trade':mean(base_changes) if base_changes else 0.0,'trades_per_year':len(base_changes)/years,
        'base_trades':len(base_changes),'addon_trades':len(addon_changes),
        'addon_win_rate':sum(x>0 for x in addon_changes)/len(addon_changes) if addon_changes else 0.0,
        'addon_avg_trade':mean(addon_changes) if addon_changes else 0.0,
        'reject_cash':reject_cash,'reject_capacity':reject_capacity,'reject_duplicate':reject_duplicate,'reject_add_cash':reject_add_cash,
        'base_allocated':base_alloc,'addon_allocated':addon_alloc,
        'avg_cash_pct':mean(avg_cash)*100.0 if avg_cash else 100.0,'avg_exposure_pct':mean(avg_exposure)*100.0 if avg_exposure else 0.0,
        'avg_open_positions':mean(open_samples) if open_samples else 0.0,
        'combined_win_rate':sum(x>0 for x in all_changes)/len(all_changes) if all_changes else 0.0,
    }


def compact(x:dict)->dict:
    base=wf.metric(x)
    base.update({
        'base_trades':x['base_trades'],'addon_trades':x['addon_trades'],
        'addon_win_rate_pct':round(x['addon_win_rate']*100,2),'addon_avg_trade_pct':round(x['addon_avg_trade']*100,3),
        'reject_cash':x['reject_cash'],'reject_capacity':x['reject_capacity'],'reject_add_cash':x['reject_add_cash'],
        'base_allocated':round(x['base_allocated'],2),'addon_allocated':round(x['addon_allocated'],2),
        'avg_cash_pct':round(x['avg_cash_pct'],1),'avg_exposure_pct':round(x['avg_exposure_pct'],1),'avg_open_positions':round(x['avg_open_positions'],2),
    })
    return base


def summarize(folds:list[dict],key:str)->dict:
    vals=[f['variants'][key] for f in folds];returns=[x['return_pct'] for x in vals];compound=1.0
    for x in returns:compound*=1+x/100.0
    ref=[f['variants']['no_add']['return_pct'] for f in folds]
    out={
        'stitched_test_return_pct':round((compound-1)*100,2),'positive_folds':sum(x>0 for x in returns),
        'median_test_return_pct':round(median(returns),2),'worst_test_return_pct':round(min(returns),2),
        'worst_mdd_pct':round(min(x['mdd_pct'] for x in vals),2),'total_base_trades':sum(x['base_trades'] for x in vals),
        'total_addon_trades':sum(x['addon_trades'] for x in vals),'mean_addon_win_rate_pct':round(mean(x['addon_win_rate_pct'] for x in vals),1),
        'mean_addon_avg_trade_pct':round(mean(x['addon_avg_trade_pct'] for x in vals),3),'total_base_cash_rejects':sum(x['reject_cash'] for x in vals),
        'total_add_cash_rejects':sum(x['reject_add_cash'] for x in vals),'mean_avg_cash_pct':round(mean(x['avg_cash_pct'] for x in vals),1),
    }
    if key!='no_add':
        out['folds_beating_reference']=sum(x>y+.01 for x,y in zip(returns,ref))
        out['mean_delta_vs_reference_pct']=round(mean(x-y for x,y in zip(returns,ref)),2)
    return out


def main():
    pool=json.loads(POOL.read_text(encoding='utf-8'))
    if not pool.get('ready') or int(pool.get('version') or 0)<4:raise SystemExit('Replay pool V4 required')
    candidates=list(pool.get('trades') or [])
    for c in candidates:c['_quality']=selection.quality_score(c)
    family=next(f for f in selection.FAMILIES if f['id']==v2.FAMILY_ID)
    folds=wf.folds_for(opt.parse_day(pool['available_start']),opt.parse_day(pool['available_end']))
    cache={}
    def executed(c):
        key=(c.get('symbol'),c.get('strategy_id'),c.get('signal_date'))
        if key not in cache:cache[key]=enriched_execute(c,pool)
        return cache[key]
    results=[]
    for fold in folds:
        _,rows=v2.fixed_pairs(family,candidates,fold,executed)
        variants={k:compact(pyramid_portfolio(rows,fold['test_start'],fold['test_end'],p)) for k,p in POLICIES.items()}
        results.append({'fold':fold['id'],'test_start':str(fold['test_start']),'test_end':str(fold['test_end']),'variants':variants})
    summary={k:summarize(results,k) for k in POLICIES}
    payload={
        'version':1,'ready':True,'generated_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'pool_generated_at':pool.get('generated_at'),
        'promotion_status':'development_only_winner_pyramid_not_fresh_holdout',
        'method':{
            'base_risk_pct':BASE_RISK_PCT,'base_capacity':BASE_CAPACITY,'addon_risk_pct':ADD_RISK_PCT,'trigger_r':TRIGGER_R,
            'addon_stop':'original base entry price','addon_entry':'next open after completed close reaches +1R',
            'no_averaging_down':True,'same_base_signal_and_exit_rules':True,'grid_search':False,'v1_v2_forward_untouched':True,
            'daily_ohlc_limit':'addon fill/stop/exit uses daily OHLC and conservative stop-first ordering; no intraday ordering claim',
        },
        'policies':{k:{**p,'eligible':sorted(p['eligible'])} for k,p in POLICIES.items()},'summary':summary,'folds':results,
        'notes':[
            'Additional buying is winner-only pyramiding; averaging down is intentionally excluded.',
            'Fresh-first variants protect portfolio breadth by letting new strategy candidates consume cash before addon orders on the same day.',
            'Historical data has already been inspected and retains current-universe survivorship bias. This is development evidence, not a fresh promotion holdout.',
            'Frozen Forward V1/V2 states are not read or mutated.',
        ],
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print('\nWinner pyramid research')
    for k,x in summary.items():
        print(k,'ret',x['stitched_test_return_pct'],'mdd',x['worst_mdd_pct'],'base',x['total_base_trades'],'adds',x['total_addon_trades'],'addavg',x['mean_addon_avg_trade_pct'],'beat',x.get('folds_beating_reference'))

if __name__=='__main__':main()
