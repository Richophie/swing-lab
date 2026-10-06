from auto_experiment_queue import generate, merge_previous
from auto_experiment_runner import (
    adjusted_rows_by_state_profile,
    evidence_flow_selection,
    evidence_priority_ranker,
    evidence_regime_gate,
    evidence_smart_money_selection,
)


def fake_sources():
    wf = {
        "generated_at": "2026-08-15T00:00:00+00:00",
        "families": [{
            "id": "f1", "name": "Family 1", "strategies": ["s1"],
            "summary": {"grade": "C", "positive_folds": 3, "fold_count": 6, "positive_fold_ratio": .5}
        }]
    }
    vol = {
        "generated_at": "2026-08-15T00:01:00+00:00",
        "families": [{
            "id": "f1",
            "summary": {
                "states": {
                    "green_low_vol": {
                        "stitched_state_sleeve_return_pct": -10,
                        "positive_avg_trade_folds": 2,
                        "folds_with_signals": 5,
                    },
                    "green_mid_vol": {
                        "stitched_state_sleeve_return_pct": 5,
                        "positive_avg_trade_folds": 3,
                        "folds_with_signals": 5,
                    },
                    "green_high_vol": {
                        "stitched_state_sleeve_return_pct": 35,
                        "positive_avg_trade_folds": 5,
                        "folds_with_signals": 6,
                    },
                }
            }
        }]
    }
    regime = {
        "generated_at": "2026-08-15T00:02:00+00:00",
        "families": [{
            "id": "f1", "name": "Family 1", "strategies": ["s1"],
            "summary": {
                "grade": "B", "fold_count": 6, "gate_helped_folds": 4,
                "mean_gate_delta_return_pct": 1.2,
                "stitched_gated_return_pct": 14, "stitched_no_gate_return_pct": 8,
                "worst_gated_mdd_pct": -18, "worst_no_gate_mdd_pct": -17
            }
        }]
    }
    priority = {
        "generated_at": "2026-08-15T00:03:00+00:00",
        "families": [{
            "id": "f1", "name": "Family 1", "strategies": ["s1"],
            "summary": {
                "rules": {
                    "current": {"stitched_test_return_pct": 5, "worst_test_mdd_pct": -20},
                    "quality_pct": {
                        "mean_delta_vs_current_pct": 1.5, "folds_beating_current": 4,
                        "worst_test_mdd_pct": -20.5, "total_test_trades": 100,
                        "stitched_test_return_pct": 12, "positive_test_folds": 4,
                        "median_test_return_pct": 1.2
                    },
                    "hybrid_50": {
                        "mean_delta_vs_current_pct": .2, "folds_beating_current": 2,
                        "worst_test_mdd_pct": -19, "total_test_trades": 100,
                        "stitched_test_return_pct": 6, "positive_test_folds": 3,
                        "median_test_return_pct": .3
                    }
                },
                "current_slot_audit": {"capacity_rejected_plus5": 2}
            }
        }]
    }
    flow = {
        "ready": True, "generated_at": "2026-08-15T00:04:00+00:00",
        "family": {"id": "f1", "name": "Family 1", "strategies": ["s1"]},
        "summary": {
            "pattern": "repeats_but_development_only",
            "strong_minus_weak_mean_return_pp": 2.2,
            "comparable_folds": 5, "strong_beats_weak_folds": 4
        }
    }
    smart = {
        "ready": True, "generated_at": "2026-08-15T00:05:00+00:00",
        "families": [{
            "id": "f1", "name": "Family 1", "strategies": ["s1"],
            "summary": {
                "pattern": "supported_development_only",
                "best_fixed_filter": "strong",
                "variants": {
                    "baseline": {"fold_count": 6, "stitched_test_return_pct": 8, "total_test_trades": 120, "positive_folds": 3, "median_test_return_pct": .2},
                    "watch_plus": {
                        "fold_count": 6, "folds_beating_baseline": 4,
                        "mean_delta_return_vs_baseline_pct": 1.1,
                        "stitched_delta_vs_baseline_pct": 5.0,
                        "worst_mdd_delta_vs_baseline_pct": 1.0,
                        "total_test_trades": 80, "stitched_test_return_pct": 13,
                        "positive_folds": 4, "median_test_return_pct": .8,
                    },
                    "strong": {
                        "fold_count": 6, "folds_beating_baseline": 5,
                        "mean_delta_return_vs_baseline_pct": 1.6,
                        "stitched_delta_vs_baseline_pct": 12.0,
                        "worst_mdd_delta_vs_baseline_pct": 0.5,
                        "total_test_trades": 160, "stitched_test_return_pct": 18,
                        "positive_folds": 5, "median_test_return_pct": 1.2,
                    },
                },
            },
            "folds": [
                {"variants": {"baseline": {"return_pct": 1.0}, "strong": {"return_pct": 3.0}}},
                {"variants": {"baseline": {"return_pct": 0.5}, "strong": {"return_pct": 2.5}}},
                {"variants": {"baseline": {"return_pct": 1.5}, "strong": {"return_pct": 3.5}}},
                {"variants": {"baseline": {"return_pct": 0.0}, "strong": {"return_pct": 2.0}}},
                {"variants": {"baseline": {"return_pct": 1.0}, "strong": {"return_pct": 2.8}}},
                {"variants": {"baseline": {"return_pct": 0.5}, "strong": {"return_pct": 2.2}}},
            ],
        }],
    }
    return wf, regime, vol, priority, flow, smart


def test_queue_generation_and_safety():
    wf, regime, vol, priority, flow, smart = fake_sources()
    items = generate(wf, regime, vol, priority, flow, smart)
    kinds = {x["kind"] for x in items}
    assert "volatility_state_sizing_v2" in kinds
    assert "regime_gate_review" in kinds
    assert "priority_ranker_review" in kinds
    assert "flow_selection_review" in kinds
    assert "smart_money_selection_review" in kinds
    assert all(x["status"] == "QUEUED" for x in items)


def test_terminal_result_is_stable_until_source_changes():
    wf, regime, vol, priority, flow, smart = fake_sources()
    items = generate(wf, regime, vol, priority, flow, smart)
    first = items[0]
    old = {"items": [{**first, "status": "DROP", "decision": "done", "attempts": 1}]}
    merged, _ = merge_previous(items, old, "2026-08-15T01:00:00+00:00")
    same = next(x for x in merged if x["key"] == first["key"])
    assert same["status"] == "DROP"
    changed = dict(same)
    changed["source_fingerprint"] = "changed"
    merged2, _ = merge_previous(items, {"items": [changed]}, "2026-08-15T02:00:00+00:00")
    again = next(x for x in merged2 if x["key"] == first["key"])
    assert again["status"] == "RETEST"


def test_evidence_decisions():
    _, regime, _, priority, flow, smart = fake_sources()
    base = {"family_id": "f1"}
    assert evidence_regime_gate(base, regime)["status"] == "CHALLENGER_CANDIDATE"
    assert evidence_priority_ranker({**base, "params": {"ranker": "quality_pct"}}, priority)["status"] == "CHALLENGER_CANDIDATE"
    assert evidence_flow_selection(base, flow)["status"] == "WATCH"
    sm=evidence_smart_money_selection({**base,"params":{"fixed_filter":"strong"}},smart)
    assert sm["status"] == "CHALLENGER_CANDIDATE"
    assert sm["evidence"]["stitched_delta_vs_baseline_pct"] == 12.0

    weak_priority = {
        "families": [{
            "id": "f1",
            "summary": {"rules": {
                "current": {"stitched_test_return_pct": -8, "worst_test_mdd_pct": -27},
                "hybrid_50": {
                    "folds_beating_current": 4,
                    "mean_delta_vs_current_pct": 1.5,
                    "worst_test_mdd_pct": -26.5,
                    "total_test_trades": 300,
                    "stitched_test_return_pct": 3.4,
                    "positive_test_folds": 2,
                    "median_test_return_pct": -1.2,
                },
            }}
        }]
    }
    weak = evidence_priority_ranker({**base, "params": {"ranker": "hybrid_50"}}, weak_priority)
    assert weak["status"] == "WATCH"


    concentrated = {
        "families": [{
            "id": "f1",
            "summary": {
                "pattern": "supported_development_only",
                "best_fixed_filter": "strong",
                "variants": {
                    "strong": {
                        "fold_count": 6,
                        "folds_beating_baseline": 4,
                        "mean_delta_return_vs_baseline_pct": 7.6,
                        "stitched_delta_vs_baseline_pct": 47.0,
                        "worst_mdd_delta_vs_baseline_pct": -2.0,
                        "total_test_trades": 235,
                        "stitched_test_return_pct": 35.0,
                        "positive_folds": 4,
                        "median_test_return_pct": 3.0,
                    }
                },
            },
            "folds": [
                {"variants": {"baseline": {"return_pct": 1.88}, "strong": {"return_pct": -6.95}}},
                {"variants": {"baseline": {"return_pct": -0.19}, "strong": {"return_pct": 1.41}}},
                {"variants": {"baseline": {"return_pct": -6.76}, "strong": {"return_pct": -10.4}}},
                {"variants": {"baseline": {"return_pct": -22.77}, "strong": {"return_pct": 5.35}}},
                {"variants": {"baseline": {"return_pct": -2.21}, "strong": {"return_pct": 8.13}}},
                {"variants": {"baseline": {"return_pct": 21.83}, "strong": {"return_pct": 40.28}}},
            ],
        }]
    }
    concentration_guard = evidence_smart_money_selection(
        {**base, "params": {"fixed_filter": "strong"}},
        concentrated,
    )
    assert concentration_guard["status"] == "WATCH"
    assert concentration_guard["evidence"]["leave_one_fold_out_min_absolute_stitched_pct"] < 0


def test_state_profile_never_leverages_above_baseline():
    pairs = [
        ({"_vol_state": "green_low_vol"}, {"risk_fraction": .10}),
        ({"_vol_state": "green_mid_vol"}, {"risk_fraction": .10}),
        ({"_vol_state": "green_high_vol"}, {"risk_fraction": .10}),
    ]
    rows = adjusted_rows_by_state_profile(
        pairs,
        {"green_low_vol": .25, "green_mid_vol": .50, "green_high_vol": 1.0},
    )
    assert [round(x["risk_fraction"], 3) for x in rows] == [.025, .05, .10]
    assert all(x["risk_fraction"] <= .10 for x in rows)


if __name__ == "__main__":
    test_queue_generation_and_safety()
    test_terminal_result_is_stable_until_source_changes()
    test_evidence_decisions()
    test_state_profile_never_leverages_above_baseline()
    print("auto experiment loop PASS")
