from auto_experiment_queue import generate, merge_previous
from auto_experiment_runner import evidence_flow_selection, evidence_priority_ranker, evidence_regime_gate


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
        "families": [{"id": "f1", "summary": {"green_high_vol_drag_pattern": "strong"}}]
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
                        "stitched_test_return_pct": 12
                    },
                    "hybrid_50": {
                        "mean_delta_vs_current_pct": .2, "folds_beating_current": 2,
                        "worst_test_mdd_pct": -19, "total_test_trades": 100,
                        "stitched_test_return_pct": 6
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
    return wf, regime, vol, priority, flow


def test_queue_generation_and_safety():
    wf, regime, vol, priority, flow = fake_sources()
    items = generate(wf, regime, vol, priority, flow)
    kinds = {x["kind"] for x in items}
    assert "adaptive_volatility_sizing" in kinds
    assert "regime_gate_review" in kinds
    assert "priority_ranker_review" in kinds
    assert "flow_selection_review" in kinds
    assert all(x["status"] == "QUEUED" for x in items)


def test_terminal_result_is_stable_until_source_changes():
    wf, regime, vol, priority, flow = fake_sources()
    items = generate(wf, regime, vol, priority, flow)
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
    _, regime, _, priority, flow = fake_sources()
    base = {"family_id": "f1"}
    assert evidence_regime_gate(base, regime)["status"] == "CHALLENGER_CANDIDATE"
    assert evidence_priority_ranker({**base, "params": {"ranker": "quality_pct"}}, priority)["status"] == "CHALLENGER_CANDIDATE"
    assert evidence_flow_selection(base, flow)["status"] == "WATCH"


if __name__ == "__main__":
    test_queue_generation_and_safety()
    test_terminal_result_is_stable_until_source_changes()
    test_evidence_decisions()
    print("auto experiment loop PASS")
