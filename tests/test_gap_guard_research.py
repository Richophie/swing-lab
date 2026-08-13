import gap_guard_research as research


def plan():
    return {'atr':2.0,'buy_low':99.0,'buy_high':101.0}


def test_current_guard_uses_larger_of_point75_atr_and_one_percent():
    down,up=research.guard_sides(plan(),100.0,'current')
    assert down==1.5 and up==1.5
    down2,up2=research.guard_sides({'atr':1.0,'buy_low':99,'buy_high':101},200.0,'current')
    assert down2==2.0 and up2==2.0


def test_atr_variants_ignore_one_percent_floor():
    p={'atr':1.0,'buy_low':99,'buy_high':101}
    assert research.guard_sides(p,200.0,'atr_0_25')==(0.25,0.25)
    assert research.guard_sides(p,200.0,'atr_0_50')==(0.5,0.5)
    assert research.guard_sides(p,200.0,'atr_0_75')==(0.75,0.75)


def test_directional_variants_change_only_one_side():
    p=plan()
    current=research.guard_sides(p,100.0,'current')
    d=research.guard_sides(p,100.0,'down_0_25_up_current')
    u=research.guard_sides(p,100.0,'down_current_up_0_25')
    assert d==(0.5,current[1])
    assert u==(current[0],0.5)


def test_open_relation_and_distance_are_measured_from_zone_edge():
    assert research.open_relation(100,99,101,2)==('inside_buy_zone',0.0)
    rel,dist=research.open_relation(98,99,101,2)
    assert rel=='below_buy_zone' and dist==0.5
    rel,dist=research.open_relation(102,99,101,2)
    assert rel=='above_buy_zone' and dist==0.5


def main():
    test_current_guard_uses_larger_of_point75_atr_and_one_percent()
    test_atr_variants_ignore_one_percent_floor()
    test_directional_variants_change_only_one_side()
    test_open_relation_and_distance_are_measured_from_zone_edge()
    print('gap guard research PASS')


if __name__=='__main__':main()
