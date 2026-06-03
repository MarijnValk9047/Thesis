# Stochastic Bidding Backtest Loop

## Purpose

Phase 4b completes the toy end-to-end loop:

1. solve the stochastic bidding model;
2. extract the first-stage submitted bid curve;
3. clear that bid curve against a realised ex-post price path;
4. redispatch deterministically from the realised cleared electricity;
5. report realised pay-as-cleared settlement and realised adjusted profit.

This is still a toy-only validation phase. It is not yet thesis-grade scenario integration.

## Scenario evaluation inside optimisation vs realised backtesting

Inside the stochastic optimisation:

- the model evaluates multiple toy scenarios;
- the bid curve is chosen to maximise probability-weighted expected adjusted profit;
- clearing is scenario-specific;
- recourse is scenario-specific.

In realised backtesting:

- the submitted bid curve is already fixed;
- one realised price path is applied ex post;
- clearing is computed against that realised path only;
- physical operation is then redispatched deterministically from that realised cleared electricity.

So the scenario objective and the realised backtest answer different questions:

- scenario objective: what looked best ex ante under the scenario distribution?
- realised backtest: what actually happened under one realised price path?

Both must be reported separately.

## Why the submitted bid curve is first-stage

The submitted bid curve is the first-stage market decision.

It is made before the actual day-ahead clearing price is known, so it must be non-anticipative:

- one common bid curve;
- no scenario-specific bid quantities;
- no use of realised actual prices when forming bids.

That is why the saved submitted bid file has no `scenario_id` column.

## Why actual clearing is needed after solving

The stochastic bidding solve does not end the market workflow.

It only produces the submitted bid curve.

To evaluate realised performance, that same bid curve must still be cleared against a realised price path:

- accepted if `bid_price >= actual_price`;
- rejected otherwise.

Only after this actual clearing step do we know the electricity that was really procured.

## Why redispatch is deterministic after realised clearing

Once realised clearing is known, the uncertainty in this toy wrapper is over for that day.

The remaining task is physical feasibility:

- given the electricity that cleared,
- how should the plant operate?

That is a deterministic redispatch problem, not another stochastic bidding problem.

Redispatch must respect:

- `used_energy + unused_cleared_energy = cleared_energy`
- plant limits
- hydrogen storage dynamics
- shortfall logic
- terminal inventory correction
- `C_unused`

So the realised wrapper uses the existing deterministic redispatch model from Phase 3.

## Pay-as-cleared settlement

Settlement uses:

- realised actual price
- realised cleared energy

It does **not** use the bid price as the paid price.

For realised backtesting:

- `realised_DA_settlement_cost = sum(actual_price * cleared_energy)`

The bid price only determines acceptance.

## Regularisation note

The stochastic bidding model includes a tiny bid-quantity regularisation term only to break degeneracy among economically equivalent never-clearing bid allocations.

Phase 4b reports:

- objective with regularisation;
- expected adjusted profit without regularisation;
- regularisation term;
- regularisation weight.

This term should remain negligible and must not be interpreted as an economic feature of the model.

## Why this is still toy-only

This wrapper is intentionally not thesis-grade yet because:

- scenario inputs are still artificial;
- realised actual paths are still artificial;
- there is no real scenario metadata integration yet;
- there is no CVaR yet;
- there is no quarter-hour support yet;
- there is no D+4 extension yet;
- there is no mFRR layer yet.

The purpose of Phase 4b is narrower:

- prove that the end-to-end market loop is coherent;
- prove that actual clearing is separate from scenario evaluation;
- prove that redispatch only uses realised cleared electricity;
- prove that expected and realised outcomes can be reported cleanly side by side.
