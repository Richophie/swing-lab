from smart_money_flow import score_live_flow

def test_score_rises_with_abnormal_participation():
    base=score_live_flow({'relative_volume':1,'volume_5d_vs_20d':1,'reversal_volume':1,'up_down_volume_ratio':1,'avg_dollar_volume_20d':60_000_000})
    strong=score_live_flow({'relative_volume':2.2,'volume_5d_vs_20d':1.7,'reversal_volume':1.4,'up_down_volume_ratio':1.5,'avg_dollar_volume_20d':150_000_000})
    assert strong['score'] > base['score']
    assert strong['label'] == '큰돈 흔적 강함'

def test_never_claims_named_institution():
    x=score_live_flow({'relative_volume':3})
    assert '특정 기관' in x['interpretation']
    assert '단정하지 않습니다' in x['interpretation']

if __name__=='__main__':
    test_score_rises_with_abnormal_participation()
    test_never_claims_named_institution()
    print('smart money flow PASS')
