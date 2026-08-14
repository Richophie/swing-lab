# Forward Review + PaperBroker Gate

Date: 2026-08-14

## Purpose

Historical tuning is paused. The next promotion decision must come from genuinely new Forward observations, not another search over the same development history.

This layer reads the frozen V1/V2/V3/V4 Forward states and answers two separate questions:

1. Is the PaperBroker infrastructure technically ready for simulated execution?
2. Is there enough Forward evidence to begin a human promotion review of a strategy?

Those are intentionally different gates.

## State machine

- `BLOCKED_SAFETY`: any challenger is no longer Forward-shadow-only, live/production mutation is enabled, auto-retune/human intervention is enabled, or the state contains errors.
- `BLOCKED_PAPER_INFRA`: the local simulated broker, API contract, persistence/restore components, or their regression-test contract is missing.
- `WAIT_FORWARD_SAMPLE`: infrastructure and safety are fine, but at least one challenger has fewer than 30 closed Forward trades.
- `HUMAN_REVIEW_READY`: every challenger has at least 30 closed Forward trades and all safety/infrastructure checks pass.

`HUMAN_REVIEW_READY` is not automatic promotion. It only allows a person to compare V1–V4 and nominate one Paper candidate.

## First review threshold

The first review threshold is fixed at **30 closed Forward trades for every V1–V4 challenger**.

This is a coarse operational milestone, not a claim of statistical proof. We do not tune the threshold after seeing which challenger reaches a favorable result first.

## What the review shows

The integrated dashboard reports, for every challenger:

- Forward MTM return and equity
- open and closed positions
- cash-rejection counts
- progress toward 30 closed trades
- safety-state checks
- V2 vs V1, V3 vs V2, and V4 vs V2 deltas

Pairwise deltas are visible before 30 trades for observability, but the UI labels the comparison as **판정 보류** until both sides satisfy the threshold.

## PaperBroker meaning

`paper_infrastructure.ready = true` means the existing local simulated broker plumbing is present and has a regression-test contract.

It does **not** mean:

- a Forward strategy has been promoted,
- a real brokerage account is connected,
- external orders can be sent,
- or the production picker has changed.

The current PaperBroker remains `LOCAL_SIMULATED_ONLY`. Real broker connectivity and external order submission stay disabled.

## Immutable guardrails during Forward

- V1–V4 remain frozen; only correctness/safety fixes are allowed.
- Research history does not auto-select a Forward winner.
- This review engine only reads challenger states and writes `static/forward_review.json`.
- It must not modify calibration/state files.
- Passing the review gate must never auto-promote a strategy or submit a real order.
- Production main-picker rules remain unchanged.

## Current expected state

At the time this gate was introduced, all four Forward challengers had 0 closed trades. Therefore the expected state is:

`WAIT_FORWARD_SAMPLE` — PaperBroker infrastructure ready, official strategy promotion waiting for future Forward evidence.
