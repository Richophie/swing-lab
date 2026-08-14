from datetime import date

import strategy_optimizer_runner as runner


def test_open_position_drawdown_is_marked_daily():
    rows = [
        {
            "start_date": "2026-01-02",
            "end_date": "2026-01-06",
            "change": 0.10,
            "risk_fraction": 0.10,
            "priority": 1.0,
            "key": "AAA|demo|2026-01-01",
            "symbol": "AAA",
            "strategy_id": "demo",
            "marks": [
                ("2026-01-02", 0.90),
                ("2026-01-05", 0.80),
                ("2026-01-06", 1.10),
            ],
        }
    ]
    result = runner.mtm_portfolio(
        rows,
        date(2026, 1, 2),
        date(2026, 1, 6),
        1,
    )

    # 3,000,000 equity; 1% risk / 10% stop distance => 300,000 position.
    # Daily close marks 0.90 then 0.80 make account equity 2,970,000 then
    # 2,940,000 before the +10% exit. The true MTM drawdown is therefore -2%.
    assert round(result["mdd"], 6) == -0.02
    assert round(result["ending"], 2) == 3_030_000.00
    assert result["underwater_days"] == 2
    assert result["mtm"] is True


def test_position_size_uses_previous_marked_equity():
    rows = [
        {
            "start_date": "2026-01-02",
            "end_date": "2026-01-07",
            "change": 0.0,
            "risk_fraction": 0.10,
            "priority": 2.0,
            "key": "AAA|demo|1",
            "symbol": "AAA",
            "strategy_id": "demo",
            "marks": [
                ("2026-01-02", 0.50),
                ("2026-01-05", 0.50),
                ("2026-01-06", 0.50),
                ("2026-01-07", 1.00),
            ],
        },
        {
            "start_date": "2026-01-05",
            "end_date": "2026-01-06",
            "change": 0.0,
            "risk_fraction": 0.10,
            "priority": 1.0,
            "key": "BBB|demo|2",
            "symbol": "BBB",
            "strategy_id": "demo",
            "marks": [
                ("2026-01-05", 1.0),
                ("2026-01-06", 1.0),
            ],
        },
    ]
    result = runner.mtm_portfolio(
        rows,
        date(2026, 1, 2),
        date(2026, 1, 7),
        2,
    )
    assert result["trades"] == 2
    assert result["max_open"] == 2
    assert result["mdd"] < 0


if __name__ == "__main__":
    test_open_position_drawdown_is_marked_daily()
    test_position_size_uses_previous_marked_equity()
    print("MTM portfolio PASS")
