# Yahoo PIT-Lite survivorship stress — 2026-08-14

## Decision

Use free Yahoo/yfinance data first. Do not purchase EODHD now.

This track is intentionally named **PIT-Lite** rather than full Point-in-Time validation because the free Yahoo probe recovered strategy-usable history for only about 45% of historical non-current S&P 500 tickers. Missing former/delisted names remain missing; they are never replaced with today's constituents and are never assumed to have zero return.

## What the new research compares

Both sides use the same historical S&P 500 membership framework, the same three-strategy family, the same TRAIN-only top-50% quality gate, the same TRAIN-only hybrid priority, the same natural exits, and the same 0.75% account-risk / max-10 portfolio policy.

1. **Survivors-only control** — historical signals are allowed only for tickers that are also members of the latest S&P 500 snapshot.
2. **Yahoo PIT-Lite** — add every historical S&P 500 member whose free Yahoo history is available enough to generate the strategy.

A signal and its next-open entry must both occur while the ticker is in the historical membership snapshot. The study uses complete calendar TEST years through 2025 so the last partial 2026 year does not distort the comparison.

## What this can answer

- Does adding recoverable former constituents materially reduce historical returns?
- Does worst daily-close MTM drawdown get worse?
- Do trade count, cash starvation, and portfolio breadth change?
- Is the effect repeated across multiple rolling TEST years or concentrated in one year?

## What this cannot prove

- It is not fully survivorship-free because more than half of historical non-current names are still missing from free Yahoo history.
- Historical ticker strings are not permanent security IDs. Ticker reuse, mergers, spin-offs, and corporate-action continuity can remain ambiguous.
- The S&P 500 is a large-cap stress universe, not the exact production liquid-stock screener universe.
- 2021–2025 has already influenced the project, so the result is development stress evidence, not a fresh promotion holdout.

## Safety

The PIT-Lite workflow is isolated. It must not modify:

- the production/main candidate picker,
- the current-universe replay pool,
- Frozen Forward Challenger V1/V2/V3/V4,
- PaperBroker/live-order rules.

The main promotion evidence remains prospective Forward data from the frozen challengers.

## Roadmap after PIT-Lite

1. Read PIT-Lite survivorship sensitivity.
2. Keep V2/V3/V4 Forward frozen and accumulating.
3. Do not add more historical V5/V6 hypotheses unless a genuinely new independent failure mode appears.
4. Once Forward closed-trade counts are meaningful, perform the pre-frozen review milestones.
5. If one challenger is robust across Forward return, drawdown, allocation/cash diagnostics, and enough elapsed market regimes, move only that winner into a paper-broker promotion stage.
6. Only after paper execution parity and safety checks consider connecting a real broker API. Live trading remains disabled until an explicit later decision.
