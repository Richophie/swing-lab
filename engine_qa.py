"""Swing Lab engine regression QA.
Run before promoting strategy changes to the public dashboard.
"""
from core_v4 import playbooks, trade_plan_for

EXPECTED = {
    'confirmed_pullback',
    'rsi2_trend_reversion',
    'momentum_pullback',
    'volatility_breakout',
}


def validate_symbol(df, market_state=None):
    ens = playbooks(df, market_state)
    strategies = ens['strategies']
    ids = {s['id'] for s in strategies}
    assert ids == EXPECTED, f'4전략 누락/중복: {ids}'
    assert len(strategies) == 4
    for s in strategies:
        assert 0 <= float(s['score']) <= 95, f"점수 포화: {s['id']}={s['score']}"
        assert isinstance(s['active'], bool)
    best = ens['best_strategy']
    if ens['recommend']:
        assert best['active'], '비활성 전략을 추천함'
        assert best['score'] >= 72, '추천 최소점수 위반'
    plan = trade_plan_for(df, best['id'])
    entry = (plan['buy_low'] + plan['buy_high']) / 2
    assert plan['buy_low'] <= plan['buy_high']
    assert plan['stop'] < entry < plan['target'], f"가격 순서 오류: {plan}"
    assert plan['days_min'] <= plan['days_max']
    assert plan['strategy_id'] == best['id']
    return {'best':best['id'],'score':best['score'],'active_count':ens['agreement'],'plan':plan}


def distribution_guard(rows):
    """Validate a completed scan. Prevent one broken playbook from flooding S grade."""
    if not rows:
        return {'ok':True,'note':'추천 없음'}
    s_rows=[r for r in rows if r.get('grade')=='S']
    assert not any(float(r.get('score',0)) > 95 for r in rows), '95점 초과 점수 발견'
    if len(s_rows) >= 8:
        counts={}
        for r in s_rows:
            sid=r.get('strategy_id','unknown'); counts[sid]=counts.get(sid,0)+1
        dominant=max(counts.values())/len(s_rows)
        assert dominant < .90, f'한 전략이 S의 {dominant:.0%} 독식: {counts}'
    symbols=[r.get('symbol') for r in rows]
    assert not ('GOOG' in symbols and 'GOOGL' in symbols), 'Alphabet 중복 노출'
    return {'ok':True,'s_count':len(s_rows)}
