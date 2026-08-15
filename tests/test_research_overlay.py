from __future__ import annotations

from research_overlay import overlay_for_strategy, research_profiles


def main():
    bundle = research_profiles()
    assert isinstance(bundle, dict)
    assert bundle.get("ready") is True

    policy = bundle.get("policy") or {}
    assert policy.get("mode") == "soft_rank_only"
    assert policy.get("max_score_adjustment") == 2.0
    assert policy.get("hard_gate_mutated") is False
    assert policy.get("buy_target_stop_mutated") is False
    assert policy.get("automatic_production_promotion") is False

    profiles = bundle.get("profiles") or {}
    assert "momentum_pullback" in profiles
    assert "confirmed_pullback" in profiles
    assert "rsi2_trend_reversion" in profiles

    for strategy_id, profile in profiles.items():
        adjustment = float(profile.get("score_adjustment") or 0)
        assert -1.5 <= adjustment <= 2.0, (strategy_id, adjustment)
        assert profile.get("policy") == "soft_rank_only"
        assert profile.get("tone") in {"lead", "support", "watch", "neutral"}

        over = overlay_for_strategy(strategy_id, 80.0)
        expected = max(0.0, min(99.0, 80.0 + adjustment))
        assert abs(float(over["research_rank_score"]) - expected) < 1e-9
        assert float(over["base_elite_score"]) == 80.0

    unknown = overlay_for_strategy("not_a_real_strategy", 75.0)
    assert unknown["score_adjustment"] == 0.0
    assert unknown["research_rank_score"] == 75.0
    assert unknown["policy"] == "soft_rank_only"

    print("research overlay PASS", {k: v.get("score_adjustment") for k, v in profiles.items()})


if __name__ == "__main__":
    main()
