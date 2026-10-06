from smart_money_component_diagnostic import (
    percentile,
    filter_rows,
    summarize,
)


def test_percentile_is_distribution_only():
    assert percentile([10, 20, 30, 40], .75) == 32.5
    assert percentile([5], .75) == 5


def test_component_filter_uses_train_threshold_not_return():
    rows = [
        {"_smart_money_components": {"participation": 60, "absorption": 80, "liquidity": 100}, "_avg_dollar_volume_20d": 80_000_000},
        {"_smart_money_components": {"participation": 85, "absorption": 40, "liquidity": 100}, "_avg_dollar_volume_20d": 400_000_000},
    ]
    kept = filter_rows(rows, "participation_q75", {"participation": 75})
    assert len(kept) == 1
    assert kept[0]["_smart_money_components"]["participation"] == 85
    high_dollar = filter_rows(rows, "dollar_volume_q75", {"dollar_volume": 300_000_000})
    assert len(high_dollar) == 1
    floor = filter_rows(rows, "liquidity_floor_75m", {})
    assert len(floor) == 2


def fake_fold(base_ret, p_ret, a_ret, l_ret, joint_ret, strong_ret):
    def v(ret, delta=0, top=10):
        return {
            "return_pct": ret,
            "mdd_pct": -10.0,
            "trades": 20,
            "win_rate_pct": 50.0,
            "delta_return_vs_baseline_pct": delta,
            "delta_mdd_vs_baseline_pct": 0.0,
            "concentration": {
                "eligible_signals": 20,
                "top_symbol_share_pct": top,
                "top5_symbol_share_pct": 40,
                "symbol_hhi": .08,
                "mean_trade_pct": .5,
                "win_rate_pct": 50,
                "top_symbols": [],
            },
        }
    return {
        "fold": "x",
        "selected_quality_intensity": "normal",
        "variants": {
            "baseline": v(base_ret),
            "total_strong": v(strong_ret, strong_ret-base_ret),
            "participation_q75": v(p_ret, p_ret-base_ret),
            "absorption_q75": v(a_ret, a_ret-base_ret),
            "dollar_volume_q75": v(l_ret, l_ret-base_ret),
            "liquidity_floor_75m": v(base_ret, 0),
            "participation_absorption_joint": v(joint_ret, joint_ret-base_ret),
        },
    }


def test_summary_can_identify_repeating_component_without_promotion():
    folds = []
    for i in range(6):
        f = fake_fold(
            1.0,
            4.0 if i < 5 else 0.5,
            .8,
            .8,
            2.0,
            3.0,
        )
        f["fold"] = str(2021+i)
        folds.append(f)
    s = summarize(folds)
    assert s["dominant_component_variant"] == "participation_q75"
    assert s["variants"]["participation_q75"]["folds_beating_baseline"] == 5
    assert s["pattern"] == "component_repeats_development_only"


if __name__ == "__main__":
    test_percentile_is_distribution_only()
    test_component_filter_uses_train_threshold_not_return()
    test_summary_can_identify_repeating_component_without_promotion()
    print("smart money component diagnostic PASS")
