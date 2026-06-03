# Stochastic Hourly Bidding Model

## Purpose

Phase 4a adds the first true stochastic hourly bidding MILP for the hydrogen test case.

This phase is intentionally narrow:

- toy scenarios only;
- hourly only;
- one delivery day only;
- fixed bid-price tiers only;
- risk-neutral expected objective only;
- no CVaR yet;
- no real thesis-grade scenario artifacts yet.

The goal is to prove the bidding logic before connecting it to real scenario inputs.

## How this differs from schedule-and-settle

The earlier schedule-and-settle model chooses a physical dispatch first and settles that dispatch against prices later.

This Phase 4a model changes the sequence:

1. submit a first-stage demand bid curve;
2. clear that bid curve separately in each price scenario;
3. operate the plant with scenario-dependent recourse after scenario-specific clearing;
4. optimise expected realised-style scenario profit.

So uncertainty can now affect both:

- electricity cost;
- electricity availability.

That is the core distinction needed for the downstream thesis question.

## First-stage bid quantities

The first-stage decision is:

- `q[t,b] >= 0`

where:

- `t` is the delivery hour;
- `b` is a fixed bid-price block.

`q[t,b]` is **not** scenario-indexed.

There is exactly one submitted bid curve shared by all scenarios. That is the non-anticipativity requirement for this phase.

## Fixed bid-price tiers

Bid prices are fixed exogenously on a grid, for example:

- `[0, 100, 158, 250, 3000] EUR/MWh`

The optimiser chooses quantities on that grid. It does **not** optimise bid prices endogenously in this phase.

This keeps the acceptance rule transparent and avoids introducing a more complex bidding design before the first-stage/second-stage structure is validated.

## Scenario-specific clearing

For each scenario `s`, hour `t`, and bid block `b`, an acceptance parameter is precomputed:

- `a[s,t,b] = 1` if `bid_price[b] >= scenario_price[s,t]`
- `a[s,t,b] = 0` otherwise

Cleared electricity in scenario `s` and hour `t` is:

- `E_cleared[s,t] = delta_t * sum_b a[s,t,b] * q[t,b]`

This is price-taking clearing with fixed acceptance thresholds.

It is **not**:

- full EUPHEMIA;
- endogenous market clearing;
- exclusive group bidding;
- price-making behaviour.

## Scenario-dependent recourse

After clearing is known in a scenario, the hydrogen plant re-optimises operation inside that scenario subject to:

- electrolyser min/max power;
- electrolyser ramping;
- compressor max power;
- hydrogen production efficiency;
- hydrogen storage balance;
- storage bounds;
- reserve floor;
- target / shortfall logic;
- terminal inventory correction;
- allowed above-target production.

The plant may only use cleared electricity. The core identity is:

- `used_energy[s,t] + unused_cleared_energy[s,t] = E_cleared[s,t]`

with:

- `used_energy[s,t] = delta_t * (electrolyser_power[s,t] + compressor_power[s,t])`

So the model cannot silently consume uncleared electricity, and it cannot silently ignore paid-but-unused cleared electricity either.

## Pay-as-cleared principle

The bid price is only an acceptance threshold.

Accepted energy pays the scenario market price:

- `settlement_cost[s] = sum_t scenario_price[s,t] * E_cleared[s,t]`

It does **not** pay the bid price.

This is a required modelling point because:

- bid price decides acceptance;
- scenario market price decides settlement.

## Objective convention

Phase 4a uses:

- **maximize expected adjusted profit**

Per scenario:

- hydrogen revenue
- minus DA settlement cost
- minus unused-cleared-energy penalty
- minus shortfall penalty
- plus terminal inventory correction

The objective is probability-weighted across scenarios. There is no CVaR term yet.

A tiny bid-quantity regularisation is included only to remove degenerate never-clearing bids in toy cases. It is not a substantive economic feature.

## Why toy scenarios only

Real thesis-grade scenario artifacts are still blocked. This phase therefore uses only small artificial scenarios with:

- explicit scenario IDs;
- explicit probabilities summing to 1;
- coherent hourly price paths;
- fixed bid-price tiers chosen to force mixed clearing.

That is deliberate. The purpose here is to validate model structure, not to claim empirical thesis results from placeholder scenario inputs.

## Why CVaR is excluded here

CVaR is intentionally deferred because this phase must first prove:

- non-anticipative first-stage bid quantities;
- scenario-specific clearing against fixed bid-price tiers;
- valid second-stage physical recourse;
- probability-weighted expected objective;
- machine-readable bid, clearing, dispatch, and settlement outputs.

Adding CVaR before those elements are clearly verified would make debugging and interpretation harder.

## Current limitations

- toy scenario coverage only;
- hourly only;
- one-day only;
- no realised actual-price clearing in this module yet;
- no quarter-hour support;
- no D+4 planning horizon;
- no mFRR;
- no exclusive group bids;
- no endogenous bid prices;
- no real scenario integration.

Those are intentional Phase 4a boundaries, not omissions by accident.
