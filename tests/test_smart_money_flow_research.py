import pandas as pd

from replay_pool_v2 import _smart_money_flow_features
from smart_money_flow import score_live_flow
from smart_money_flow_research import WATCH_SCORE, STRONG_SCORE, summarize


def frame(extra_future_volume=1000):
    idx=pd.date_range("2026-01-01",periods=30,freq="D")
    close=[100+i*.2 for i in range(30)]
    open_=[x-.1 for x in close]
    volume=[1_000_000+(i%5)*50_000 for i in range(30)]
    volume[26]=extra_future_volume
    return pd.DataFrame({"Open":open_,"Close":close,"Volume":volume},index=idx)


def test_signal_day_features_ignore_future_rows():
    a=_smart_money_flow_features(frame(1_000_000),25)
    b=_smart_money_flow_features(frame(100_000_000),25)
    assert a==b
    assert "relative_volume" in a
    assert "avg_dollar_volume_20d" in a


def test_fixed_thresholds_are_not_tuned():
    assert WATCH_SCORE==62.0
    assert STRONG_SCORE==75.0
    weak=score_live_flow({"relative_volume":1,"volume_5d_vs_20d":1,"reversal_volume":0,"up_down_volume_ratio":1,"avg_dollar_volume_20d":5_000_000})
    strong=score_live_flow({"relative_volume":2.5,"volume_5d_vs_20d":1.8,"reversal_volume":1.8,"up_down_volume_ratio":1.6,"avg_dollar_volume_20d":100_000_000})
    assert strong["score"]>weak["score"]


def test_summary_prefers_repeating_fixed_filter_without_auto_promotion():
    folds=[]
    for year in range(2021,2026):
        folds.append({
            "selected_quality_intensity":"loose",
            "variants":{
                "baseline":{"return_pct":2.0,"mdd_pct":-10.0,"trades":20,"win_rate_pct":55.0},
                "watch_plus":{"return_pct":3.0,"mdd_pct":-9.5,"trades":15,"win_rate_pct":58.0,"delta_return_vs_baseline_pct":1.0,"delta_mdd_vs_baseline_pct":0.5},
                "strong":{"return_pct":4.0,"mdd_pct":-9.0,"trades":12,"win_rate_pct":60.0,"delta_return_vs_baseline_pct":2.0,"delta_mdd_vs_baseline_pct":1.0},
            },
        })
    s=summarize(folds)
    assert s["pattern"]=="supported_development_only"
    assert s["best_fixed_filter"]=="strong"
    assert s["variants"]["strong"]["folds_beating_baseline"]==5


if __name__=="__main__":
    test_signal_day_features_ignore_future_rows()
    test_fixed_thresholds_are_not_tuned()
    test_summary_prefers_repeating_fixed_filter_without_auto_promotion()
    print("smart money research PASS")
